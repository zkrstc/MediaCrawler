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
import json
import os
import time
import re
from typing import Any, Callable, Dict, List, Optional, Union
from urllib.parse import urlencode

import httpx
from playwright.async_api import BrowserContext, Page
from tenacity import retry, stop_after_attempt, wait_fixed
from PIL import Image

import config
from base.base_crawler import AbstractApiClient
from tools import utils

from .exception import DataFetchError, IPBlockError
from .field import SearchNoteType, SearchSortType
from .help import get_search_id, sign
from .extractor import XiaoHongShuExtractor
from .secsign import seccore_signv2_playwright

class XiaoHongShuClient(AbstractApiClient):

    def __init__(
        self,
        timeout=60,  # 若开启爬取媒体选项，xhs 的长视频需要更久的超时时间
        proxy=None,
        *,
        headers: Dict[str, str],
        playwright_page: Page,
        cookie_dict: Dict[str, str],
    ):
        self.proxy = proxy
        self.timeout = timeout
        self.headers = headers
        self._host = "https://edith.xiaohongshu.com"
        self._domain = "https://www.xiaohongshu.com"
        self.IP_ERROR_STR = "网络连接异常，请检查网络设置或重启试试"
        self.IP_ERROR_CODE = 300012
        self.NOTE_ABNORMAL_STR = "笔记状态异常，请稍后查看"
        self.NOTE_ABNORMAL_CODE = -510001
        self.playwright_page = playwright_page
        self.cookie_dict = cookie_dict
        self._extractor = XiaoHongShuExtractor()
        self.ip_proxy_pool = None  # Will be set by crawler
        self.cookie_pool_manager = None  # Will be set by crawler

    async def _pre_headers(self, url: str, data=None) -> Dict:
        """
        请求头参数签名
        Args:
            url:
            data:

        Returns:

        """
        # Wait for window._webmsxyw to be available
        try:
            await self.playwright_page.wait_for_function(
                "typeof window._webmsxyw === 'function'",
                timeout=10000
            )
        except Exception as e:
            utils.logger.error(f"[XiaoHongShuClient._pre_headers] window._webmsxyw not available: {e}")
            # Try to reload the page if the function is not available
            utils.logger.info("[XiaoHongShuClient._pre_headers] Reloading page to initialize window._webmsxyw")
            await self.playwright_page.reload(wait_until="networkidle")
            await self.playwright_page.wait_for_function(
                "typeof window._webmsxyw === 'function'",
                timeout=10000
            )
        
        x_s = await seccore_signv2_playwright(self.playwright_page, url, data)
        local_storage = await self.playwright_page.evaluate("() => window.localStorage")
        signs = sign(
            a1=self.cookie_dict.get("a1", ""),
            b1=local_storage.get("b1", ""),
            x_s=x_s,
            x_t=str(int(time.time())),
        )

        headers = {
            "X-S": signs["x-s"],
            "X-T": signs["x-t"],
            "x-S-Common": signs["x-s-common"],
            "X-B3-Traceid": signs["x-b3-traceid"],
        }
        self.headers.update(headers)
        return self.headers

    async def update_proxy(self, new_proxy: str):
        """
        更新代理IP
        Args:
            new_proxy: 新的代理地址
        """
        self.proxy = new_proxy
        utils.logger.info(f"[XiaoHongShuClient.update_proxy] Proxy updated to: {new_proxy}")

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(1))
    async def request(self, method, url, **kwargs) -> Union[str, Any]:
        """
        封装httpx的公共请求方法，对请求响应做一些处理
        Args:
            method: 请求方法
            url: 请求的URL
            **kwargs: 其他请求参数，例如请求头、请求体等

        Returns:

        """
        # return response.text
        return_response = kwargs.pop("return_response", False)
        
        try:
            async with httpx.AsyncClient(proxy=self.proxy) as client:
                response = await client.request(method, url, timeout=self.timeout, **kwargs)
        except httpx.ProxyError as e:
            error_msg = str(e)
            utils.logger.error(f"[XiaoHongShuClient.request] Proxy error: {error_msg}")
            
            # 检测是否是代理认证失败（460错误或Authentication Invalid）
            if "460" in error_msg or "Proxy Authentication Invalid" in error_msg or "Authentication Invalid" in error_msg:
                utils.logger.warning("[XiaoHongShuClient.request] Proxy authentication failed, attempting to switch proxy...")
                
                # 尝试切换代理
                if self.ip_proxy_pool:
                    try:
                        new_ip_info = await self.ip_proxy_pool.get_proxy()
                        from tools import utils as tool_utils
                        _, new_httpx_proxy = tool_utils.format_proxy_info(new_ip_info)
                        await self.update_proxy(new_httpx_proxy)
                        utils.logger.info(f"[XiaoHongShuClient.request] Switched to new proxy: {new_ip_info.ip}:{new_ip_info.port}")
                        
                        # 重试请求
                        async with httpx.AsyncClient(proxy=self.proxy) as client:
                            response = await client.request(method, url, timeout=self.timeout, **kwargs)
                    except Exception as switch_error:
                        utils.logger.error(f"[XiaoHongShuClient.request] Failed to switch proxy: {switch_error}")
                        raise
                else:
                    utils.logger.error("[XiaoHongShuClient.request] No proxy pool available for switching")
                    raise
            else:
                raise

        if response.status_code == 471 or response.status_code == 461:
            # 验证码错误，尝试切换Cookie和IP
            verify_type = response.headers.get("Verifytype", "unknown")
            verify_uuid = response.headers.get("Verifyuuid", "unknown")
            msg = f"出现验证码，请求失败，Verifytype: {verify_type}，Verifyuuid: {verify_uuid}, Response: {response}"
            utils.logger.error(msg)
            
            # 创建自定义异常用于标识验证码错误
            from .exception import CaptchaError
            raise CaptchaError(msg, verify_type=verify_type, verify_uuid=verify_uuid)

        if return_response:
            return response.text
        data: Dict = response.json()
        if data.get("success"):
            return data.get("data", data.get("success", {}))
        elif data.get("code") == self.IP_ERROR_CODE:
            raise IPBlockError(self.IP_ERROR_STR)
        elif data.get("code") in [-100, -101, -102, -104]:
            # Cookie/permission related errors - trigger cookie switching
            # -100: 登录已过期 (Login expired)
            # -101: 未登录 (Not logged in)
            # -102: 登录状态失效 (Login state invalid)
            # -104: 账号没有权限访问 (Account has no permission)
            error_msg = data.get("msg", "Cookie/Permission error")
            utils.logger.error(f"[XiaoHongShuClient.request] Cookie/Permission error (code: {data.get('code')}) - URL: {url}, Response: {data}")
            
            # Import and raise CookieBlockedException to trigger automatic cookie switching
            from tools.cookie_guard import CookieBlockedException
            raise CookieBlockedException(error_msg)
        else:
            # Log the full response for debugging
            error_msg = data.get("msg") or data.get("message") or f"Request failed with response: {data}"
            utils.logger.error(f"[XiaoHongShuClient.request] API request failed - URL: {url}, Response: {data}")
            raise DataFetchError(error_msg)

    async def get(self, uri: str, params=None) -> Dict:
        """
        GET请求，对请求头签名
        Args:
            uri: 请求路由
            params: 请求参数

        Returns:

        """
        final_uri = uri
        if isinstance(params, dict):
            final_uri = f"{uri}?" f"{urlencode(params)}"
        headers = await self._pre_headers(final_uri)
        return await self.request(
            method="GET", url=f"{self._host}{final_uri}", headers=headers
        )

    async def post(self, uri: str, data: dict, **kwargs) -> Dict:
        """
        POST请求，对请求头签名
        Args:
            uri: 请求路由
            data: 请求体参数

        Returns:

        """
        headers = await self._pre_headers(uri, data)
        json_str = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
        return await self.request(
            method="POST",
            url=f"{self._host}{uri}",
            data=json_str,
            headers=headers,
            **kwargs,
        )

    async def get_note_media(self, url: str) -> Union[bytes, None]:
        async with httpx.AsyncClient(proxy=self.proxy) as client:
            try:
                response = await client.request("GET", url, timeout=self.timeout)
                response.raise_for_status()
                if not response.reason_phrase == "OK":
                    utils.logger.error(
                        f"[XiaoHongShuClient.get_note_media] request {url} err, res:{response.text}"
                    )
                    return None
                else:
                    return response.content
            except (
                httpx.HTTPError
            ) as exc:  # some wrong when call httpx.request method, such as connection error, client error, server error or response status code is not 2xx
                utils.logger.error(
                    f"[XiaoHongShuClient.get_aweme_media] {exc.__class__.__name__} for {exc.request.url} - {exc}"
                )  # 保留原始异常类型名称，以便开发者调试
                return None

    async def pong(self) -> bool:
        """
        用于检查登录态是否失效了
        Returns:

        """
        """get a note to check if login state is ok"""
        utils.logger.info("[XiaoHongShuClient.pong] Begin to pong xhs...")
        ping_flag = False
        try:
            note_card: Dict = await self.get_note_by_keyword(keyword="小红书")
            if note_card.get("items"):
                ping_flag = True
        except Exception as e:
            utils.logger.error(
                f"[XiaoHongShuClient.pong] Ping xhs failed: {e}, and try to login again..."
            )
            ping_flag = False
        return ping_flag

    async def update_cookies(self, browser_context: BrowserContext):
        """
        API客户端提供的更新cookies方法，一般情况下登录成功后会调用此方法
        Args:
            browser_context: 浏览器上下文对象

        Returns:

        """
        cookie_str, cookie_dict = utils.convert_cookies(await browser_context.cookies())
        self.headers["Cookie"] = cookie_str
        self.cookie_dict = cookie_dict

    async def get_note_by_keyword(
        self,
        keyword: str,
        search_id: str = get_search_id(),
        page: int = 1,
        page_size: int = 20,
        sort: SearchSortType = SearchSortType.GENERAL,
        note_type: SearchNoteType = SearchNoteType.ALL,
    ) -> Dict:
        """
        根据关键词搜索笔记
        Args:
            keyword: 关键词参数
            page: 分页第几页
            page_size: 分页数据长度
            sort: 搜索结果排序指定
            note_type: 搜索的笔记类型

        Returns:

        """
        uri = "/api/sns/web/v1/search/notes"
        data = {
            "keyword": keyword,
            "page": page,
            "page_size": page_size,
            "search_id": search_id,
            "sort": sort.value,
            "note_type": note_type.value,
        }
        return await self.post(uri, data)

    async def get_note_by_id(
        self,
        note_id: str,
        xsec_source: str,
        xsec_token: str,
    ) -> Dict:
        """
        获取笔记详情API
        Args:
            note_id:笔记ID
            xsec_source: 渠道来源
            xsec_token: 搜索关键字之后返回的比较列表中返回的token

        Returns:

        """
        if xsec_source == "":
            xsec_source = "pc_search"

        data = {
            "source_note_id": note_id,
            "image_formats": ["jpg", "webp", "avif"],
            "extra": {"need_body_topic": 1},
            "xsec_source": xsec_source,
            "xsec_token": xsec_token,
        }
        uri = "/api/sns/web/v1/feed"
        res = await self.post(uri, data)
        if res and res.get("items"):
            res_dict: Dict = res["items"][0]["note_card"]
            return res_dict
        # 爬取频繁了可能会出现有的笔记能有结果有的没有
        utils.logger.error(
            f"[XiaoHongShuClient.get_note_by_id] get note id:{note_id} empty and res:{res}"
        )
        return dict()

    async def get_note_comments(
        self,
        note_id: str,
        xsec_token: str,
        cursor: str = "",
    ) -> Dict:
        """
        获取一级评论的API
        Args:
            note_id: 笔记ID
            xsec_token: 验证token
            cursor: 分页游标

        Returns:

        """
        uri = "/api/sns/web/v2/comment/page"
        params = {
            "note_id": note_id,
            "cursor": cursor,
            "top_comment_id": "",
            "image_formats": "jpg,webp,avif",
            "xsec_token": xsec_token,
        }
        return await self.get(uri, params)

    async def get_note_sub_comments(
        self,
        note_id: str,
        root_comment_id: str,
        xsec_token: str,
        num: int = 10,
        cursor: str = "",
    ):
        """
        获取指定父评论下的子评论的API
        Args:
            note_id: 子评论的帖子ID
            root_comment_id: 根评论ID
            xsec_token: 验证token
            num: 分页数量
            cursor: 分页游标

        Returns:

        """
        uri = "/api/sns/web/v2/comment/sub/page"
        params = {
            "note_id": note_id,
            "root_comment_id": root_comment_id,
            "num": num,
            "cursor": cursor,
            "image_formats": "jpg,webp,avif",
            "top_comment_id": "",
            "xsec_token": xsec_token,
        }
        return await self.get(uri, params)

    async def get_note_all_comments(
        self,
        note_id: str,
        xsec_token: str,
        crawl_interval: float = 1.0,
        callback: Optional[Callable] = None,
        max_count: int = 10,
    ) -> List[Dict]:
        """
        获取指定笔记下的所有一级评论，该方法会一直查找一个帖子下的所有评论信息
        Args:
            note_id: 笔记ID
            xsec_token: 验证token
            crawl_interval: 爬取一次笔记的延迟单位（秒）
            callback: 一次笔记爬取结束后
            max_count: 一次笔记爬取的最大评论数量
        Returns:

        """
        result = []
        comments_has_more = True
        comments_cursor = ""
        
        utils.logger.info(f"[XiaoHongShuClient.get_note_all_comments] 📝 Note {note_id}: Starting to crawl comments (target: {max_count})")
        
        while comments_has_more and len(result) < max_count:
            comments_res = await self.get_note_comments(
                note_id=note_id, xsec_token=xsec_token, cursor=comments_cursor
            )
            comments_has_more = comments_res.get("has_more", False)
            comments_cursor = comments_res.get("cursor", "")
            if "comments" not in comments_res:
                utils.logger.info(
                    f"[XiaoHongShuClient.get_note_all_comments] No 'comments' key found in response: {comments_res}"
                )
                break
            comments = comments_res["comments"]
            if len(result) + len(comments) > max_count:
                comments = comments[: max_count - len(result)]
            if callback:
                await callback(note_id, comments)
            await asyncio.sleep(crawl_interval)
            result.extend(comments)
            
            # 显社进度
            utils.logger.info(f"[XiaoHongShuClient.get_note_all_comments] 📝 Note {note_id}: Crawled {len(result)}/{max_count} primary comments")
            sub_comments = await self.get_comments_all_sub_comments(
                comments=comments,
                xsec_token=xsec_token,
                crawl_interval=crawl_interval,
                callback=callback,
            )
            result.extend(sub_comments)
        
        utils.logger.info(f"[XiaoHongShuClient.get_note_all_comments] ✅ Note {note_id}: Finished crawling {len(result)} comments (primary + sub)")
        return result

    async def get_comments_all_sub_comments(
        self,
        comments: List[Dict],
        xsec_token: str,
        crawl_interval: float = 1.0,
        callback: Optional[Callable] = None,
    ) -> List[Dict]:
        """
        获取指定一级评论下的二级评论
        
        注意：小红书页面展开规则
        - 如果二级评论总数 > 6条，第一次点击"展开回复"会显示6条（原本1条 + 新显示5条）
        - 如果二级评论总数 ≤ 6条，第一次点击"展开回复"会显示全部
        - 建议设置 CRAWLER_MAX_SUB_COMMENTS_COUNT_PER_COMMENT = 6 来模拟第一次展开的效果
        
        Args:
            comments: 评论列表
            xsec_token: 验证token
            crawl_interval: 爬取一次评论的延迟单位（秒）
            callback: 一次评论爬取结束后

        Returns:
            二级评论列表
        """
        if not config.ENABLE_GET_SUB_COMMENTS:
            utils.logger.info(
                f"[XiaoHongShuCrawler.get_comments_all_sub_comments] Crawling sub_comment mode is not enabled"
            )
            return []

        result = []
        for comment in comments:
            note_id = comment.get("note_id")
            sub_comments = comment.get("sub_comments")
            
            # 统计当前一级评论下已爬取的二级评论数量
            sub_comments_count = 0
            max_sub_comments = config.CRAWLER_MAX_SUB_COMMENTS_COUNT_PER_COMMENT
            
            if sub_comments and callback:
                await callback(note_id, sub_comments)
                sub_comments_count += len(sub_comments)

            sub_comment_has_more = comment.get("sub_comment_has_more")
            if not sub_comment_has_more:
                continue

            root_comment_id = comment.get("id")
            sub_comment_cursor = comment.get("sub_comment_cursor")

            # 检查是否需要限制数量 (0表示不限制)
            while sub_comment_has_more:
                # 如果设置了限制且已达到限制，则停止爬取
                if max_sub_comments > 0 and sub_comments_count >= max_sub_comments:
                    utils.logger.info(
                        f"[XiaoHongShuClient.get_comments_all_sub_comments] Reached sub-comment limit ({max_sub_comments}) for comment {root_comment_id}"
                    )
                    break
                
                try:
                    comments_res = await self.get_note_sub_comments(
                        note_id=note_id,
                        root_comment_id=root_comment_id,
                        xsec_token=xsec_token,
                        num=10,
                        cursor=sub_comment_cursor,
                    )
                except Exception as e:
                    utils.logger.error(
                        f"[XiaoHongShuClient.get_comments_all_sub_comments] Failed to get sub-comments for {root_comment_id}: {e}"
                    )
                    # 获取二级评论失败时，跳过这个评论，继续处理下一个
                    break

                if comments_res is None:
                    utils.logger.info(
                        f"[XiaoHongShuClient.get_comments_all_sub_comments] No response found for note_id: {note_id}"
                    )
                    continue
                sub_comment_has_more = comments_res.get("has_more", False)
                sub_comment_cursor = comments_res.get("cursor", "")
                if "comments" not in comments_res:
                    utils.logger.info(
                        f"[XiaoHongShuClient.get_comments_all_sub_comments] No 'comments' key found in response: {comments_res}"
                    )
                    break
                comments = comments_res["comments"]
                
                # 如果设置了限制，只取需要的数量
                if max_sub_comments > 0:
                    remaining = max_sub_comments - sub_comments_count
                    comments = comments[:remaining]
                
                if callback:
                    await callback(note_id, comments)
                await asyncio.sleep(crawl_interval)
                result.extend(comments)
                sub_comments_count += len(comments)
        return result

    async def screenshot_comment_element(
        self,
        note_id: str,
        comment_id: str,
        include_sub_comments: bool = True,
    ) -> Optional[str]:
        """
        对评论元素进行截图（支持截取一级评论及其二级评论）
        
        Args:
            note_id: 笔记ID
            comment_id: 评论ID
            include_sub_comments: 是否包含二级评论区域（True=截取整个评论区，False=只截取一级评论本身）
            
        Returns:
            截图保存路径，失败返回None
        """
        if not config.ENABLE_GET_COMMENTS_SCREENSHOT:
            return None
            
        try:
            # 构建笔记URL
            note_url = f"https://www.xiaohongshu.com/explore/{note_id}"
            
            # 如果当前页面不是目标笔记页面，则导航到该页面
            current_url = self.playwright_page.url
            if note_id not in current_url:
                utils.logger.info(f"[screenshot_comment_element] Navigating to note page: {note_url}")
                await self.playwright_page.goto(note_url, wait_until="networkidle", timeout=30000)
                await asyncio.sleep(2)
            
            # 等待评论区加载
            await self.playwright_page.wait_for_selector('[class*="comment"]', timeout=10000)
            
            # 尝试多种选择器来定位评论元素
            comment_selectors = [
                f'[data-id="{comment_id}"]',
                f'[id*="{comment_id}"]',
                f'[data-comment-id="{comment_id}"]',
            ]
            
            comment_element = None
            for selector in comment_selectors:
                try:
                    locator = self.playwright_page.locator(selector).first
                    if await locator.count() > 0:
                        comment_element = locator
                        utils.logger.info(f"[screenshot_comment_element] Found comment with selector: {selector}")
                        break
                except Exception:
                    continue
            
            # 如果通过data属性找不到，尝试通过文本内容查找
            if not comment_element:
                utils.logger.warning(f"[screenshot_comment_element] Cannot find comment element by ID, trying alternative method")
                # 这里可以根据实际需要添加更多查找逻辑
                return None
            
            # 滚动到评论元素可见
            await comment_element.scroll_into_view_if_needed()
            await asyncio.sleep(0.5)
            
            # 创建截图保存目录
            screenshot_dir = os.path.join("data", "xhs", "screenshots", note_id)
            os.makedirs(screenshot_dir, exist_ok=True)
            
            # 生成截图文件名
            timestamp = utils.get_current_timestamp()
            screenshot_filename = f"comment_{comment_id}_{timestamp}.png"
            if include_sub_comments:
                screenshot_filename = f"comment_with_replies_{comment_id}_{timestamp}.png"
            
            screenshot_path = os.path.join(screenshot_dir, screenshot_filename)
            
            # 截图
            await comment_element.screenshot(path=screenshot_path, timeout=10000)
            
            utils.logger.info(f"[screenshot_comment_element] Screenshot saved: {screenshot_path}")
            return screenshot_path
            
        except Exception as e:
            utils.logger.error(f"[screenshot_comment_element] Error taking screenshot for comment {comment_id}: {e}")
            return None

    async def screenshot_comments_section(
        self,
        note_id: str,
        note_url: str = None,
    ) -> Optional[str]:
        """
        对整个评论区进行长截图（包含一级评论和展开后的二级评论）
        
        Args:
            note_id: 笔记ID
            note_url: 笔记URL（可选，如果不提供则自动构建）
            
        Returns:
            截图保存路径，失败返回None
        """
        if not config.ENABLE_GET_COMMENTS_SCREENSHOT:
            utils.logger.info("[screenshot_comments_section] Comment screenshot is not enabled")
            return None
        
        # 获取要截图的评论数量配置
        screenshot_count = config.SCREENSHOT_COMMENTS_COUNT
        
        try:
            # 构建笔记URL
            if not note_url:
                note_url = f"https://www.xiaohongshu.com/explore/{note_id}"
            
            utils.logger.info(f"[screenshot_comments_section] Starting to screenshot comment section for note: {note_id}")
            utils.logger.info(f"[screenshot_comments_section] Target URL: {note_url}")
            
            # 检查当前页面URL，判断是否需要导航
            try:
                current_url = self.playwright_page.url
                utils.logger.info(f"[screenshot_comments_section] Current URL: {current_url}")
                # 检查是否已经在目标笔记页面（完整匹配）
                need_navigate = f"/explore/{note_id}" not in current_url
            except:
                current_url = ""
                need_navigate = True
            
            # 导航到笔记详情页
            if need_navigate:
                utils.logger.info(f"[screenshot_comments_section] Navigating to note page: {note_url}")
                try:
                    await self.playwright_page.goto(note_url, wait_until="load", timeout=60000)
                    await asyncio.sleep(3)  # 等待页面稳定
                    utils.logger.info(f"[screenshot_comments_section] Navigation successful")
                except Exception as e:
                    utils.logger.error(f"[screenshot_comments_section] Navigation failed: {e}")
                    return None
            else:
                utils.logger.info(f"[screenshot_comments_section] Already on target note page, no navigation needed")
                await asyncio.sleep(1)
            
            # 先滚动页面，让评论区加载出来
            utils.logger.info("[screenshot_comments_section] Scrolling down to load comments...")
            for i in range(3):
                await self.playwright_page.evaluate("window.scrollBy(0, window.innerHeight)")
                await asyncio.sleep(1)
            
            # 等待评论区加载，尝试多种选择器
            utils.logger.info("[screenshot_comments_section] Waiting for comment section to load...")
            comment_loaded = False
            comment_selectors_to_try = [
                '[class*="comment"]',
                '[class*="Comment"]',
                '[id*="comment"]',
                'text=全部评论',
                'text=评论',
            ]
            
            for selector in comment_selectors_to_try:
                try:
                    await self.playwright_page.wait_for_selector(selector, timeout=5000)
                    utils.logger.info(f"[screenshot_comments_section] Comment section found with selector: {selector}")
                    comment_loaded = True
                    break
                except Exception:
                    continue
            
            if not comment_loaded:
                utils.logger.warning(f"[screenshot_comments_section] Comment section not found after trying all selectors")
                # 尝试截图整个页面看看
                try:
                    screenshot_dir = os.path.join("data", "xhs", "screenshots")
                    os.makedirs(screenshot_dir, exist_ok=True)
                    debug_path = os.path.join(screenshot_dir, f"debug_{note_id}.png")
                    await self.playwright_page.screenshot(path=debug_path)
                    utils.logger.info(f"[screenshot_comments_section] Saved debug screenshot: {debug_path}")
                except:
                    pass
                return None
            
            # 滚动到评论区
            utils.logger.info("[screenshot_comments_section] Scrolling to comment section...")
            try:
                # 尝试多种评论区容器选择器
                comment_container_selectors = [
                    '[class*="comment-container"]',
                    '[class*="comments"]',
                    '[class*="comment-section"]',
                    '[id*="comment"]',
                ]
                
                comment_container = None
                for selector in comment_container_selectors:
                    try:
                        locator = self.playwright_page.locator(selector).first
                        if await locator.count() > 0:
                            comment_container = locator
                            await comment_container.scroll_into_view_if_needed()
                            utils.logger.info(f"[screenshot_comments_section] Found comment container with selector: {selector}")
                            break
                    except Exception:
                        continue
                
                # 如果找不到容器，就滚动到第一个评论元素
                if not comment_container:
                    comment_selectors = ['[class*="comment-item"]', '[class*="CommentItem"]']
                    for selector in comment_selectors:
                        try:
                            first_comment = self.playwright_page.locator(selector).first
                            if await first_comment.count() > 0:
                                await first_comment.scroll_into_view_if_needed()
                                comment_container = first_comment
                                break
                        except Exception:
                            continue
                
                if not comment_container:
                    utils.logger.warning("[screenshot_comments_section] Cannot find comment section")
                    return None
                    
            except Exception as e:
                utils.logger.warning(f"[screenshot_comments_section] Error scrolling to comments: {e}")
            
            await asyncio.sleep(1)
            
            # 小红书使用懒加载机制：滚动到底部会自动加载下一批10条评论
            utils.logger.info("[screenshot_comments_section] 📜 Loading comments using scroll-based lazy loading...")
            
            # 根据目标评论数量计算需要滚动的次数
            max_scroll_attempts = max(3, (screenshot_count + 9) // 10) if screenshot_count > 0 else 3
            utils.logger.info(f"[screenshot_comments_section] 📜 Target: {screenshot_count} comments, will scroll up to {max_scroll_attempts} times")
            
            scroll_attempts = 0
            last_comment_count = 0
            no_change_count = 0
            
            while scroll_attempts < max_scroll_attempts:
                # 检查当前评论数量
                try:
                    current_count = await self.playwright_page.locator('.parent-comment').count()
                    utils.logger.info(f"[screenshot_comments_section] 📊 Current: {current_count} comments (target: {screenshot_count})")
                    
                    # 如果已经达到目标数量，停止滚动
                    if current_count >= screenshot_count:
                        utils.logger.info(f"[screenshot_comments_section] ✅ Loaded enough comments ({current_count} >= {screenshot_count})")
                        break
                    
                    # 如果评论数量没有变化，记录次数
                    if current_count == last_comment_count:
                        no_change_count += 1
                        if no_change_count >= 2:
                            utils.logger.warning(f"[screenshot_comments_section] ⚠️  Comment count not changing, stopping (may have fewer comments)")
                            break
                    else:
                        no_change_count = 0
                        last_comment_count = current_count
                    
                except Exception as e:
                    utils.logger.warning(f"[screenshot_comments_section] Error checking comment count: {e}")
                
                # 滚动到评论区底部，触发懒加载
                try:
                    utils.logger.info(f"[screenshot_comments_section] 📜 Scrolling to load more (attempt {scroll_attempts + 1}/{max_scroll_attempts})")
                    
                    # 找到最后一个评论元素并滚动到它
                    last_comment = self.playwright_page.locator('.parent-comment').last
                    if await last_comment.count() > 0:
                        await last_comment.scroll_into_view_if_needed()
                        await asyncio.sleep(0.5)
                        
                        # 再往下滚动一点，确保触发懒加载
                        await self.playwright_page.evaluate("window.scrollBy(0, 500)")
                        await asyncio.sleep(1.5)  # 等待加载
                    else:
                        # 如果找不到评论元素，直接滚动到底部
                        await self.playwright_page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                        await asyncio.sleep(1.5)
                    
                    scroll_attempts += 1
                    
                except Exception as e:
                    utils.logger.warning(f"[screenshot_comments_section] Error scrolling: {e}")
                    scroll_attempts += 1
            
            # 最终检查
            try:
                final_count = await self.playwright_page.locator('.parent-comment').count()
                utils.logger.info(f"[screenshot_comments_section] 📊 Final: {final_count} comments loaded (target was {screenshot_count})")
                
                if final_count < screenshot_count:
                    utils.logger.warning(f"[screenshot_comments_section] ⚠️  Only loaded {final_count}/{screenshot_count} comments")
            except:
                pass
            
            # 等待评论加载完成
            await asyncio.sleep(1)
            
            # ========== 新增：逐层截图并拼接成长图 ==========
            utils.logger.info(f"[screenshot_comments_section] Starting layer-by-layer screenshot (target: {screenshot_count if screenshot_count > 0 else 'all'} comments)...")
            
            # 创建截图保存目录（按笔记ID隔离）
            screenshot_dir = os.path.join("data", "xhs", "screenshots")
            temp_dir = os.path.join(screenshot_dir, "temp", note_id)  # 每个笔记独立目录
            os.makedirs(temp_dir, exist_ok=True)
            
            # 清理该笔记的旧临时文件（如果存在）
            if os.path.exists(temp_dir):
                for old_file in os.listdir(temp_dir):
                    if old_file.startswith('layer_') and old_file.endswith('.png'):
                        try:
                            os.remove(os.path.join(temp_dir, old_file))
                        except:
                            pass
            
            # 查找所有父评论（每个父评论包含1个一级评论+其所有二级评论）
            # 根据小红书的HTML结构，使用parent-comment选择器
            comment_selectors = [
                '#content-comments .parent-comment',  # 从评论区容器内查找
                '#detail-comment .parent-comment',  # 另一种可能的容器ID
                'div[id*="comment"] .parent-comment',  # 从任何评论容器内查找
                '.parent-comment',  # 直接查找（可能会选到容器）
                '[class*="parent-comment"]',
                'div.parent-comment',
            ]
            
            comment_locator = None
            total_comments = 0
            for selector in comment_selectors:
                try:
                    locator = self.playwright_page.locator(selector)
                    count = await locator.count()
                    if count > 0:
                        # 验证选到的是真正的评论元素（包含用户名、内容等）
                        first_elem = locator.first
                        # 检查是否包含评论的基本元素（用户信息、内容等）
                        text = await first_elem.inner_text()
                        if len(text) > 0:  # 确保有文本内容
                            # 检查第一个元素的高度，如果异常高说明选择器有问题
                            first_box = await first_elem.bounding_box()
                            if first_box and first_box['height'] > 5000:
                                utils.logger.warning(f"[screenshot_comments_section] Selector {selector} first element height is {first_box['height']:.0f}px (abnormal!)")
                                utils.logger.warning(f"[screenshot_comments_section] This selector may be selecting a container instead of individual comments")
                                # 尝试下一个选择器
                                continue
                            
                            comment_locator = locator
                            total_comments = count
                            utils.logger.info(f"[screenshot_comments_section] Found {count} comments with selector: {selector}")
                            utils.logger.info(f"[screenshot_comments_section] First comment preview: {text[:50]}...")
                            if first_box:
                                utils.logger.info(f"[screenshot_comments_section] First comment height: {first_box['height']:.0f}px")
                            break
                except Exception as e:
                    utils.logger.debug(f"[screenshot_comments_section] Selector {selector} failed: {e}")
                    continue
            
            if not comment_locator or total_comments == 0:
                utils.logger.warning("[screenshot_comments_section] No comment elements found")
                # 输出页面HTML结构用于调试
                try:
                    page_content = await self.playwright_page.content()
                    debug_file = os.path.join(temp_dir, f"debug_page_{note_id}.html")
                    with open(debug_file, 'w', encoding='utf-8') as f:
                        f.write(page_content)
                    utils.logger.info(f"[screenshot_comments_section] Page HTML saved to {debug_file} for debugging")
                except:
                    pass
                return None
            
            # 验证找到的父评论元素并输出详细信息
            utils.logger.info(f"[screenshot_comments_section] Validating {total_comments} parent comment elements...")
            valid_comment_indices = []
            valid_comment_ids = []  # 保存评论ID用于验证
            
            for i in range(min(total_comments, 50)):  # 最多检查前50个
                try:
                    elem = comment_locator.nth(i)
                    # 查找父评论中的一级评论（不包含comment-item-sub）
                    primary_comment = elem.locator('.comment-item:not(.comment-item-sub)').first
                    if await primary_comment.count() > 0:
                        text = await primary_comment.inner_text()
                        if text and len(text.strip()) > 10:
                            # 获取评论ID
                            comment_id = await elem.evaluate("el => el.querySelector('.comment-item')?.id || ''")
                            
                            valid_comment_indices.append(i)
                            valid_comment_ids.append(comment_id)
                            
                            if len(valid_comment_indices) <= 3:  # 只显示前3个
                                # 提取评论内容（去掉日期、点赞数等）
                                content_lines = text.split('\n')
                                main_content = next((line for line in content_lines if len(line.strip()) > 10), text)
                                utils.logger.info(f"[screenshot_comments_section] Valid parent comment {len(valid_comment_indices)}: ID={comment_id}, Content={main_content[:60]}...")
                except:
                    continue
            
            utils.logger.info(f"[screenshot_comments_section] Found {len(valid_comment_indices)} valid parent comments out of {total_comments} elements")
            
            if len(valid_comment_indices) == 0:
                utils.logger.error("[screenshot_comments_section] No valid parent comment elements found")
                return None
            
            # 限制截图的评论数量
            target_count = min(screenshot_count if screenshot_count > 0 else len(valid_comment_indices), len(valid_comment_indices))
            
            # 详细日志
            utils.logger.info(f"[screenshot_comments_section] Screenshot configuration:")
            utils.logger.info(f"  - Config target: {screenshot_count}")
            utils.logger.info(f"  - Valid comments found: {len(valid_comment_indices)}")
            utils.logger.info(f"  - Final target: {target_count}")
            
            if target_count < screenshot_count:
                utils.logger.warning(f"[screenshot_comments_section] ⚠️  Only found {len(valid_comment_indices)} valid comments, less than target {screenshot_count}")
                utils.logger.warning(f"[screenshot_comments_section] ⚠️  Will only screenshot {target_count} layers")
            
            utils.logger.info(f"[screenshot_comments_section] Will screenshot {target_count} parent comments (each with primary + sub-comments, layer by layer)")
            
            # 逐层截图
            layer_screenshots = []
            timestamp = utils.get_current_timestamp()
            successful_screenshots = 0
            
            # 隐藏所有互动栏（interactions），减少空白和不必要的内容
            try:
                await self.playwright_page.evaluate("""
                    // 隐藏所有评论的互动栏（点赞、评论等）
                    const interactions = document.querySelectorAll('.interactions, .info .interactions');
                    interactions.forEach(bar => {
                        bar.style.display = 'none';
                    });
                    
                    // 减少评论之间的间距
                    const comments = document.querySelectorAll('.parent-comment');
                    comments.forEach(comment => {
                        comment.style.marginBottom = '5px';
                        comment.style.paddingBottom = '0px';
                    });
                    
                    // 减少一级评论和二级评论之间的间距
                    const replyCont = document.querySelectorAll('.reply-container');
                    replyCont.forEach(container => {
                        container.style.marginTop = '5px';
                        container.style.paddingTop = '0px';
                    });
                """)
                utils.logger.info("[screenshot_comments_section] Hidden interactions and reduced spacing")
                await asyncio.sleep(0.5)
            except Exception as e:
                utils.logger.warning(f"[screenshot_comments_section] Failed to hide interactions: {e}")
            
            # 只处理验证过的有效父评论
            for idx, comment_idx in enumerate(valid_comment_indices[:target_count]):
                try:
                    comment_element = comment_locator.nth(comment_idx)
                    expected_comment_id = valid_comment_ids[idx] if idx < len(valid_comment_ids) else "unknown"
                    
                    # 获取父评论的一级评论文本用于日志，并验证元素是否正确
                    try:
                        # 获取评论ID用于确认
                        actual_comment_id = await comment_element.evaluate("el => el.querySelector('.comment-item')?.id || 'no-id'")
                        
                        primary_comment = comment_element.locator('.comment-item:not(.comment-item-sub)').first
                        primary_text = await primary_comment.inner_text()
                        content_lines = primary_text.split('\n')
                        main_content = next((line for line in content_lines if len(line.strip()) > 10), primary_text)
                        
                        # 简洁日志：只显示笔记ID、层数和内容摘要
                        utils.logger.info(f"[screenshot_comments_section] 📸 Note {note_id}: Layer {successful_screenshots+1}/{target_count} - {main_content[:50]}...")
                        
                        # 验证ID是否匹配
                        if expected_comment_id and actual_comment_id != expected_comment_id:
                            utils.logger.warning(f"[screenshot_comments_section] WARNING: Comment ID mismatch! Expected {expected_comment_id}, got {actual_comment_id}")
                    except Exception as e:
                        utils.logger.warning(f"[screenshot_comments_section] Failed to get comment info for index {comment_idx}: {e}")
                        pass
                    
                    # 统一滚动策略：所有层都使用相同的方式
                    await comment_element.scroll_into_view_if_needed()
                    await asyncio.sleep(1.0)  # 增加等待时间，让评论内容完全加载
                    
                    # 展开该父评论的二级评论（每个一级评论只点击一次展开按钮）
                    try:
                        # 统计展开前的二级评论数量
                        sub_comments_before = comment_element.locator('.comment-item-sub')
                        sub_count_before = await sub_comments_before.count()
                        
                        # 查找"展开回复"按钮（只在当前评论元素内查找）
                        # 使用class选择器最可靠，避免匹配到其他评论的按钮
                        show_more_selectors = [
                            '.show-more',           # 最精确的class选择器
                            '[class*="show-more"]', # 模糊匹配
                        ]
                        
                        button_clicked = False
                        for selector in show_more_selectors:
                            # 如果已经点击过按钮，直接跳出循环
                            if button_clicked:
                                break
                            
                            try:
                                # 在当前评论元素内查找展开按钮（限定在comment_element范围内）
                                show_more_button = comment_element.locator(selector).first
                                button_count = await show_more_button.count()
                                
                                if button_count > 0:
                                    if await show_more_button.is_visible(timeout=500):
                                        button_text = await show_more_button.inner_text()
                                        utils.logger.info(f"[screenshot_comments_section] Layer {successful_screenshots+1}: Found expand button '{button_text}' (clicking ONCE only)")
                                        
                                        # 点击按钮展开二级评论
                                        await show_more_button.click()
                                        button_clicked = True  # 标记已点击，防止重复点击
                                        await asyncio.sleep(2.5)  # 增加等待时间，确保二级评论完全加载
                                        
                                        # 统计展开后的数量
                                        sub_comments_after = comment_element.locator('.comment-item-sub')
                                        sub_count_after = await sub_comments_after.count()
                                        utils.logger.info(f"[screenshot_comments_section] Layer {successful_screenshots+1}: ✓ Expanded from {sub_count_before} to {sub_count_after} sub-comments (clicked once)")
                                        
                                        # 立即退出循环，确保只点击一次
                                        break
                            except Exception as e:
                                utils.logger.debug(f"[screenshot_comments_section] Selector '{selector}' failed: {e}")
                                continue
                        
                        # 如果没有找到展开按钮
                        if not button_clicked:
                            if sub_count_before > 0:
                                utils.logger.info(f"[screenshot_comments_section] Layer {successful_screenshots+1}: No expand button found, already showing {sub_count_before} sub-comments")
                            else:
                                utils.logger.debug(f"[screenshot_comments_section] Layer {successful_screenshots+1}: No sub-comments to expand")
                    except Exception as e:
                        utils.logger.warning(f"[screenshot_comments_section] Error expanding sub-comments: {e}")
                    
                    # 移除该层元素的margin和padding，让截图更紧凑
                    # 对第一层做特殊处理，使用clip截图去除顶部空白
                    is_first_layer = (successful_screenshots == 0)
                    
                    try:
                        if is_first_layer:
                            # 第一层：找到实际内容的起始位置，移除上方空白
                            await comment_element.evaluate("""
                                element => {
                                    element.style.margin = '0';
                                    element.style.padding = '10px';
                                    element.style.paddingTop = '0';  // 第一层不要顶部padding
                                }
                            """)
                        else:
                            # 其他层：正常设置
                            await comment_element.evaluate("""
                                element => {
                                    element.style.margin = '0';
                                    element.style.padding = '10px';
                                }
                            """)
                    except Exception as e:
                        utils.logger.debug(f"[screenshot_comments_section] Failed to adjust element style: {e}")
                    
                    # 等待评论内容（包括图片）完全加载
                    await asyncio.sleep(0.5)
                    
                    # 截取该层评论（包含展开的二级评论）
                    successful_screenshots += 1
                    # 文件名包含笔记ID，便于识别
                    layer_screenshot_path = os.path.join(temp_dir, f"layer_{successful_screenshots}_{note_id}.png")
                    
                    # 使用元素的screenshot方法
                    try:
                        # 获取元素的边界框信息
                        box = await comment_element.bounding_box()
                        if box:
                            utils.logger.info(f"[screenshot_comments_section] Layer {successful_screenshots} bounding box: x={box['x']:.0f}, y={box['y']:.0f}, width={box['width']:.0f}, height={box['height']:.0f}")
                            
                            # 如果是第一层且高度异常，输出详细结构信息
                            if is_first_layer and box['height'] > 5000:
                                utils.logger.warning(f"[screenshot_comments_section] First layer height is abnormally large: {box['height']:.0f}px")
                                # 获取元素的HTML结构用于调试
                                try:
                                    element_info = await comment_element.evaluate("""
                                        element => {
                                            return {
                                                tagName: element.tagName,
                                                className: element.className,
                                                childCount: element.children.length,
                                                innerHTML_preview: element.innerHTML.substring(0, 500),
                                                has_comment_item: !!element.querySelector('.comment-item'),
                                                has_reply_container: !!element.querySelector('.reply-container'),
                                                comment_items_count: element.querySelectorAll('.comment-item').length
                                            };
                                        }
                                    """)
                                    utils.logger.info(f"[screenshot_comments_section] First layer element info: {element_info}")
                                except Exception as e:
                                    utils.logger.debug(f"Failed to get element info: {e}")
                        
                        if is_first_layer:
                            # 第一层：使用clip参数，从实际内容开始截图
                            # 查找第一个真正的评论元素（.comment-item）的位置
                            try:
                                # 获取第一个 .comment-item 相对于 .parent-comment 的偏移
                                offset_info = await comment_element.evaluate("""
                                    element => {
                                        const firstCommentItem = element.querySelector('.comment-item:not(.comment-item-sub)');
                                        if (firstCommentItem) {
                                            const parentRect = element.getBoundingClientRect();
                                            const commentRect = firstCommentItem.getBoundingClientRect();
                                            
                                            // 进一步查找头像元素，确保从最顶部的可见内容开始
                                            const avatar = firstCommentItem.querySelector('.avatar');
                                            let offset = commentRect.top - parentRect.top;
                                            
                                            if (avatar) {
                                                const avatarRect = avatar.getBoundingClientRect();
                                                offset = Math.min(offset, avatarRect.top - parentRect.top);
                                            }
                                            
                                            return {
                                                offset: offset,
                                                commentTop: commentRect.top - parentRect.top,
                                                avatarTop: avatar ? avatar.getBoundingClientRect().top - parentRect.top : null
                                            };
                                        }
                                        return { offset: 0, commentTop: 0, avatarTop: null };
                                    }
                                """)
                                
                                first_comment_offset = offset_info['offset']
                                utils.logger.info(f"[screenshot_comments_section] First layer offset detection - comment: {offset_info['commentTop']}px, avatar: {offset_info['avatarTop']}px, final offset: {first_comment_offset}px")
                                
                                if first_comment_offset > 5 and box:  # 只有当空白超过5px时才裁剪
                                    # 使用page.screenshot + clip来精确截取
                                    utils.logger.info(f"[screenshot_comments_section] First layer: clipping top {first_comment_offset:.0f}px to remove whitespace")
                                    clip = {
                                        'x': box['x'],
                                        'y': box['y'] + first_comment_offset,
                                        'width': box['width'],
                                        'height': box['height'] - first_comment_offset
                                    }
                                    await self.playwright_page.screenshot(path=layer_screenshot_path, clip=clip, timeout=10000)
                                else:
                                    utils.logger.info(f"[screenshot_comments_section] First layer: offset too small ({first_comment_offset:.0f}px), using normal screenshot")
                                    await comment_element.screenshot(path=layer_screenshot_path, timeout=10000)
                            except Exception as clip_error:
                                utils.logger.warning(f"[screenshot_comments_section] Clip screenshot failed: {clip_error}, using normal screenshot")
                                await comment_element.screenshot(path=layer_screenshot_path, timeout=10000)
                        else:
                            # 其他层：正常截图
                            await comment_element.screenshot(path=layer_screenshot_path, timeout=10000)
                        
                        layer_screenshots.append(layer_screenshot_path)
                        utils.logger.info(f"[screenshot_comments_section] Layer {successful_screenshots}/{target_count} screenshot saved")
                    except Exception as screenshot_error:
                        utils.logger.error(f"[screenshot_comments_section] Failed to screenshot layer {successful_screenshots}: {screenshot_error}")
                        raise
                    
                except Exception as e:
                    utils.logger.warning(f"[screenshot_comments_section] Error screenshotting comment at index {comment_idx}: {e}")
                    continue
            
            if not layer_screenshots:
                utils.logger.error("[screenshot_comments_section] No layers were successfully screenshotted")
                return None
            
            utils.logger.info(f"[screenshot_comments_section] Successfully captured {len(layer_screenshots)} layers (target was {target_count}), now stitching...")
            
            # 如果截图数量不够，给出警告
            if len(layer_screenshots) < target_count:
                utils.logger.warning(f"[screenshot_comments_section] Only captured {len(layer_screenshots)} layers, expected {target_count}. Page may not have enough comments.")
            
            # 拼接所有层的截图成一张长图（不做任何裁剪）
            screenshot_success = False
            try:
                images = [Image.open(path) for path in layer_screenshots]
                
                # 直接使用原始图片，不做任何裁剪
                utils.logger.info(f"[screenshot_comments_section] Using original images without cropping")
                
                # 计算总高度和最大宽度
                total_height = sum(img.height for img in images)
                max_width = max(img.width for img in images)
                
                utils.logger.info(f"[screenshot_comments_section] Stitching {len(images)} images, total height: {total_height}px, max width: {max_width}px")
                
                # 创建新的长图
                stitched_image = Image.new('RGB', (max_width, total_height), (255, 255, 255))
                
                # 逐层粘贴
                current_y = 0
                for idx, img in enumerate(images):
                    stitched_image.paste(img, (0, current_y))
                    utils.logger.info(f"[screenshot_comments_section] Pasted layer {idx+1} at y={current_y}, height={img.height}px")
                    current_y += img.height
                
                # 保存拼接后的长图
                screenshot_filename = f"comments_{note_id}_{timestamp}.png"
                screenshot_path = os.path.join(screenshot_dir, screenshot_filename)
                stitched_image.save(screenshot_path, 'PNG')
                screenshot_success = True
                utils.logger.info(f"[screenshot_comments_section] Stitched long image saved: {screenshot_path}")
                
                # 清理临时文件
                for img in images:
                    img.close()
                
                # 调试模式：保留临时文件以便检查
                # 如果不需要调试，取消下面的注释即可删除临时文件
                # for path in layer_screenshots:
                #     try:
                #         os.remove(path)
                #     except:
                #         pass
                # utils.logger.info(f"[screenshot_comments_section] Temporary files cleaned up")
                
                utils.logger.info(f"[screenshot_comments_section] Temporary layer files kept in {temp_dir} for debugging")
                
            except Exception as e:
                utils.logger.error(f"[screenshot_comments_section] Error stitching images: {e}")
                import traceback
                traceback.print_exc()
                return None
            # ========== 逐层截图+拼接结束 ==========
            
            if not screenshot_success:
                utils.logger.error("[screenshot_comments_section] Screenshot stitching failed")
                return None
            
            if screenshot_success:
                utils.logger.info(f"[screenshot_comments_section] Screenshot saved: {screenshot_path}")
                return screenshot_path
            else:
                utils.logger.error("[screenshot_comments_section] Failed to take screenshot")
                return None
            
        except Exception as e:
            utils.logger.error(f"[screenshot_comments_section] Error: {e}")
            import traceback
            traceback.print_exc()
            return None

    async def get_creator_info(self, user_id: str) -> Dict:
        """
        通过解析网页版的用户主页HTML，获取用户个人简要信息
        PC端用户主页的网页存在window.__INITIAL_STATE__这个变量上的，解析它即可
        eg: https://www.xiaohongshu.com/user/profile/59d8cb33de5fb4696bf17217
        """
        uri = f"/user/profile/{user_id}"
        html_content = await self.request(
            "GET", self._domain + uri, return_response=True, headers=self.headers
        )
        return self._extractor.extract_creator_info_from_html(html_content)

    async def get_notes_by_creator(
        self,
        creator: str,
        cursor: str,
        page_size: int = 30,
    ) -> Dict:
        """
        获取博主的笔记
        Args:
            creator: 博主ID
            cursor: 上一页最后一条笔记的ID
            page_size: 分页数据长度

        Returns:

        """
        uri = "/api/sns/web/v1/user_posted"
        data = {
            "user_id": creator,
            "cursor": cursor,
            "num": page_size,
            "image_formats": "jpg,webp,avif",
        }
        return await self.get(uri, data)

    async def get_all_notes_by_creator(
        self,
        user_id: str,
        crawl_interval: float = 1.0,
        callback: Optional[Callable] = None,
    ) -> List[Dict]:
        """
        获取指定用户下的所有发过的帖子，该方法会一直查找一个用户下的所有帖子信息
        Args:
            user_id: 用户ID
            crawl_interval: 爬取一次的延迟单位（秒）
            callback: 一次分页爬取结束后的更新回调函数

        Returns:

        """
        result = []
        notes_has_more = True
        notes_cursor = ""
        while notes_has_more and len(result) < config.CRAWLER_MAX_NOTES_COUNT:
            notes_res = await self.get_notes_by_creator(user_id, notes_cursor)
            if not notes_res:
                utils.logger.error(
                    f"[XiaoHongShuClient.get_notes_by_creator] The current creator may have been banned by xhs, so they cannot access the data."
                )
                break

            notes_has_more = notes_res.get("has_more", False)
            notes_cursor = notes_res.get("cursor", "")
            if "notes" not in notes_res:
                utils.logger.info(
                    f"[XiaoHongShuClient.get_all_notes_by_creator] No 'notes' key found in response: {notes_res}"
                )
                break

            notes = notes_res["notes"]
            utils.logger.info(
                f"[XiaoHongShuClient.get_all_notes_by_creator] got user_id:{user_id} notes len : {len(notes)}"
            )

            remaining = config.CRAWLER_MAX_NOTES_COUNT - len(result)
            if remaining <= 0:
                break

            notes_to_add = notes[:remaining]
            if callback:
                await callback(notes_to_add)

            result.extend(notes_to_add)
            await asyncio.sleep(crawl_interval)

        utils.logger.info(
            f"[XiaoHongShuClient.get_all_notes_by_creator] Finished getting notes for user {user_id}, total: {len(result)}"
        )
        return result

    async def get_note_short_url(self, note_id: str) -> Dict:
        """
        获取笔记的短链接
        Args:
            note_id: 笔记ID

        Returns:

        """
        uri = f"/api/sns/web/short_url"
        data = {"original_url": f"{self._domain}/discovery/item/{note_id}"}
        return await self.post(uri, data=data, return_response=True)

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(1))
    async def get_note_by_id_from_html(
        self,
        note_id: str,
        xsec_source: str,
        xsec_token: str,
        enable_cookie: bool = False,
    ) -> Optional[Dict]:
        """
        通过解析网页版的笔记详情页HTML，获取笔记详情, 该接口可能会出现失败的情况，这里尝试重试3次
        copy from https://github.com/ReaJason/xhs/blob/eb1c5a0213f6fbb592f0a2897ee552847c69ea2d/xhs/core.py#L217-L259
        thanks for ReaJason
        Args:
            note_id:
            xsec_source:
            xsec_token:
            enable_cookie:

        Returns:

        """
        url = (
            "https://www.xiaohongshu.com/explore/"
            + note_id
            + f"?xsec_token={xsec_token}&xsec_source={xsec_source}"
        )
        copy_headers = self.headers.copy()
        if not enable_cookie:
            del copy_headers["Cookie"]

        html = await self.request(
            method="GET", url=url, return_response=True, headers=copy_headers
        )

        return self._extractor.extract_note_detail_from_html(note_id, html)