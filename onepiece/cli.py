import argparse
import os
import logging
import configparser
import time
from copy import deepcopy

from .comicbook import ComicBook
from .crawlerbase import CrawlerBase, Citem
from .utils import (
    parser_chapter_str,
    ensure_file_dir_exists,
    merge_books,
    merge_zip_books
)
from .session import SessionMgr
from .worker import WorkerPoolMgr
from .utils.mail import Mail
from . import VERSION
from .config import CrawlerConfig

logger = logging.getLogger(__name__)
HERE = os.path.abspath(os.path.dirname(__file__))


def parse_args():
    """
    根据腾讯漫画id下载图片,默认下载海贼王最新一集。

    下载海贼王最新一集:
    python3 onepiece.py

    下载漫画 id=505430 最新一集:
    python3 onepiece.py -id 505430

    下载漫画 id=505430 所有章节:
    python3 onepiece.py -id 505430 -m all

    下载漫画 id=505430 第800集:
    python3 onepiece.py -id 505430 -c 800

    下载漫画 id=505430 倒数第二集:
    python3 onepiece.py -id 505430 -c -2

    下载漫画 id=505430 1到5集,7集，9到10集:
    python3 onepiece.py -id 505430 -i 1-5,7,9-10
    """

    parser = argparse.ArgumentParser(prog="onepiece")

    parser.add_argument('-id', '--comicid', type=str,
                        help="漫画id，如海贼王: 505430 (http://ac.qq.com/Comic/ComicInfo/id/505430)")
    parser.add_argument('--url', type=str,
                        help="漫画id，如海贼王: http://ac.qq.com/Comic/ComicInfo/id/505430")
    parser.add_argument('--url-file', type=str, help="漫画URL列表")

    parser.add_argument('--ext-name', type=str, help="如：番外篇、单行本等。具体得看站点支持哪些")

    parser.add_argument('--name', type=str, help="漫画名")

    parser.add_argument('-c', '--chapter', type=str, default="-1",
                        help="要下载的章节, 默认下载最新章节。如 -c 666 或者 -c 1-5,7,9-10")

    parser.add_argument('--worker', type=int, help="线程池数，默认开启4个线程池")

    parser.add_argument('--all', action='store_true',
                        help="是否下载该漫画的所有章节, 如 --all")

    parser.add_argument('--pdf', action='store_true',
                        help="是否生成pdf文件, 如 --pdf")
    parser.add_argument('--single-image', action='store_true',
                        help="是否拼接成一张图片, 如 --single-image")
    parser.add_argument('--quality', type=int, help="生成长图的图片质量，最高质量100")
    parser.add_argument('--max-height', type=int, help="长图最大高度，最大高度65500")

    parser.add_argument('--login', action='store_true',
                        help="是否登录账号，如 --login")

    parser.add_argument('--mail', action='store_true',
                        help="是否发送pdf文件到邮箱, 如 --mail。需要预先配置邮件信息。\
                        可以参照config.ini.example文件，创建并修改config.ini文件")

    parser.add_argument('--receivers', type=str, help="邮件接收列表，多个以逗号隔开")
    parser.add_argument('--zip', action='store_true',
                        help="打包生成zip文件")

    parser.add_argument('--config', help="配置文件路径")

    parser.add_argument('-o', '--output', type=str,
                        help="文件保存路径，默认保存在当前路径下的download文件夹")

    s = ' '.join(['%s(%s)' % (crawler.SITE, crawler.SOURCE_NAME) for crawler in ComicBook.CRAWLER_CLS_MAP.values()])
    site_help_msg = "数据源网站：支持 %s" % s

    parser.add_argument('-s', '--site', type=str, choices=ComicBook.CRAWLER_CLS_MAP.keys(),
                        help=site_help_msg)

    parser.add_argument('--verify', action='store_true',
                        help="verify")

    parser.add_argument('--driver-path', type=str, help="selenium driver")

    parser.add_argument('--driver-type', type=str,
                        choices=CrawlerBase.SUPPORT_DRIVER_TYPE,
                        help="支持的浏览器: {}.".format(
                            ",".join(sorted(CrawlerBase.SUPPORT_DRIVER_TYPE)))
                        )

    parser.add_argument('--cookies-path', type=str, help="读取或保存上次使用的cookies路径")

    parser.add_argument('--latest-all', action='store_true', help="下载最近更新里的所有漫画")
    parser.add_argument('--latest-page', type=str, help="最近更新的页数，如1-10，默认第1页")

    parser.add_argument('--show-tags', action='store_true', help="展示当前支持的标签")
    parser.add_argument('--tag-all', action='store_true', help="下载标签里的所有漫画")
    parser.add_argument('--tag', type=str, help="标签id")
    parser.add_argument('--tag-page', type=str, help="标签页数，如1-10，默认第1页")

    parser.add_argument('--proxy', type=str,
                        help='设置代理，如 --proxy "socks5://user:pass@host:port"')

    parser.add_argument('--node-modules', type=str,
                        help="node_modules 模块目录")
    parser.add_argument('--merge', action='store_true', help="将多话合并成一个文件夹")
    parser.add_argument('--merge-zip', action='store_true', help="将多话合并成一个压缩包")
    parser.add_argument('--image-timeout', type=int, help="图片下载超时时间")
    parser.add_argument('--crawler-timeout', type=int, help="站点访问超时时间")
    parser.add_argument('--crawler-delay', type=int, help="每个章节下载时间间隔")
    parser.add_argument('--migrate', action='store_true', help="文件夹重命名(旧版本迁移用)")

    parser.add_argument('-V', '--version', action='version', version=VERSION)
    parser.add_argument('--debug', action='store_true', help="debug")

    args = parser.parse_args()
    return args


def init_logger(debug=False):
    level = logging.DEBUG if debug else logging.INFO
    logger = logging.getLogger()
    handler = logging.StreamHandler()
    formatter = logging.Formatter(
        "%(asctime)s %(name)s %(lineno)s [%(levelname)s] %(message)s",
        datefmt='%Y/%m/%d %H:%M:%S'
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(level)
    return logger


def download_main(comicbook, output_dir, ext_name=None, chapters=None,
                  is_download_all=None, is_gen_pdf=None, is_gen_zip=None,
                  is_single_image=None, quality=None, max_height=None, mail=None,
                  receivers=None, is_send_mail=None, merge=None, merge_zip=None,
                  crawler_delay=None):
    is_gen_pdf = is_gen_pdf or mail
    chapter_str = chapters or '-1'
    chapter_numbers = parser_chapter_str(chapter_str=chapter_str,
                                         last_chapter_number=comicbook.get_last_chapter_number(ext_name),
                                         is_all=is_download_all)
    chapter_dirs = []
    for chapter_number in chapter_numbers:
        try:
            chapter = comicbook.Chapter(chapter_number, ext_name=ext_name)
            logger.info("正在下载 【{}】 {} 【{}】".format(
                comicbook.name, chapter.chapter_number, chapter.title))

            chapter_dir = chapter.save(output_dir=output_dir)
            chapter_dirs.append(chapter_dir)
            logger.info("下载成功 %s", chapter_dir)
            if is_single_image:
                img_path = chapter.save_as_single_image(output_dir=output_dir, quality=quality, max_height=max_height)
                logger.info("生成长图 %s", img_path)
            if is_gen_pdf:
                pdf_path = chapter.save_as_pdf(output_dir=output_dir)
                logger.info("生成pdf文件 %s", pdf_path)

            if is_send_mail:
                mail.send(subject=os.path.basename(pdf_path),
                          content=None,
                          file_list=[pdf_path, ],
                          receivers=receivers)
            if is_gen_zip:
                zip_file_path = chapter.save_as_zip(output_dir=output_dir)
                logger.info("生成zip文件 %s", zip_file_path)
        except Exception:
            logger.exception('download comicbook error. site=%s comicid=%s chapter_number=%s',
                             comicbook.crawler.SITE, comicbook.crawler.comicid, chapter_number)
        if crawler_delay:
            logger.info("crawler delay. sleep %ss", crawler_delay)
            time.sleep(crawler_delay)

    start = chapter_numbers[0]
    end = chapter_numbers[-1]
    if merge:
        merge_dir = comicbook.get_merge_dir(output_dir=output_dir, start=start, end=end, ext_name=ext_name)
        ensure_file_dir_exists(dirpath=merge_dir)
        merge_books(chapter_dirs=chapter_dirs, output_dir=merge_dir)
        logger.info("合并成单文件夹 %s", merge_dir)

    if merge_zip:
        merge_zip_path = comicbook.get_merge_zip_path(output_dir=output_dir, start=start, end=end, ext_name=ext_name)
        ensure_file_dir_exists(filepath=merge_zip_path)
        merge_zip_books(chapter_dirs=chapter_dirs, target_path=merge_zip_path)
        logger.info("合并成单个zip文件 %s", merge_zip_path)


def download_latest_all(page_str, **kwargs):
    comicbook = kwargs.pop('comicbook')
    page_str = page_str or '1'
    for page in parser_chapter_str(page_str):
        for citem in comicbook.latest(page=page):
            next_comicbook = ComicBook(site=comicbook.crawler.SITE, comicid=citem.comicid)
            next_comicbook.start_crawler()
            echo_comicbook_desc(comicbook=next_comicbook, ext_name=kwargs.get('ext_name'))
            download_main(comicbook=next_comicbook, **kwargs)


def download_tag_all(tag, page_str, **kwargs):
    comicbook = kwargs.pop('comicbook')
    page_str = page_str or '1'
    for page in parser_chapter_str(page_str):
        for citem in comicbook.get_tag_result(tag=tag, page=page):
            next_comicbook = ComicBook(site=comicbook.crawler.SITE, comicid=citem.comicid)
            next_comicbook.start_crawler()
            echo_comicbook_desc(comicbook=next_comicbook, ext_name=kwargs.get('ext_name'))
            download_main(comicbook=next_comicbook, **kwargs)


def download_url_list(config, url_file, **kwargs):
    comicbook = kwargs.pop('comicbook')
    with open(url_file) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            url = line
            site = ComicBook.get_site_by_url(url=url)
            comicid = ComicBook.get_comicid_by_url(site=site, url=url)
            if not site or not comicid:
                logger.info('Unknown url. url=%s', url)
                continue
            comicbook = ComicBook(site=site, comicid=comicid)
            init_crawler(site=site, config=config)
            comicbook.start_crawler()
            echo_comicbook_desc(comicbook=comicbook, ext_name=kwargs.get('ext_name'))
            download_main(comicbook=comicbook, **kwargs)


def show_tags(comicbook):
    msg_list = []
    for t1 in comicbook.get_tags():
        category = t1['category']
        t1_msg_list = []
        for t2 in t1['tags']:
            msg = '{name}={tag}'.format(name=t2['name'], tag=t2['tag'])
            t1_msg_list.append(msg)
        msg = '{}:\n{}'.format(category, '\t'.join(t1_msg_list))
        msg_list.append(msg)
    logger.info('支持的标签\n%s', '\n'.join(msg_list))


def echo_comicbook_desc(comicbook, ext_name=None):
    name = "{} {}".format(comicbook.name, ext_name) if ext_name else comicbook.name
    msg = ("{source_name} 【{name}】 更新至: {last_chapter_number:>03} "
           "【{last_chapter_title}】 数据来源: {source_url}").format(
        source_name=comicbook.source_name,
        name=name,
        last_chapter_number=comicbook.get_last_chapter_number(ext_name),
        last_chapter_title=comicbook.get_last_chapter_title(ext_name),
        source_url=comicbook.source_url)
    logger.info(msg)


def init_crawler(site, config):
    proxy = config.get_proxy(site=site)
    if proxy:
        logger.info('set proxy. %s', proxy)
        SessionMgr.set_proxy(site=site, proxy=proxy)
    if config.verify:
        logger.info('set verify. verify=True')
        SessionMgr.set_verify(site=site, verify=True)

    # 加载cookies
    cookies_path = config.get_cookies_path(site)
    if cookies_path and os.path.exists(cookies_path):
        SessionMgr.load_cookies(site=site, path=cookies_path)
        logger.info('load cookies success. %s', cookies_path)


def save_cookies(site, config):
    cookies_path = config.get_cookies_path(site)
    if cookies_path:
        ensure_file_dir_exists(filepath=cookies_path)
        SessionMgr.export_cookies(site=site, path=cookies_path)
        logger.info("cookies saved. path={}".format(cookies_path))


def migrate(comicbook_dir):
    for crawler_cls in ComicBook.CRAWLER_CLS_MAP.values():
        if crawler_cls.SINGLE_CHAPTER:
            dir1 = os.path.join(comicbook_dir, crawler_cls.SOURCE_NAME)
            for name1 in os.listdir(dir1):
                dir2 = os.path.join(dir1, name1)
                if not os.path.isdir(dir2):
                    continue
                for name2 in os.listdir(dir2):
                    dir3 = os.path.join(dir2, name2)
                    if not os.path.isdir(dir3):
                        continue
                    new_name = name2.split(' ')[0]
                    target = os.path.join(dir2, new_name)
                    os.rename(dir3, target)


def main():
    args = parse_args()
    init_logger(debug=args.debug)
    config = CrawlerConfig(args=args)
    if args.migrate:
        migrate(config.output)
        exit(0)

    if args.url:
        site = ComicBook.get_site_by_url(args.url)
        if not site:
            raise RuntimeError('Unknown url. url=%s' % args.url)
        comicid = ComicBook.get_comicid_by_url(site=site, url=args.url)
    else:
        site = args.site or 'qq'
        comicid = args.comicid

    WorkerPoolMgr.set_worker(worker=config.worker)
    CrawlerBase.DRIVER_PATH = config.driver_path
    logger.debug('set DRIVER_PATH. DRIVER_PATH=%s', config.driver_path)
    CrawlerBase.DRIVER_TYPE = config.driver_type
    logger.debug('set DRIVER_TYPE. DRIVER_TYPE=%s', config.driver_type)
    CrawlerBase.NODE_MODULES = config.node_modules
    logger.debug('set NODE_MODULES. NODE_MODULES=%s', config.node_modules)

    comicbook = ComicBook(site=site, comicid=comicid)
    comicbook.set_crawler_timeout(config.crawler_timeout)
    comicbook.set_image_timeout(config.image_timeout)

    if args.login:
        comicbook.crawler.login()
        save_cookies(site=site, config=config)
    if args.show_tags:
        init_crawler(site=site, config=config)
        show_tags(comicbook=comicbook)
        exit(0)

    if args.name:
        init_crawler(site=site, config=config)
        result = comicbook.search(name=args.name, limit=10)
        msg_list = []
        for item in result:
            msg_list.append("comicid={}\t{}\tsource_url={}".format(
                item.comicid, item.name, item.source_url)
            )
        logger.info('\n%s', '\n'.join(msg_list))
        exit(0)

    if args.mail:
        is_send_mail = True
        mail = Mail.init(config.get_config_file())
    else:
        is_send_mail = False
        mail = None

    download_main_kwargs = dict(
        comicbook=comicbook,
        output_dir=config.output,
        chapters=args.chapter,
        is_download_all=args.all,
        is_gen_pdf=args.pdf,
        is_gen_zip=args.zip,
        is_single_image=args.single_image,
        quality=config.quality,
        max_height=config.max_height,
        mail=mail,
        ext_name=args.ext_name,
        is_send_mail=is_send_mail,
        receivers=args.receivers,
        merge=args.merge,
        merge_zip=args.merge_zip,
        crawler_delay=config.crawler_delay
    )

    if args.url_file:
        download_url_list(config=config, url_file=args.url_file, **download_main_kwargs)
    elif args.latest_all:
        init_crawler(site=site, config=config)
        download_latest_all(page_str=args.latest_page, **download_main_kwargs)
    elif args.tag_all:
        init_crawler(site=site, config=config)
        download_tag_all(tag=args.tag, page_str=args.tag_page, **download_main_kwargs)
    else:
        init_crawler(site=site, config=config)
        comicbook.start_crawler()
        echo_comicbook_desc(comicbook=comicbook, ext_name=args.ext_name)
        download_main(**download_main_kwargs)


if __name__ == '__main__':
    main()
