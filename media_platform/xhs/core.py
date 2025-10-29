# 声明：本代码仅供学习和研究目的使用。使用者应遵守以下原则：
# 1. 不得用于任何商业用途。
# 2. 使用时应遵守目标平台的使用条款和robots.txt规则。
# 3. 不得进行大规模爬取或对平台造成运营干扰。
# 4. 应合理控制请求频率，避免给目标平台带来不必要的负担。
# 5. 不得用于任何非法或不当的用途。
#
# 详细许可条款请参阅项目根目录下的LICENSE文件。
# 使用本代码即表示您同意遵守上述原则和LICENSE中的所有条款。

import asyncio
import os
import random
from asyncio import Task
from typing import Dict, List, Optional

from playwright.async_api import (
    BrowserContext,
    BrowserType,
    Page,
    Playwright,
    async_playwright,
)
from tenacity import RetryError

import config
from base.base_crawler import AbstractCrawler
from config import CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES
from model.m_xiaohongshu import NoteUrlInfo, CreatorUrlInfo
from proxy.proxy_ip_pool import IpInfoModel, create_ip_pool
from store import xhs as xhs_store
from tools import utils
from tools.cdp_browser import CDPBrowserManager
from var import crawler_type_var, source_keyword_var

from .client import XiaoHongShuClient
from .exception import DataFetchError
from .field import SearchSortType
from .help import parse_note_info_from_note_url, parse_creator_info_from_url, get_search_id
from .login import XiaoHongShuLogin
from tools.cookie_pool import CookiePoolManager, create_cookie_pool_manager
from tools.cookie_guard import CookieBlockedException

class XiaoHongShuCrawler(AbstractCrawler):
    context_page: Page
    xhs_client: XiaoHongShuClient
    browser_context: BrowserContext
    cdp_manager: Optional[CDPBrowserManager]
    cookie_pool_manager: Optional[CookiePoolManager]

    def __init__(self) -> None:
        self.index_url = "https://www.xiaohongshu.com"
        # self.user_agent = utils.get_user_agent()
        self.user_agent = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        self.cdp_manager = None
        # 存储每个笔记的评论区截图路径
        self.note_screenshots: Dict[str, str] = {}
        # 存储每个笔记的完整详情（用于截图后更新）
        self.note_details_cache: Dict[str, Dict] = {}
        # 断点续爬：进度管理器
        self.progress_manager = None
        # Cookie池管理器
        self.cookie_pool_manager = None
        # IP代理池
        self.ip_proxy_pool = None
        # 轮换计数器
        self.notes_count_for_rotation = 0  # 用于Cookie和IP定期轮换

    async def start(self) -> None:
        playwright_proxy_format, httpx_proxy_format = None, None
        if config.ENABLE_IP_PROXY:
            self.ip_proxy_pool = await create_ip_pool(config.IP_PROXY_POOL_COUNT, enable_validate_ip=True)
            ip_proxy_info: IpInfoModel = await self.ip_proxy_pool.get_proxy()
            playwright_proxy_format, httpx_proxy_format = utils.format_proxy_info(ip_proxy_info)
            utils.logger.info(f"[XiaoHongShuCrawler] Using proxy: {ip_proxy_info.ip}:{ip_proxy_info.port}")

        async with async_playwright() as playwright:
            # 根据配置选择启动模式
            if config.ENABLE_CDP_MODE:
                utils.logger.info("[XiaoHongShuCrawler] 使用CDP模式启动浏览器")
                self.browser_context = await self.launch_browser_with_cdp(
                    playwright,
                    playwright_proxy_format,
                    self.user_agent,
                    headless=config.CDP_HEADLESS,
                )
            else:
                utils.logger.info("[XiaoHongShuCrawler] 使用标准模式启动浏览器")
                # Launch a browser context.
                chromium = playwright.chromium
                self.browser_context = await self.launch_browser(
                    chromium,
                    playwright_proxy_format,
                    self.user_agent,
                    headless=config.HEADLESS,
                )
            # stealth.min.js is a js script to prevent the website from detecting the crawler.
            await self.browser_context.add_init_script(path="libs/stealth.min.js")
            self.context_page = await self.browser_context.new_page()
            # 使用domcontentloaded代替networkidle，避免等待所有资源加载完成
            # 增加超时时间到60秒
            await self.context_page.goto(self.index_url, wait_until="domcontentloaded", timeout=60000)

            # Create a client to interact with the xiaohongshu website.
            self.xhs_client = await self.create_xhs_client(httpx_proxy_format)
            
            # 初始化Cookie池管理器（如果启用）
            if config.ENABLE_COOKIE_POOL and config.ENABLE_COOKIE_AUTO_SWITCH:
                utils.logger.info("[XiaoHongShuCrawler] Initializing Cookie Pool Manager...")
                self.cookie_pool_manager = await create_cookie_pool_manager(
                    platform="xhs",
                    client=self.xhs_client,
                    browser_context=self.browser_context,
                    enable_auto_switch=True
                )
                # 如果Cookie池中有Cookie，应用第一个
                current_cookie = self.cookie_pool_manager.cookie_pool.get_current_cookie()
                if current_cookie:
                    utils.logger.info(f"[XiaoHongShuCrawler] Applying cookie from pool: {current_cookie.account_id}")
                    await self.cookie_pool_manager._apply_cookie(current_cookie)
            
            if not await self.xhs_client.pong():
                login_obj = XiaoHongShuLogin(
                    login_type=config.LOGIN_TYPE,
                    login_phone="",  # input your phone number
                    browser_context=self.browser_context,
                    context_page=self.context_page,
                    cookie_str=config.COOKIES,
                )
                await login_obj.begin()
                await self.xhs_client.update_cookies(browser_context=self.browser_context)

            crawler_type_var.set(config.CRAWLER_TYPE)
            if config.CRAWLER_TYPE == "search":
                # Search for notes and retrieve their comment information.
                await self.search()
            elif config.CRAWLER_TYPE == "detail":
                # Get the information and comments of the specified post
                await self.get_specified_notes()
            elif config.CRAWLER_TYPE == "creator":
                # Get creator's information and their notes and comments
                await self.get_creators_and_notes()
            else:
                pass

            utils.logger.info("[XiaoHongShuCrawler.start] Xhs Crawler finished ...")

    async def search(self) -> None:
        """Search for notes and retrieve their comment information."""
        utils.logger.info("[XiaoHongShuCrawler.search] Begin search xiaohongshu keywords")
        
        # 初始化断点续爬功能
        if config.ENABLE_RESUME_CRAWL and config.SAVE_DATA_OPTION == "csv":
            from tools.crawl_progress import CrawlProgressManager
            self.progress_manager = CrawlProgressManager(platform="xhs", crawler_type=config.CRAWLER_TYPE)
            self.progress_manager.load_crawled_ids()
            
            # 自动清理不完整的评论（如果开启）
            if config.ENABLE_AUTO_CLEAN_INCOMPLETE_COMMENTS and config.ENABLE_GET_COMMENTS:
                deleted_count = self.progress_manager.clean_incomplete_comments(
                    min_comment_count=config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES
                )
                if deleted_count > 0:
                    utils.logger.info(f"[XiaoHongShuCrawler.search] 🧹 Auto-cleaned {deleted_count} incomplete comment rows")
            
            # 传入最小评论数量，只有达到这个数量的笔记才被认为已完成
            self.progress_manager.load_crawled_comment_note_ids(min_comment_count=config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES)
            utils.logger.info(f"[XiaoHongShuCrawler.search] Resume crawl enabled:")
            utils.logger.info(f"  - Already crawled {self.progress_manager.get_crawled_count()} notes")
            utils.logger.info(f"  - Already crawled comments for {self.progress_manager.get_crawled_comment_count()} notes")
            
            # 在开始搜索前，检查并处理不完整的笔记
            if config.ENABLE_GET_COMMENTS_SCREENSHOT:
                utils.logger.info(f"[XiaoHongShuCrawler.search] 🔍 Checking existing notes for incomplete data...")
                incomplete_notes = await self._check_and_get_incomplete_screenshots()
                
                if incomplete_notes:
                    utils.logger.info(f"[XiaoHongShuCrawler.search] ⚠️  Found {len(incomplete_notes)} notes with incomplete comments or screenshots")
                    utils.logger.info(f"[XiaoHongShuCrawler.search] 🗑️  Deleting incomplete data to re-crawl...")
                    
                    # 删除不完整笔记的所有数据
                    deleted_count = 0
                    for note_info in incomplete_notes:
                        note_id = note_info['note_id']
                        comment_count = note_info['comment_count']
                        layer_count = note_info['layer_count']
                        
                        utils.logger.info(f"[XiaoHongShuCrawler.search] 🗑️  Deleting note {note_id} (comments: {comment_count}/20, layers: {layer_count})")
                        
                        if self.progress_manager.delete_incomplete_note_data(note_id):
                            deleted_count += 1
                            # 从已爬取列表中移除
                            self.progress_manager.crawled_ids.discard(note_id)
                            self.progress_manager.crawled_comment_note_ids.discard(note_id)
                    
                    utils.logger.info(f"[XiaoHongShuCrawler.search] ✅ Deleted {deleted_count} incomplete notes, they will be re-crawled")
                else:
                    utils.logger.info(f"[XiaoHongShuCrawler.search] ✅ All existing notes have complete data, starting to search new notes")
        
        xhs_limit_count = 20  # xhs limit page fixed value
        start_page = config.START_PAGE
        for keyword in config.KEYWORDS.split(","):
            source_keyword_var.set(keyword)
            utils.logger.info(f"[XiaoHongShuCrawler.search] Current search keyword: {keyword}")
            page = 1
            search_id = get_search_id()
            crawled_notes_count = 0  # 已爬取的帖子数量
            while crawled_notes_count < config.CRAWLER_MAX_NOTES_COUNT:
                if page < start_page:
                    utils.logger.info(f"[XiaoHongShuCrawler.search] Skip page {page}")
                    page += 1
                    continue

                try:
                    utils.logger.info(f"[XiaoHongShuCrawler.search] search xhs keyword: {keyword}, page: {page}")
                    note_ids: List[str] = []
                    xsec_tokens: List[str] = []
                    
                    # 尝试获取笔记，如果失败则尝试切换cookie
                    max_retry = 3
                    retry_count = 0
                    notes_res = None
                    
                    while retry_count < max_retry:
                        try:
                            notes_res = await self.xhs_client.get_note_by_keyword(
                                keyword=keyword,
                                search_id=search_id,
                                page=page,
                                sort=(SearchSortType(config.SORT_TYPE) if config.SORT_TYPE != "" else SearchSortType.GENERAL),
                            )
                            break  # 成功则退出循环
                        except (IPBlockError, DataFetchError, CaptchaError, CookieBlockedException) as e:
                            utils.logger.error(f"[XiaoHongShuCrawler.search] Error fetching notes: {e}")
                            retry_count += 1
                            
                            # 如果是Cookie过期/被封，切换Cookie
                            if isinstance(e, CookieBlockedException):
                                utils.logger.warning(f"[XiaoHongShuCrawler.search] 🔐 Cookie expired/blocked! Switching to next cookie...")
                                
                                # 切换Cookie
                                if self.cookie_pool_manager and retry_count < max_retry:
                                    switched = await self.cookie_pool_manager.handle_cookie_blocked()
                                    if switched:
                                        utils.logger.info("[XiaoHongShuCrawler.search] ✅ Cookie switched successfully")
                                        await asyncio.sleep(2)  # 等待一下再重试
                                    else:
                                        utils.logger.error("[XiaoHongShuCrawler.search] ❌ Failed to switch cookie, no more available cookies")
                                        raise
                                else:
                                    utils.logger.error("[XiaoHongShuCrawler.search] ❌ Cookie pool not available")
                                    raise
                            
                            # 如果是验证码错误，切换Cookie和IP
                            elif isinstance(e, CaptchaError):
                                utils.logger.warning(f"[XiaoHongShuCrawler.search] 🚨 Captcha detected! Switching Cookie and IP...")
                                
                                # 切换Cookie
                                if self.cookie_pool_manager and retry_count < max_retry:
                                    switched = await self.cookie_pool_manager.handle_cookie_blocked()
                                    if switched:
                                        utils.logger.info("[XiaoHongShuCrawler.search] ✅ Cookie switched")
                                
                                # 切换IP
                                if self.ip_proxy_pool and config.ENABLE_IP_PROXY:
                                    try:
                                        new_ip_info = await self.ip_proxy_pool.get_proxy()
                                        _, httpx_proxy = utils.format_proxy_info(new_ip_info)
                                        await self.xhs_client.update_proxy(httpx_proxy)
                                        utils.logger.info(f"[XiaoHongShuCrawler.search] ✅ IP switched to: {new_ip_info.ip}:{new_ip_info.port}")
                                    except Exception as ip_error:
                                        utils.logger.error(f"[XiaoHongShuCrawler.search] Failed to switch IP: {ip_error}")
                                
                                await asyncio.sleep(3)
                            # 其他错误，只切换Cookie
                            elif self.cookie_pool_manager and retry_count < max_retry:
                                utils.logger.warning(f"[XiaoHongShuCrawler.search] Attempting to switch cookie (retry {retry_count}/{max_retry})...")
                                switched = await self.cookie_pool_manager.handle_cookie_blocked()
                                if switched:
                                    utils.logger.info("[XiaoHongShuCrawler.search] Cookie switched successfully, retrying...")
                                    await asyncio.sleep(2)  # 等待一下再重试
                                else:
                                    utils.logger.error("[XiaoHongShuCrawler.search] Failed to switch cookie, no more available cookies")
                                    raise
                            else:
                                raise
                    
                    if not notes_res:
                        utils.logger.error("[XiaoHongShuCrawler.search] Failed to fetch notes after retries")
                        break
                    # utils.logger.info(f"[XiaoHongShuCrawler.search] Search notes res:{notes_res}")  # 已注释：不显示搜索结果列表
                    if not notes_res or not notes_res.get("has_more", False):
                        utils.logger.info("No more content!")
                        break
                    
                    # 过滤出真实的帖子（排除推荐和热搜）
                    valid_items = [
                        post_item for post_item in notes_res.get("items", {})
                        if post_item.get("model_type") not in ("rec_query", "hot_query")
                    ]
                    
                    # 过滤掉已爬取的笔记（断点续爬）
                    if self.progress_manager:
                        items_before_filter = len(valid_items)
                        valid_items = [
                            item for item in valid_items 
                            if not self.progress_manager.is_crawled(item.get("id"))
                        ]
                        skipped_count = items_before_filter - len(valid_items)
                        if skipped_count > 0:
                            utils.logger.info(f"[XiaoHongShuCrawler.search] Skipped {skipped_count} already crawled notes")
                    
                    # 只爬取用户指定数量的帖子
                    remaining_count = config.CRAWLER_MAX_NOTES_COUNT - crawled_notes_count
                    items_to_crawl = valid_items[:remaining_count]
                    
                    # 显示本批次进度信息
                    batch_start_index = crawled_notes_count + 1
                    batch_end_index = crawled_notes_count + len(items_to_crawl)
                    progress_percent = (crawled_notes_count / config.CRAWLER_MAX_NOTES_COUNT) * 100
                    utils.logger.info(f"[XiaoHongShuCrawler.search] 📊 Progress: {crawled_notes_count}/{config.CRAWLER_MAX_NOTES_COUNT} ({progress_percent:.1f}%) | Crawling notes #{batch_start_index}-#{batch_end_index}")
                    
                    semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)
                    task_list = []
                    for idx, post_item in enumerate(items_to_crawl, start=batch_start_index):
                        task_list.append(
                            self.get_note_detail_async_task(
                                note_id=post_item.get("id"),
                                xsec_source=post_item.get("xsec_source"),
                                xsec_token=post_item.get("xsec_token"),
                                semaphore=semaphore,
                            )
                        )
                    
                    note_details = await asyncio.gather(*task_list)
                    successful_count = len([d for d in note_details if d])
                    crawled_notes_count += successful_count
                    
                    # 标记已爬取的笔记（断点续爬）
                    if self.progress_manager:
                        for note_detail in note_details:
                            if note_detail:
                                self.progress_manager.mark_as_crawled(note_detail.get("note_id"))
                    
                    # 保存笔记详情并显示每个笔记的进度
                    for idx, note_detail in enumerate(note_details, start=batch_start_index):
                        if note_detail:
                            note_id = note_detail.get("note_id")
                            title = note_detail.get("title", "No title")[:30]
                            
                            # 显示当前正在处理的笔记
                            current_progress = (idx / config.CRAWLER_MAX_NOTES_COUNT) * 100
                            utils.logger.info(f"[XiaoHongShuCrawler.search] ✓ Note #{idx}/{config.CRAWLER_MAX_NOTES_COUNT} ({current_progress:.1f}%) - {title}")
                            
                            # 缓存note_detail，用于截图后更新
                            self.note_details_cache[note_id] = note_detail
                            
                            # 如果有对应的截图，则传递截图路径
                            screenshot_path = self.note_screenshots.get(note_id, "")
                            await xhs_store.update_xhs_note(note_detail, screenshot_path)
                            await self.get_notice_media(note_detail)
                            note_ids.append(note_id)
                            xsec_tokens.append(note_detail.get("xsec_token"))
                    
                    page += 1
                    # 显示本批次完成情况
                    utils.logger.info(f"[XiaoHongShuCrawler.search] ✅ Batch completed: {successful_count}/{len(items_to_crawl)} notes saved successfully")
                    
                    # 过滤掉已爬取评论的笔记（评论续爬）
                    if self.progress_manager and config.ENABLE_GET_COMMENTS:
                        notes_to_crawl_comments = []
                        tokens_to_crawl_comments = []
                        notes_to_screenshot_only = []  # 只需要截图的笔记
                        tokens_to_screenshot_only = []
                        skipped_comment_count = 0
                        
                        for note_id, xsec_token in zip(note_ids, xsec_tokens):
                            if not self.progress_manager.is_comment_crawled(note_id):
                                # 检查评论是否完整（只缺截图）
                                if config.ENABLE_GET_COMMENTS_SCREENSHOT:
                                    comment_complete = self._check_comment_complete(note_id)
                                    if comment_complete:
                                        # 评论完整但缺截图，只需要截图
                                        notes_to_screenshot_only.append(note_id)
                                        tokens_to_screenshot_only.append(xsec_token)
                                        continue
                                
                                # 需要爬取评论
                                notes_to_crawl_comments.append(note_id)
                                tokens_to_crawl_comments.append(xsec_token)
                            else:
                                skipped_comment_count += 1
                        
                        if skipped_comment_count > 0:
                            utils.logger.info(f"[XiaoHongShuCrawler.search] 💬 Skipped {skipped_comment_count} notes with already crawled comments")
                        
                        # 处理只需要截图的笔记
                        if notes_to_screenshot_only:
                            utils.logger.info(f"[XiaoHongShuCrawler.search] 📸 Found {len(notes_to_screenshot_only)} notes with complete comments but missing screenshots")
                            await self.batch_screenshot_comments(notes_to_screenshot_only, tokens_to_screenshot_only)
                        
                        # 处理需要爬取评论的笔记
                        if notes_to_crawl_comments:
                            utils.logger.info(f"[XiaoHongShuCrawler.search] 💬 Crawling comments for {len(notes_to_crawl_comments)} notes")
                            await self.batch_get_note_comments(notes_to_crawl_comments, tokens_to_crawl_comments)
                            
                            # 标记已爬取评论
                            for note_id in notes_to_crawl_comments:
                                self.progress_manager.mark_comment_as_crawled(note_id)
                    else:
                        # 不启用续爬或不爬取评论，正常爬取
                        await self.batch_get_note_comments(note_ids, xsec_tokens)
                    
                    # 截图完成后，更新包含截图路径的笔记信息
                    # 注意：无论截图是否成功，都需要更新一次以确保CSV中的screenshot字段被正确设置
                    screenshot_count = 0
                    for note_detail in note_details:
                        if note_detail:
                            note_id = note_detail.get("note_id")
                            screenshot_path = self.note_screenshots.get(note_id, "")
                            if screenshot_path:
                                screenshot_count += 1
                            await xhs_store.update_xhs_note(note_detail, screenshot_path)
                    
                    if screenshot_count > 0:
                        utils.logger.info(f"[XiaoHongShuCrawler.search] 📸 Screenshots: {screenshot_count}/{len(note_details)} notes have screenshots")
                    
                    # 检查是否已经爬取够数量
                    if crawled_notes_count >= config.CRAWLER_MAX_NOTES_COUNT:
                        utils.logger.info(f"[XiaoHongShuCrawler.search] Reached target count: {crawled_notes_count}/{config.CRAWLER_MAX_NOTES_COUNT}")
                        break
                    
                    # Sleep after each page navigation
                    await asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC)
                    utils.logger.info(f"[XiaoHongShuCrawler.search] Sleeping for {config.CRAWLER_MAX_SLEEP_SEC} seconds after page {page-1}")
                except DataFetchError:
                    utils.logger.error("[XiaoHongShuCrawler.search] Get note detail error")
                    break

    async def get_creators_and_notes(self) -> None:
        """Get creator's notes and retrieve their comment information."""
        utils.logger.info("[XiaoHongShuCrawler.get_creators_and_notes] Begin get xiaohongshu creators")
        for creator_url in config.XHS_CREATOR_ID_LIST:
            try:
                # Parse creator URL to get user_id and security tokens
                creator_info: CreatorUrlInfo = parse_creator_info_from_url(creator_url)
                utils.logger.info(f"[XiaoHongShuCrawler.get_creators_and_notes] Parse creator URL info: {creator_info}")
                user_id = creator_info.user_id

                # get creator detail info from web html content
                createor_info: Dict = await self.xhs_client.get_creator_info(
                    user_id=user_id,
                    xsec_token=creator_info.xsec_token,
                    xsec_source=creator_info.xsec_source
                )
                if createor_info:
                    await xhs_store.save_creator(user_id, creator=createor_info)
            except ValueError as e:
                utils.logger.error(f"[XiaoHongShuCrawler.get_creators_and_notes] Failed to parse creator URL: {e}")
                continue

            # Use fixed crawling interval
            crawl_interval = config.CRAWLER_MAX_SLEEP_SEC
            # Get all note information of the creator
            all_notes_list = await self.xhs_client.get_all_notes_by_creator(
                user_id=user_id,
                crawl_interval=crawl_interval,
                callback=self.fetch_creator_notes_detail,
            )

            note_ids = []
            xsec_tokens = []
            for note_item in all_notes_list:
                note_ids.append(note_item.get("note_id"))
                xsec_tokens.append(note_item.get("xsec_token"))
            await self.batch_get_note_comments(note_ids, xsec_tokens)
            
            # 截图完成后，更新包含截图路径的笔记信息
            for note_item in all_notes_list:
                note_id = note_item.get("note_id")
                screenshot_path = self.note_screenshots.get(note_id, "")
                # 从缓存中获取完整的note_detail
                note_detail = self.note_details_cache.get(note_id)
                if note_detail and screenshot_path:
                    utils.logger.info(f"[XiaoHongShuCrawler.get_creator_notes_detail] Updating note {note_id} with screenshot path: {screenshot_path}")
                    await xhs_store.update_xhs_note(note_detail, screenshot_path)
                elif not note_detail:
                    utils.logger.warning(f"[XiaoHongShuCrawler.get_creator_notes_detail] Note {note_id} not found in cache, skipping screenshot update")

    async def fetch_creator_notes_detail(self, note_list: List[Dict]):
        """
        Concurrently obtain the specified post list and save the data
        """
        semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)
        task_list = [
            self.get_note_detail_async_task(
                note_id=post_item.get("note_id"),
                xsec_source=post_item.get("xsec_source"),
                xsec_token=post_item.get("xsec_token"),
                semaphore=semaphore,
            ) for post_item in note_list
        ]

        note_details = await asyncio.gather(*task_list)
        for note_detail in note_details:
            if note_detail:
                note_id = note_detail.get("note_id")
                # 缓存note_detail，用于截图后更新
                self.note_details_cache[note_id] = note_detail
                screenshot_path = self.note_screenshots.get(note_id, "")
                await xhs_store.update_xhs_note(note_detail, screenshot_path)
                await self.get_notice_media(note_detail)

    async def get_specified_notes(self):
        """
        Get the information and comments of the specified post
        must be specified note_id, xsec_source, xsec_token⚠️⚠️⚠️
        Returns:

        """
        get_note_detail_task_list = []
        for full_note_url in config.XHS_SPECIFIED_NOTE_URL_LIST:
            note_url_info: NoteUrlInfo = parse_note_info_from_note_url(full_note_url)
            utils.logger.info(f"[XiaoHongShuCrawler.get_specified_notes] Parse note url info: {note_url_info}")
            crawler_task = self.get_note_detail_async_task(
                note_id=note_url_info.note_id,
                xsec_source=note_url_info.xsec_source,
                xsec_token=note_url_info.xsec_token,
                semaphore=asyncio.Semaphore(config.MAX_CONCURRENCY_NUM),
            )
            get_note_detail_task_list.append(crawler_task)

        need_get_comment_note_ids = []
        xsec_tokens = []
        note_details = await asyncio.gather(*get_note_detail_task_list)
        for note_detail in note_details:
            if note_detail:
                note_id = note_detail.get("note_id", "")
                need_get_comment_note_ids.append(note_id)
                xsec_tokens.append(note_detail.get("xsec_token", ""))
                screenshot_path = self.note_screenshots.get(note_id, "")
                await xhs_store.update_xhs_note(note_detail, screenshot_path)
                await self.get_notice_media(note_detail)
        await self.batch_get_note_comments(need_get_comment_note_ids, xsec_tokens)
        
        # 截图完成后，更新包含截图路径的笔记信息
        for note_detail in note_details:
            if note_detail:
                note_id = note_detail.get("note_id", "")
                screenshot_path = self.note_screenshots.get(note_id, "")
                if screenshot_path:
                    utils.logger.info(f"[XiaoHongShuCrawler.get_specified_notes] Updating note {note_id} with screenshot path: {screenshot_path}")
                else:
                    utils.logger.info(f"[XiaoHongShuCrawler.get_specified_notes] Updating note {note_id} without screenshot (screenshot was not generated)")
                await xhs_store.update_xhs_note(note_detail, screenshot_path)

    async def get_note_detail_async_task(
        self,
        note_id: str,
        xsec_source: str,
        xsec_token: str,
        semaphore: asyncio.Semaphore,
    ) -> Optional[Dict]:
        """Get note detail

        Args:
            note_id:
            xsec_source:
            xsec_token:
            semaphore:

        Returns:
            Dict: note detail
        """
        note_detail = None
        async with semaphore:
            max_retry = 3
            retry_count = 0
            
            while retry_count < max_retry:
                try:
                    utils.logger.info(f"[get_note_detail_async_task] Begin get note detail, note_id: {note_id}")

                    note_detail = await self.xhs_client.get_note_by_id_from_html(note_id, xsec_source, xsec_token, enable_cookie=True)
                    if not note_detail:
                        raise Exception(f"[get_note_detail_async_task] Failed to get note detail, Id: {note_id}")
                    note_detail.update({"xsec_token": xsec_token, "xsec_source": xsec_source})
                    
                    # Cookie和IP定期轮换检查
                    await self._check_and_rotate_resources()
                    
                    # Sleep after fetching note detail (添加随机延迟，更像人类行为)
                    import random
                    random_delay = random.uniform(0.8, 1.2)  # 随机80%-120%
                    actual_sleep = config.CRAWLER_MAX_SLEEP_SEC * random_delay
                    await asyncio.sleep(actual_sleep)
                    utils.logger.info(f"[get_note_detail_async_task] Sleeping for {actual_sleep:.1f} seconds after fetching note {note_id}")
                    
                    return note_detail

                except (DataFetchError, IPBlockError, CaptchaError, CookieBlockedException) as ex:
                    utils.logger.error(f"[XiaoHongShuCrawler.get_note_detail_async_task] Get note detail error: {ex}")
                    retry_count += 1
                    
                    # 如果是Cookie过期/被封，切换Cookie
                    if isinstance(ex, CookieBlockedException):
                        utils.logger.warning(f"[get_note_detail_async_task] 🔐 Cookie expired/blocked! Switching to next cookie...")
                        
                        if self.cookie_pool_manager and retry_count < max_retry:
                            switched = await self.cookie_pool_manager.handle_cookie_blocked()
                            if switched:
                                utils.logger.info("[get_note_detail_async_task] ✅ Cookie switched successfully")
                                await asyncio.sleep(2)
                            else:
                                utils.logger.error("[get_note_detail_async_task] ❌ Failed to switch cookie")
                                return None
                        else:
                            return None
                    
                    # 如果是验证码错误，切换Cookie和IP
                    elif isinstance(ex, CaptchaError):
                        utils.logger.warning(f"[get_note_detail_async_task] 🚨 Captcha detected! Switching Cookie and IP...")
                        
                        # 切换Cookie
                        if self.cookie_pool_manager and retry_count < max_retry:
                            await self.cookie_pool_manager.handle_cookie_blocked()
                        
                        # 切换IP
                        if self.ip_proxy_pool and config.ENABLE_IP_PROXY:
                            try:
                                new_ip_info = await self.ip_proxy_pool.get_proxy()
                                _, httpx_proxy = utils.format_proxy_info(new_ip_info)
                                await self.xhs_client.update_proxy(httpx_proxy)
                                utils.logger.info(f"[get_note_detail_async_task] ✅ IP switched to: {new_ip_info.ip}:{new_ip_info.port}")
                            except Exception as ip_error:
                                utils.logger.error(f"[get_note_detail_async_task] Failed to switch IP: {ip_error}")
                        
                        await asyncio.sleep(3)
                    # 其他错误，只切换Cookie
                    elif self.cookie_pool_manager and retry_count < max_retry:
                        utils.logger.warning(f"[get_note_detail_async_task] Attempting to switch cookie (retry {retry_count}/{max_retry})...")
                        switched = await self.cookie_pool_manager.handle_cookie_blocked()
                        if switched:
                            utils.logger.info("[get_note_detail_async_task] Cookie switched successfully, retrying...")
                            await asyncio.sleep(2)
                        else:
                            utils.logger.error("[get_note_detail_async_task] Failed to switch cookie")
                            return None
                    else:
                        return None
                        
                except KeyError as ex:
                    utils.logger.error(f"[XiaoHongShuCrawler.get_note_detail_async_task] have not fund note detail note_id:{note_id}, err: {ex}")
                    return None
                except Exception as ex:
                    utils.logger.error(f"[XiaoHongShuCrawler.get_note_detail_async_task] Unexpected error: {ex}")
                    return None
            
            return None

    async def batch_get_note_comments(self, note_list: List[str], xsec_tokens: List[str]):
        """Batch get note comments"""
        if not config.ENABLE_GET_COMMENTS:
            utils.logger.info(f"[XiaoHongShuCrawler.batch_get_note_comments] Crawling comment mode is not enabled")
            return

        utils.logger.info(f"[XiaoHongShuCrawler.batch_get_note_comments] Begin batch get note comments, note list: {note_list}")
        semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)
        task_list: List[Task] = []
        for index, note_id in enumerate(note_list):
            task = asyncio.create_task(
                self.get_comments(note_id=note_id, xsec_token=xsec_tokens[index], semaphore=semaphore),
                name=note_id,
            )
            task_list.append(task)
        await asyncio.gather(*task_list)

    async def get_comments(self, note_id: str, xsec_token: str, semaphore: asyncio.Semaphore):
        """Get note comments with keyword filtering and quantity limitation"""
        async with semaphore:
            utils.logger.info(f"[XiaoHongShuCrawler.get_comments] Begin get note id comments {note_id}")
            # Use fixed crawling interval
            crawl_interval = config.CRAWLER_MAX_SLEEP_SEC
            
            # 尝试获取评论，如果失败则尝试切换cookie
            max_retry = 3
            retry_count = 0
            success = False
            
            while retry_count < max_retry and not success:
                try:
                    await self.xhs_client.get_note_all_comments(
                        note_id=note_id,
                        xsec_token=xsec_token,
                        crawl_interval=crawl_interval,
                        callback=xhs_store.batch_update_xhs_note_comments,
                        max_count=CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES,
                    )
                    success = True
                except (DataFetchError, IPBlockError, CaptchaError, CookieBlockedException) as e:
                    utils.logger.error(f"[XiaoHongShuCrawler.get_comments] Error fetching comments: {e}")
                    retry_count += 1
                    
                    # 如果是Cookie过期/被封，切换Cookie
                    if isinstance(e, CookieBlockedException):
                        utils.logger.warning(f"[XiaoHongShuCrawler.get_comments] 🔐 Cookie expired/blocked! Switching to next cookie...")
                        
                        if self.cookie_pool_manager and retry_count < max_retry:
                            switched = await self.cookie_pool_manager.handle_cookie_blocked()
                            if switched:
                                utils.logger.info("[XiaoHongShuCrawler.get_comments] ✅ Cookie switched successfully")
                                await asyncio.sleep(2)
                            else:
                                utils.logger.error("[XiaoHongShuCrawler.get_comments] ❌ Failed to switch cookie")
                                break
                        else:
                            break
                    
                    # 如果是验证码错误，切换Cookie和IP
                    elif isinstance(e, CaptchaError):
                        utils.logger.warning(f"[XiaoHongShuCrawler.get_comments] 🚨 Captcha detected! Switching Cookie and IP...")
                        
                        # 切换Cookie
                        if self.cookie_pool_manager and retry_count < max_retry:
                            await self.cookie_pool_manager.handle_cookie_blocked()
                        
                        # 切换IP
                        if self.ip_proxy_pool and config.ENABLE_IP_PROXY:
                            try:
                                new_ip_info = await self.ip_proxy_pool.get_proxy()
                                _, httpx_proxy = utils.format_proxy_info(new_ip_info)
                                await self.xhs_client.update_proxy(httpx_proxy)
                                utils.logger.info(f"[XiaoHongShuCrawler.get_comments] ✅ IP switched to: {new_ip_info.ip}:{new_ip_info.port}")
                            except Exception as ip_error:
                                utils.logger.error(f"[XiaoHongShuCrawler.get_comments] Failed to switch IP: {ip_error}")
                        
                        await asyncio.sleep(3)
                    # 其他错误，只切换Cookie
                    elif self.cookie_pool_manager and retry_count < max_retry:
                        utils.logger.warning(f"[XiaoHongShuCrawler.get_comments] Attempting to switch cookie (retry {retry_count}/{max_retry})...")
                        switched = await self.cookie_pool_manager.handle_cookie_blocked()
                        if switched:
                            utils.logger.info("[XiaoHongShuCrawler.get_comments] Cookie switched successfully, retrying...")
                            await asyncio.sleep(2)
                        else:
                            utils.logger.error("[XiaoHongShuCrawler.get_comments] Failed to switch cookie")
                            break
                    else:
                        break
            
            if not success:
                utils.logger.error(f"[XiaoHongShuCrawler.get_comments] Failed to get comments for note {note_id} after retries")
                return
            
            # 如果启用了评论截图功能，则进行整个评论区的长截图
            if config.ENABLE_GET_COMMENTS_SCREENSHOT:
                utils.logger.info(f"[XiaoHongShuCrawler.get_comments] Starting to screenshot comment section for note {note_id}")
                # 构建完整的note_url（带xsec_token参数）
                note_url = f"https://www.xiaohongshu.com/explore/{note_id}?xsec_token={xsec_token}&xsec_source=pc_search"
                screenshot_path = await self.xhs_client.screenshot_comments_section(
                    note_id=note_id,
                    note_url=note_url
                )
                if screenshot_path:
                    self.note_screenshots[note_id] = screenshot_path
                    utils.logger.info(f"[XiaoHongShuCrawler.get_comments] Screenshot saved: {screenshot_path}")
                    
                    # 立即更新截图路径并保存到 summary
                    note_detail = self.note_details_cache.get(note_id)
                    if note_detail:
                        utils.logger.info(f"[XiaoHongShuCrawler.get_comments] Updating note {note_id} with screenshot path")
                        await xhs_store.update_xhs_note(note_detail, screenshot_path)
                    else:
                        utils.logger.warning(f"[XiaoHongShuCrawler.get_comments] Note {note_id} not found in cache, cannot update screenshot path")
                else:
                    utils.logger.warning(f"[XiaoHongShuCrawler.get_comments] Failed to screenshot comment section for note {note_id}")
            
            # Sleep after fetching comments
            await asyncio.sleep(crawl_interval)
            utils.logger.info(f"[XiaoHongShuCrawler.get_comments] Sleeping for {crawl_interval} seconds after fetching comments for note {note_id}")

    def _check_comment_complete(self, note_id: str) -> bool:
        """
        检查某个笔记的评论是否完整（一级评论数量是否达标）
        Args:
            note_id: 笔记ID
        Returns:
            True 表示评论完整，False 表示不完整
        """
        import csv
        from collections import Counter
        
        crawler_type = config.CRAWLER_TYPE
        file_path = f"data/xhs/csv/{crawler_type}_comments_{utils.get_current_date()}.csv"
        
        if not os.path.exists(file_path):
            return False
        
        try:
            primary_count = 0
            with open(file_path, 'r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row.get('note_id') == note_id:
                        # 只统计一级评论（parent_comment_id 为 '0' 或为空）
                        parent_comment_id = row.get('parent_comment_id', '')
                        if parent_comment_id == '0' or parent_comment_id == '' or not parent_comment_id:
                            primary_count += 1
            
            # 检查是否达到目标数量
            return primary_count >= config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES
        except Exception as e:
            utils.logger.warning(f"[XiaoHongShuCrawler._check_comment_complete] Error checking comment for {note_id}: {e}")
            return False
    
    async def batch_screenshot_comments(self, note_list: List[str], xsec_tokens: List[str]):
        """
        批量截图（不爬取评论，只截图）
        用于评论已完整但缺少截图的情况
        """
        if not config.ENABLE_GET_COMMENTS_SCREENSHOT:
            return
        
        utils.logger.info(f"[XiaoHongShuCrawler.batch_screenshot_comments] Begin batch screenshot for {len(note_list)} notes")
        
        for note_id, xsec_token in zip(note_list, xsec_tokens):
            try:
                utils.logger.info(f"[XiaoHongShuCrawler.batch_screenshot_comments] Screenshotting note {note_id}")
                note_url = f"https://www.xiaohongshu.com/explore/{note_id}?xsec_token={xsec_token}&xsec_source=pc_search"
                screenshot_path = await self.xhs_client.screenshot_comments_section(
                    note_id=note_id,
                    note_url=note_url
                )
                if screenshot_path:
                    self.note_screenshots[note_id] = screenshot_path
                    utils.logger.info(f"[XiaoHongShuCrawler.batch_screenshot_comments] Screenshot saved: {screenshot_path}")
                    
                    # 立即更新截图路径到CSV
                    # 需要从 content.csv 中读取 note_detail
                    await self._update_screenshot_path(note_id, screenshot_path)
                    
                    # 标记为已完成
                    if self.progress_manager:
                        self.progress_manager.mark_comment_as_crawled(note_id)
                else:
                    utils.logger.warning(f"[XiaoHongShuCrawler.batch_screenshot_comments] Failed to screenshot note {note_id}")
                
                # 休眠
                await asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC)
            except Exception as e:
                utils.logger.error(f"[XiaoHongShuCrawler.batch_screenshot_comments] Error screenshotting note {note_id}: {e}")
    
    async def _update_screenshot_path(self, note_id: str, screenshot_path: str):
        """
        更新截图路径到 summary.csv
        """
        try:
            # 构造一个简单的 note_detail 对象
            note_detail = {"note_id": note_id}
            await xhs_store.update_xhs_note(note_detail, screenshot_path)
        except Exception as e:
            utils.logger.warning(f"[XiaoHongShuCrawler._update_screenshot_path] Error updating screenshot path for {note_id}: {e}")
    
    async def _check_and_rotate_resources(self):
        """
        检查并执行Cookie定期轮换
        Cookie每爬取COOKIE_ROTATION_INTERVAL个笔记后轮换
        注意：IP不再主动轮换，只在出错时切换
        """
        self.notes_count_for_rotation += 1
        
        # 检查Cookie轮换
        if self.cookie_pool_manager and config.ENABLE_COOKIE_POOL:
            if self.notes_count_for_rotation % config.COOKIE_ROTATION_INTERVAL == 0:
                next_cookie = self.cookie_pool_manager.cookie_pool.get_next_cookie()
                if next_cookie:
                    try:
                        await self.cookie_pool_manager._apply_cookie(next_cookie)
                        utils.logger.info(
                            f"[XiaoHongShuCrawler._check_and_rotate_resources] 🔄 Rotated Cookie after {self.notes_count_for_rotation} notes: "
                            f"{next_cookie.account_id}"
                        )
                    except Exception as e:
                        utils.logger.error(f"[XiaoHongShuCrawler._check_and_rotate_resources] Failed to rotate Cookie: {e}")
        
        # IP轮换已移除 - IP只在出错时通过错误处理机制切换
    
    async def _check_and_get_incomplete_screenshots(self):
        """
        检查并获取需要补全截图的已有笔记
        从 content.csv 读取笔记信息
        """
        import csv
        from collections import defaultdict
        
        crawler_type = config.CRAWLER_TYPE
        current_date = utils.get_current_date()
        
        # 读取 content.csv
        content_file = f"data/xhs/csv/{crawler_type}_contents_{current_date}.csv"
        if not os.path.exists(content_file):
            utils.logger.info(f"[_check_and_get_incomplete_screenshots] Content file not found: {content_file}")
            return []
        
        utils.logger.info(f"[_check_and_get_incomplete_screenshots] Reading content from: {content_file}")
        
        # 读取 comments.csv 统计评论数量
        comments_file = f"data/xhs/csv/{crawler_type}_comments_{current_date}.csv"
        note_comment_counts = defaultdict(int)
        if os.path.exists(comments_file):
            utils.logger.info(f"[_check_and_get_incomplete_screenshots] Reading comments from: {comments_file}")
            with open(comments_file, 'r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    note_id = row.get('note_id')
                    parent_comment_id = row.get('parent_comment_id', '')
                    # 只统计一级评论（parent_comment_id 为 '0' 或为空）
                    if parent_comment_id == '0' or parent_comment_id == '' or not parent_comment_id:
                        note_comment_counts[note_id] += 1
            utils.logger.info(f"[_check_and_get_incomplete_screenshots] Found comments for {len(note_comment_counts)} notes")
        else:
            utils.logger.warning(f"[_check_and_get_incomplete_screenshots] Comments file not found: {comments_file}")
        
        # 检查截图完整性
        screenshot_dir = "data/xhs/screenshots"
        temp_base_dir = os.path.join(screenshot_dir, "temp")
        incomplete_notes = []
        
        total_notes = 0
        notes_with_screenshot = 0
        notes_without_comments = 0
        
        with open(content_file, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                note_id = row.get('note_id')
                xsec_token = row.get('xsec_token', '')
                note_url = row.get('note_url', '')
                
                if not note_id:
                    continue
                
                total_notes += 1
                
                # 检查是否有最终截图
                screenshot_exists = False
                screenshot_filename = ""
                if os.path.exists(screenshot_dir):
                    for filename in os.listdir(screenshot_dir):
                        if note_id in filename and filename.endswith('.png') and 'comments' in filename:
                            screenshot_exists = True
                            screenshot_filename = filename
                            break
                
                # 检查评论数量
                comment_count = note_comment_counts.get(note_id, 0)
                target_count = config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES
                
                # 检查临时层文件
                note_temp_dir = os.path.join(temp_base_dir, note_id)
                layer_count = 0
                if os.path.exists(note_temp_dir):
                    for filename in os.listdir(note_temp_dir):
                        if 'layer_' in filename and note_id in filename and filename.endswith('.png'):
                            layer_count += 1
                
                # 判断是否完整
                is_complete = False
                reason = ""
                
                if screenshot_exists:
                    # 有最终截图，认为完整（不管评论数量）
                    is_complete = True
                    notes_with_screenshot += 1
                    if total_notes <= 5:
                        utils.logger.info(f"[_check_and_get_incomplete_screenshots] Note {note_id}: ✅ complete ({screenshot_filename})")
                else:
                    # 没有最终截图，需要检查是否需要删除重爬
                    if layer_count > 0:
                        # 有临时文件但没有最终截图，说明截图过程中断，需要删除重爬
                        reason = f"incomplete screenshot ({layer_count} temp layers, no final screenshot)"
                        if total_notes <= 5:
                            utils.logger.info(f"[_check_and_get_incomplete_screenshots] Note {note_id}: ⚠️  {reason} - will delete and re-crawl")
                    elif comment_count > 0:
                        # 有评论但没有截图，需要删除重爬
                        notes_without_comments += 1
                        reason = f"has comments ({comment_count}) but no screenshot"
                        if total_notes <= 5:
                            utils.logger.info(f"[_check_and_get_incomplete_screenshots] Note {note_id}: ⚠️  {reason} - will delete and re-crawl")
                    else:
                        # 没有评论也没有截图，可能是刚保存的content记录，还没开始爬评论
                        # 这种情况也需要删除，因为应该先爬评论再保存content
                        reason = f"no comments and no screenshot (incomplete record)"
                        if total_notes <= 5:
                            utils.logger.info(f"[_check_and_get_incomplete_screenshots] Note {note_id}: ⚠️  {reason} - will delete and re-crawl")
                
                # 如果不完整，添加到列表
                if not is_complete:
                    incomplete_notes.append({
                        'note_id': note_id,
                        'xsec_token': xsec_token,
                        'note_url': note_url,
                        'comment_count': comment_count,
                        'layer_count': layer_count,
                        'reason': reason
                    })
        
        # 显示统计信息
        utils.logger.info(f"[_check_and_get_incomplete_screenshots] Summary:")
        utils.logger.info(f"  - Total notes in content.csv: {total_notes}")
        utils.logger.info(f"  - Notes with complete screenshot: {notes_with_screenshot}")
        utils.logger.info(f"  - Notes without enough comments: {notes_without_comments}")
        utils.logger.info(f"  - Notes need screenshot: {len(incomplete_notes)}")
        
        return incomplete_notes
    
    async def _complete_existing_screenshots(self, incomplete_notes):
        """
        补全已有笔记的截图
        使用 content.csv 中的 URL 直接打开截图
        """
        utils.logger.info(f"[XiaoHongShuCrawler._complete_existing_screenshots] Begin completing {len(incomplete_notes)} screenshots")
        
        for idx, note_info in enumerate(incomplete_notes, 1):
            note_id = note_info['note_id']
            xsec_token = note_info['xsec_token']
            note_url = note_info.get('note_url', '')
            layer_count = note_info['layer_count']
            comment_count = note_info['comment_count']
            
            utils.logger.info(f"[XiaoHongShuCrawler._complete_existing_screenshots] ({idx}/{len(incomplete_notes)}) Processing note {note_id}")
            utils.logger.info(f"  - Comments: {comment_count}/{config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES}")
            utils.logger.info(f"  - Current layers: {layer_count}")
            
            try:
                # 构建笔记URL（优先使用保存的URL，否则构造）
                if not note_url or note_url == '':
                    note_url = f"https://www.xiaohongshu.com/explore/{note_id}"
                    if xsec_token:
                        note_url += f"?xsec_token={xsec_token}&xsec_source=pc_search"
                
                # 截图
                screenshot_path = await self.xhs_client.screenshot_comments_section(
                    note_id=note_id,
                    note_url=note_url
                )
                
                if screenshot_path:
                    self.note_screenshots[note_id] = screenshot_path
                    utils.logger.info(f"[XiaoHongShuCrawler._complete_existing_screenshots] ✓ Screenshot completed: {screenshot_path}")
                    
                    # 更新截图路径
                    await self._update_screenshot_path(note_id, screenshot_path)
                    
                    # 标记为已完成
                    if self.progress_manager:
                        self.progress_manager.mark_comment_as_crawled(note_id)
                else:
                    utils.logger.warning(f"[XiaoHongShuCrawler._complete_existing_screenshots] ✗ Failed to screenshot note {note_id}")
                
                # 休眠
                await asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC)
                
            except Exception as e:
                utils.logger.error(f"[XiaoHongShuCrawler._complete_existing_screenshots] Error processing note {note_id}: {e}")
                continue
    
    async def create_xhs_client(self, httpx_proxy: Optional[str]) -> XiaoHongShuClient:
        """Create xhs client"""
        utils.logger.info("[XiaoHongShuCrawler.create_xhs_client] Begin create xiaohongshu API client ...")
        cookie_str, cookie_dict = utils.convert_cookies(await self.browser_context.cookies())
        xhs_client_obj = XiaoHongShuClient(
            proxy=httpx_proxy,
            headers={
                "accept": "application/json, text/plain, */*",
                "accept-language": "zh-CN,zh;q=0.9",
                "cache-control": "no-cache",
                "content-type": "application/json;charset=UTF-8",
                "origin": "https://www.xiaohongshu.com",
                "pragma": "no-cache",
                "priority": "u=1, i",
                "referer": "https://www.xiaohongshu.com/",
                "sec-ch-ua": '"Chromium";v="136", "Google Chrome";v="136", "Not.A/Brand";v="99"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
                "sec-fetch-dest": "empty",
                "sec-fetch-mode": "cors",
                "sec-fetch-site": "same-site",
                "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
                "Cookie": cookie_str,
            },
            playwright_page=self.context_page,
            cookie_dict=cookie_dict,
        )
        # 将IP代理池传递给客户端，用于自动切换
        xhs_client_obj.ip_proxy_pool = self.ip_proxy_pool
        return xhs_client_obj

    async def launch_browser(
        self,
        chromium: BrowserType,
        playwright_proxy: Optional[Dict],
        user_agent: Optional[str],
        headless: bool = True,
    ) -> BrowserContext:
        """Launch browser and create browser context"""
        utils.logger.info("[XiaoHongShuCrawler.launch_browser] Begin create browser context ...")
        if config.SAVE_LOGIN_STATE:
            # feat issue #14
            # we will save login state to avoid login every time
            user_data_dir = os.path.join(os.getcwd(), "browser_data", config.USER_DATA_DIR % config.PLATFORM)  # type: ignore
            browser_context = await chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                accept_downloads=True,
                headless=headless,
                proxy=playwright_proxy,  # type: ignore
                viewport={
                    "width": 1920,
                    "height": 1080
                },
                user_agent=user_agent,
            )
            return browser_context
        else:
            browser = await chromium.launch(headless=headless, proxy=playwright_proxy)  # type: ignore
            browser_context = await browser.new_context(viewport={"width": 1920, "height": 1080}, user_agent=user_agent)
            return browser_context

    async def launch_browser_with_cdp(
        self,
        playwright: Playwright,
        playwright_proxy: Optional[Dict],
        user_agent: Optional[str],
        headless: bool = True,
    ) -> BrowserContext:
        """
        使用CDP模式启动浏览器
        """
        try:
            self.cdp_manager = CDPBrowserManager()
            browser_context = await self.cdp_manager.launch_and_connect(
                playwright=playwright,
                playwright_proxy=playwright_proxy,
                user_agent=user_agent,
                headless=headless,
            )

            # 显示浏览器信息
            browser_info = await self.cdp_manager.get_browser_info()
            utils.logger.info(f"[XiaoHongShuCrawler] CDP浏览器信息: {browser_info}")

            return browser_context

        except Exception as e:
            utils.logger.error(f"[XiaoHongShuCrawler] CDP模式启动失败，回退到标准模式: {e}")
            # 回退到标准模式
            chromium = playwright.chromium
            return await self.launch_browser(chromium, playwright_proxy, user_agent, headless)

    async def close(self):
        """Close browser context"""
        # 如果使用CDP模式，需要特殊处理
        if self.cdp_manager:
            await self.cdp_manager.cleanup()
            self.cdp_manager = None
        else:
            await self.browser_context.close()
        utils.logger.info("[XiaoHongShuCrawler.close] Browser context closed ...")

    async def get_notice_media(self, note_detail: Dict):
        if not config.ENABLE_GET_MEIDAS:
            utils.logger.info(f"[XiaoHongShuCrawler.get_notice_media] Crawling image mode is not enabled")
            return
        await self.get_note_images(note_detail)
        await self.get_notice_video(note_detail)

    async def get_note_images(self, note_item: Dict):
        """
        get note images. please use get_notice_media
        :param note_item:
        :return:
        """
        if not config.ENABLE_GET_MEIDAS:
            return
        note_id = note_item.get("note_id")
        image_list: List[Dict] = note_item.get("image_list", [])

        for img in image_list:
            if img.get("url_default") != "":
                img.update({"url": img.get("url_default")})

        if not image_list:
            return
        picNum = 0
        for pic in image_list:
            url = pic.get("url")
            if not url:
                continue
            content = await self.xhs_client.get_note_media(url)
            await asyncio.sleep(random.random())
            if content is None:
                continue
            extension_file_name = f"{picNum}.jpg"
            picNum += 1
            await xhs_store.update_xhs_note_image(note_id, content, extension_file_name)

    async def get_notice_video(self, note_item: Dict):
        """
        get note videos. please use get_notice_media
        :param note_item:
        :return:
        """
        if not config.ENABLE_GET_MEIDAS:
            return
        note_id = note_item.get("note_id")

        videos = xhs_store.get_video_url_arr(note_item)

        if not videos:
            return
        videoNum = 0
        for url in videos:
            content = await self.xhs_client.get_note_media(url)
            await asyncio.sleep(random.random())
            if content is None:
                continue
            extension_file_name = f"{videoNum}.mp4"
            videoNum += 1
            await xhs_store.update_xhs_note_video(note_id, content, extension_file_name)
