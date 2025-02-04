import datetime
import time
import logging
import re
from collections import defaultdict

import execjs
from bs4 import BeautifulSoup

from .exceptions import URLException
from .session import SessionMgr

logger = logging.getLogger(__name__)


class ComicBookItem():
    FIELDS = ["comicid", "name", "desc", "tag", "cover_image_url", "author",
              "source_url", "source_name", "crawl_time", "chapters", "ext_chapters",
              "status", 'tags', "site", "last_update_time"]

    def __init__(self, comicid=None, name=None, desc=None, cover_image_url=None,
                 author=None, source_url=None, source_name=None,
                 crawl_time=None, status=None, site=None, last_update_time=None,
                 default_ext_name=None, **kwargs):
        self.comicid = comicid or ""
        self.name = name or ""
        self.desc = desc or ""
        self.cover_image_url = cover_image_url or ""
        self.author = author or ""
        self.source_url = source_url or ""
        self.source_name = source_name or ""
        self.crawl_time = crawl_time or datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.status = status or ""
        self.site = site or ""
        self.last_update_time = last_update_time or ""
        self.default_ext_name = default_ext_name

        # {'番外篇': {1: Citem(chapter_number=1, title="xx", cid="xxx"}}
        self.citems = defaultdict(dict)
        self.tags = []

    @property
    def tag(self):
        return ",".join([tag['name'] for tag in self.tags])

    def to_dict(self):
        return {field: getattr(self, field) for field in self.FIELDS}

    def add_tag(self, name, tag=None):
        tag = tag or ''
        if name:
            self.tags.append(dict(name=name, tag=tag))

    def add_chapter(self, chapter_number, title, source_url, ext_name=None, **kwargs):
        ext_name = ext_name or ''
        self.citems[ext_name][chapter_number] = Citem(
            chapter_number=chapter_number, title=title, source_url=source_url, **kwargs)

    def citems_to_list(self, citems):
        rv = []
        for citem in sorted(citems.values(), key=lambda x: x.chapter_number):
            rv.append(
                {
                    "title": citem.title,
                    "chapter_number": citem.chapter_number,
                    "source_url": citem.source_url,
                }
            )
        return rv

    @property
    def chapters(self):
        ext_name = self.default_ext_name
        return self.citems_to_list(self.citems[ext_name])

    @property
    def ext_chapters(self):
        ret = []
        for ext_name in self.citems:
            if ext_name != self.default_ext_name:
                ext_info = dict(ext_name=ext_name, chapters=self.citems_to_list(self.citems[ext_name]))
                ret.append(ext_info)
        return ret


class Citem():

    def __init__(self, **kwargs):
        self._kwargs = kwargs
        for k, v in kwargs.items():
            setattr(self, k, v)

    def to_dict(self):
        return self._kwargs


class ChapterItem():
    FIELDS = ["comicid", "chapter_number", "title", "image_urls", "source_url", "site", "source_name"]

    def __init__(self, comicid, chapter_number, title, image_urls,
                 source_url=None, site=None, source_name=None,
                 image_pipelines=None):
        self.chapter_number = chapter_number
        self.title = title or ""
        self.image_urls = image_urls or []
        self.source_url = source_url or ""
        self.site = site or ""
        self.source_name = source_name or ""
        self.image_pipelines = image_pipelines
        self.comicid = comicid or ""

    def to_dict(self):
        return {field: getattr(self, field) for field in self.FIELDS}


class SearchResultItem():
    FIELDS = ["comicid", "name", "cover_image_url", "source_url", "status", "site", "source_name"]

    def __init__(self, site=None, source_name=None):
        self._result = []
        self.site = site or ""
        self.source_name = source_name or ""

    def add_result(self, comicid, name, cover_image_url, source_url, status=None):
        status = status or ""
        item = Citem(comicid=comicid, name=name,
                     cover_image_url=cover_image_url, source_url=source_url,
                     status=status, site=self.site, source_name=self.source_name)
        self._result.append(item)

    def __iter__(self):
        return iter(self._result)

    def to_dict(self):
        return [i.to_dict() for i in self._result]


class TagsItem():

    def __init__(self):
        self.tags = []

    def add_tag(self, category, name, tag):
        for t1 in self.tags:
            if t1['category'] == category:
                for t2 in t1['tags']:
                    if tag == t2['tag']:
                        return
                t1['tags'].append(dict(name=name, tag=tag))
                return
        self.tags.append(dict(category=category, tags=[]))
        self.tags[-1]['tags'].append(dict(name=name, tag=tag))

    def to_dict(self):
        return self.tags

    def __iter__(self):
        return iter(self.tags)


class CrawlerBase():

    SOURCE_NAME = "未知"
    SITE = ""
    SITE_INDEX = ""
    LOGIN_URL = ""

    COMICID_PATTERN = re.compile(r'(.*)')
    DEFAULT_COMICID = None
    DEFAULT_SEARCH_NAME = ''
    DEFAULT_TAG = ''
    DEFAULT_EXT_NAME = ""

    DRIVER_PATH = None
    DRIVER_TYPE = None
    DEFAULT_DRIVER_TYPE = "Chrome"
    SUPPORT_DRIVER_TYPE = frozenset(["Firefox", "Chrome", "Opera", "Ie", "Edge"])
    DRIVER_INSTANCE = None
    HEADLESS = False

    # 是否需要 nodejs 环境
    REQUIRE_JAVASCRIPT = False
    TAGS = None
    R18 = False

    # 站点编码
    SITE_ENCODEING = None
    # 是否只有单话
    SINGLE_CHAPTER = None

    _TAGS_INFO = None
    NODE_MODULES = ''

    def __init__(self):
        self.timeout = 30
        self._tag_info = None
        if self.REQUIRE_JAVASCRIPT:
            try:
                execjs.get()
            except Exception:
                raise RuntimeError('pleaese install nodejs first. https://nodejs.org/zh-cn/')

    def set_timeout(self, timeout=30):
        self.timeout = timeout

    def get_session(self):
        return SessionMgr.get_session(site=self.SITE)

    def export_session(self, path):
        SessionMgr.export_session(site=self.SITE, path=path)

    def load_session(self, path):
        SessionMgr.load_session(site=self.SITE, path=path)

    def load_cookies(self, path):
        SessionMgr.load_cookies(site=self.SITE, path=path)

    def export_cookies(self, path):
        SessionMgr.export_cookies(site=self.SITE, path=path)

    def send_request(self, method, url, **kwargs):
        session = self.get_session()
        kwargs.setdefault('headers', {'Referer': self.SITE_INDEX})
        kwargs.setdefault('timeout', self.timeout)
        try:
            logger.debug('send_request. url=%s kwargs=%s', url, kwargs)
            return session.request(method=method, url=url, **kwargs)
        except Exception as e:
            msg = "URL error. url={}".format(url)
            raise URLException(msg) from e

    def get_html(self, url, encoding=None, **kwargs):
        response = self.send_request("GET", url, **kwargs)
        site_encoding = encoding or self.SITE_ENCODEING
        if site_encoding:
            return response.content.decode(site_encoding)
        return response.text

    def get_html_and_soup(self, url, encoding=None, **kwargs):
        html = self.get_html(url, encoding=encoding, **kwargs)
        soup = BeautifulSoup(html, 'html.parser')
        return html, soup

    def get_soup(self, url, encoding=None, **kwargs):
        html = self.get_html(url, encoding=encoding, **kwargs)
        return BeautifulSoup(html, 'html.parser')

    def get_json(self, url, **kwargs):
        response = self.send_request("GET", url, **kwargs)
        return response.json()

    @classmethod
    def get_comicid_by_url(cls, comicid_or_url):
        if comicid_or_url and isinstance(comicid_or_url, str):
            r = cls.COMICID_PATTERN.search(comicid_or_url)
            if r:
                return r.group(1)
        return comicid_or_url

    def get_comicbook_item(self):
        """
        :return ComicBookItem instance:
        """
        raise NotImplementedError

    def get_chapter_item(self, chapter_number):
        """
        :return ChapterItem instance:
        """
        raise NotImplementedError

    def new_comicbook_item(self, **kwargs):
        comicid = getattr(self, 'comicid')
        return ComicBookItem(site=self.SITE, comicid=comicid, source_name=self.SOURCE_NAME,
                             default_ext_name=self.DEFAULT_EXT_NAME, **kwargs)

    def new_chapter_item(self, **kwargs):
        comicid = getattr(self, 'comicid')
        return ChapterItem(site=self.SITE, comicid=comicid, source_name=self.SOURCE_NAME, **kwargs)

    def new_search_result_item(self, **kwargs):
        return SearchResultItem(site=self.SITE, source_name=self.SOURCE_NAME, **kwargs)

    def new_tags_item(self, **kwargs):
        return TagsItem(**kwargs)

    def search(self, name, page=1, size=None):
        """
        :return SearchResultItem:
        """
        return self.new_search_result_item()

    def latest(self, page=1):
        """
        :return SearchResultItem:
        """
        return self.new_search_result_item()

    def get_tags(self):
        """
        :return TagsItem:
        """
        return self.new_tags_item()

    def get_tag_result(self, tag, page=1):
        """
        :return SearchResultItem:
        """
        return self.new_search_result_item()

    def login(self):
        login_url = self.LOGIN_URL or self.SITE_INDEX
        self.selenium_login(login_url=login_url)

    def selenium_login(self, login_url, check_login_status_func=None):
        if callable(check_login_status_func):
            if check_login_status_func():
                logger.info("login success")
                return
        logger.info("Please complete login on your browser")
        driver = self.create_driver()
        driver.get(login_url)
        while True:
            logger.info("Waiting to login")
            time.sleep(3)
            try:
                cookies = []
                for cookie in driver.get_cookies():
                    cookies.append(
                        dict(name=cookie["name"],
                             value=cookie["value"],
                             path=cookie["path"],
                             domain=cookie["domain"],
                             secure=cookie["secure"])
                    )
            except Exception:
                logger.exception('unknow error. driver quit.')
                self.close_driver()
                return
            SessionMgr.update_cookies(site=self.SITE, cookies=cookies)
            if callable(check_login_status_func):
                if check_login_status_func():
                    logger.info("login success")
                    self.close_driver()
                    break

    def create_driver(self, **kwargs):
        try:
            from selenium import webdriver
        except ImportError:
            raise RuntimeError('pleaese install selenium first. python3 -m pip install selenium')

        if not self.DRIVER_PATH:
            raise RuntimeError("DRIVER_PATH must be set")

        if self.DRIVER_TYPE not in self.SUPPORT_DRIVER_TYPE:
            raise RuntimeError(
                "DRIVER_TYPE must be: {}".format(",".join(self.SUPPORT_DRIVER_TYPE)))

        if self.DRIVER_INSTANCE:
            return self.DRIVER_INSTANCE

        if self.DRIVER_TYPE == 'Chrome' and self.HEADLESS:
            from selenium.webdriver.chrome.options import Options
            options = Options()
            options.add_argument('--headless')
            prefs = {"profile.managed_default_content_settings.images": 2}
            options.add_experimental_option("prefs", prefs)
            driver = webdriver.Chrome(self.DRIVER_PATH, chrome_options=options)
        else:
            driver = getattr(webdriver, self.DRIVER_TYPE)(self.DRIVER_PATH, **kwargs)
        logger.info('new driver=%s', driver)
        self.DRIVER_INSTANCE = driver
        return self.DRIVER_INSTANCE

    def close_driver(self):
        if self.DRIVER_INSTANCE:
            self.DRIVER_INSTANCE.quit()
            self.DRIVER_INSTANCE = None
            logger.info('driver quit.')

    def __del__(self):
        self.close_driver()

    def get_tags_from_cache(self):
        if self._TAGS_INFO is None:
            self._TAGS_INFO = self.get_tags()
        return self._TAGS_INFO

    def get_tag_id_by_name(self, name):
        for group in self.get_tags_from_cache():
            for tag in group['tags']:
                if tag['name'] == name:
                    return tag['tag']
        return ''
