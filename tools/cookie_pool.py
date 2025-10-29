# -*- coding: utf-8 -*-
"""
Cookie池管理工具
用于管理多个账号的Cookie，当一个Cookie被封时自动切换到下一个
"""

import asyncio
import json
import os
from typing import Dict, List, Optional
from playwright.async_api import BrowserContext, Browser, Playwright
from tools import utils


class CookieInfo:
    """Cookie信息模型"""
    
    def __init__(
        self,
        account_id: str,
        cookie_dict: Dict[str, str],
        cookie_str: str,
        is_valid: bool = True,
        fail_count: int = 0,
        storage_state_path: Optional[str] = None
    ):
        self.account_id = account_id
        self.cookie_dict = cookie_dict
        self.cookie_str = cookie_str
        self.is_valid = is_valid
        self.fail_count = fail_count
        self.storage_state_path = storage_state_path
        self.last_used_time = None
    
    def mark_invalid(self):
        """标记Cookie为无效"""
        self.is_valid = False
        self.fail_count += 1
    
    def mark_valid(self):
        """标记Cookie为有效"""
        self.is_valid = True
        self.fail_count = 0
    
    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            "account_id": self.account_id,
            "cookie_dict": self.cookie_dict,
            "cookie_str": self.cookie_str,
            "is_valid": self.is_valid,
            "fail_count": self.fail_count,
            "storage_state_path": self.storage_state_path
        }


class CookiePool:
    """Cookie池管理器"""
    
    def __init__(
        self,
        platform: str = "xhs",
        max_fail_count: int = 3,
        cookie_pool_dir: str = "cookie_pool"
    ):
        """
        初始化Cookie池
        
        Args:
            platform: 平台名称
            max_fail_count: 最大失败次数，超过后Cookie被标记为无效
            cookie_pool_dir: Cookie池存储目录
        """
        self.platform = platform
        self.max_fail_count = max_fail_count
        self.cookie_pool_dir = cookie_pool_dir
        self.cookie_list: List[CookieInfo] = []
        self.current_index = 0
        
        # 创建Cookie池目录
        os.makedirs(cookie_pool_dir, exist_ok=True)
        self.pool_file = os.path.join(cookie_pool_dir, f"{platform}_cookie_pool.json")
    
    def add_cookie(self, cookie_info: CookieInfo):
        """添加Cookie到池中"""
        self.cookie_list.append(cookie_info)
        utils.logger.info(f"[CookiePool] Added cookie for account: {cookie_info.account_id}")
    
    def get_current_cookie(self) -> Optional[CookieInfo]:
        """获取当前Cookie"""
        if not self.cookie_list:
            utils.logger.error("[CookiePool] Cookie pool is empty!")
            return None
        
        # 找到第一个有效的Cookie
        for i in range(len(self.cookie_list)):
            idx = (self.current_index + i) % len(self.cookie_list)
            cookie = self.cookie_list[idx]
            if cookie.is_valid:
                self.current_index = idx
                return cookie
        
        utils.logger.error("[CookiePool] No valid cookie available!")
        return None
    
    def switch_to_next_cookie(self) -> Optional[CookieInfo]:
        """切换到下一个Cookie"""
        if not self.cookie_list:
            return None
        
        # 标记当前Cookie为失败
        current_cookie = self.cookie_list[self.current_index]
        current_cookie.fail_count += 1
        
        if current_cookie.fail_count >= self.max_fail_count:
            current_cookie.mark_invalid()
            utils.logger.warning(
                f"[CookiePool] Cookie {current_cookie.account_id} marked as invalid "
                f"(fail count: {current_cookie.fail_count})"
            )
        
        # 切换到下一个
        start_index = self.current_index
        for i in range(1, len(self.cookie_list) + 1):
            next_index = (start_index + i) % len(self.cookie_list)
            next_cookie = self.cookie_list[next_index]
            
            if next_cookie.is_valid:
                self.current_index = next_index
                utils.logger.info(
                    f"[CookiePool] Switched to cookie: {next_cookie.account_id} "
                    f"({next_index + 1}/{len(self.cookie_list)})"
                )
                return next_cookie
        
        utils.logger.error("[CookiePool] All cookies are invalid!")
        return None
    
    def get_next_cookie(self) -> Optional[CookieInfo]:
        """主动轮换到下一个Cookie（不标记失败）"""
        if not self.cookie_list:
            return None
        
        # 轮换到下一个有效Cookie
        start_index = self.current_index
        for i in range(1, len(self.cookie_list) + 1):
            next_index = (start_index + i) % len(self.cookie_list)
            next_cookie = self.cookie_list[next_index]
            
            if next_cookie.is_valid:
                self.current_index = next_index
                utils.logger.info(
                    f"[CookiePool] Rotating to cookie: {next_cookie.account_id} "
                    f"({next_index + 1}/{len(self.cookie_list)})"
                )
                return next_cookie
        
        utils.logger.error("[CookiePool] No valid cookies available!")
        return None
    
    def mark_current_success(self):
        """标记当前Cookie使用成功"""
        if self.cookie_list:
            current_cookie = self.cookie_list[self.current_index]
            current_cookie.mark_valid()
    
    def get_valid_cookie_count(self) -> int:
        """获取有效Cookie数量"""
        return sum(1 for cookie in self.cookie_list if cookie.is_valid)
    
    def save_to_file(self):
        """保存Cookie池到文件"""
        try:
            data = {
                "platform": self.platform,
                "current_index": self.current_index,
                "cookies": [cookie.to_dict() for cookie in self.cookie_list]
            }
            
            with open(self.pool_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            utils.logger.info(f"[CookiePool] Saved cookie pool to {self.pool_file}")
        except Exception as e:
            utils.logger.error(f"[CookiePool] Failed to save cookie pool: {e}")
    
    def load_from_file(self) -> bool:
        """从文件加载Cookie池"""
        try:
            if not os.path.exists(self.pool_file):
                utils.logger.warning(f"[CookiePool] Cookie pool file not found: {self.pool_file}")
                return False
            
            with open(self.pool_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            self.platform = data.get("platform", self.platform)
            self.current_index = data.get("current_index", 0)
            
            self.cookie_list = []
            for cookie_data in data.get("cookies", []):
                cookie_info = CookieInfo(
                    account_id=cookie_data["account_id"],
                    cookie_dict=cookie_data["cookie_dict"],
                    cookie_str=cookie_data["cookie_str"],
                    is_valid=cookie_data.get("is_valid", True),
                    fail_count=cookie_data.get("fail_count", 0),
                    storage_state_path=cookie_data.get("storage_state_path")
                )
                self.cookie_list.append(cookie_info)
            
            utils.logger.info(
                f"[CookiePool] Loaded {len(self.cookie_list)} cookies from {self.pool_file}"
            )
            return True
        except Exception as e:
            utils.logger.error(f"[CookiePool] Failed to load cookie pool: {e}")
            return False
    
    def reset_all_cookies(self):
        """重置所有Cookie状态"""
        for cookie in self.cookie_list:
            cookie.mark_valid()
        utils.logger.info("[CookiePool] Reset all cookies to valid state")


class CookiePoolManager:
    """Cookie池管理器（集成到爬虫中）"""
    
    def __init__(
        self,
        platform: str,
        client,
        browser_context: BrowserContext,
        enable_auto_switch: bool = True
    ):
        """
        初始化Cookie池管理器
        
        Args:
            platform: 平台名称
            client: API客户端
            browser_context: 浏览器上下文
            enable_auto_switch: 是否启用自动切换
        """
        self.platform = platform
        self.client = client
        self.browser_context = browser_context
        self.enable_auto_switch = enable_auto_switch
        self.cookie_pool = CookiePool(platform=platform)
        
        # 加载已有的Cookie池
        self.cookie_pool.load_from_file()
    
    async def handle_cookie_blocked(self) -> bool:
        """
        处理Cookie被封锁的情况
        
        Returns:
            是否成功切换到新Cookie
        """
        if not self.enable_auto_switch:
            utils.logger.error("[CookiePoolManager] Auto switch is disabled")
            return False
        
        utils.logger.warning("[CookiePoolManager] 🚫 Cookie blocked detected, switching to next cookie...")
        
        # 切换到下一个Cookie
        next_cookie = self.cookie_pool.switch_to_next_cookie()
        
        if not next_cookie:
            utils.logger.error("[CookiePoolManager] ❌ No available cookie to switch!")
            return False
        
        # 应用新Cookie
        try:
            await self._apply_cookie(next_cookie)
            
            # 验证新Cookie是否有效
            if hasattr(self.client, 'pong'):
                is_valid = await self.client.pong()
                if is_valid:
                    self.cookie_pool.mark_current_success()
                    utils.logger.info("[CookiePoolManager] ✅ Successfully switched to new cookie")
                    self.cookie_pool.save_to_file()
                    return True
                else:
                    utils.logger.warning("[CookiePoolManager] ⚠️ New cookie validation failed")
                    return await self.handle_cookie_blocked()  # 递归尝试下一个
            else:
                # 如果没有pong方法，假设切换成功
                self.cookie_pool.mark_current_success()
                self.cookie_pool.save_to_file()
                return True
                
        except Exception as e:
            utils.logger.error(f"[CookiePoolManager] Failed to apply new cookie: {e}")
            return False
    
    async def _apply_cookie(self, cookie_info: CookieInfo):
        """应用Cookie到浏览器和客户端"""
        # 1. 清除现有Cookie
        await self.browser_context.clear_cookies()
        
        # 2. 如果有storage_state，加载它
        if cookie_info.storage_state_path and os.path.exists(cookie_info.storage_state_path):
            # 需要重新创建context（Playwright限制）
            utils.logger.info(f"[CookiePoolManager] Loading storage state from {cookie_info.storage_state_path}")
        
        # 3. 添加新Cookie到浏览器
        for key, value in cookie_info.cookie_dict.items():
            await self.browser_context.add_cookies([{
                'name': key,
                'value': value,
                'domain': self._get_domain_for_platform(),
                'path': "/"
            }])
        
        # 4. 更新客户端的Cookie
        self.client.headers["Cookie"] = cookie_info.cookie_str
        self.client.cookie_dict = cookie_info.cookie_dict
        
        # 5. 刷新页面以重新初始化签名环境（关键！）
        # 切换Cookie后必须刷新页面，让浏览器重新加载localStorage和签名函数
        try:
            page = self.browser_context.pages[0] if self.browser_context.pages else None
            if page:
                utils.logger.info(f"[CookiePoolManager] Reloading page to reinitialize signature environment...")
                
                # 方案1: 先尝试简单刷新
                await page.reload(wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(3000)  # 等待3秒让JS执行
                
                # 检查签名函数
                signature_loaded = await page.evaluate("typeof window._webmsxyw === 'function'")
                
                if not signature_loaded:
                    utils.logger.warning(f"[CookiePoolManager] ⚠️ Signature function not loaded, trying full page navigation...")
                    # 方案2: 完全重新导航到首页
                    await page.goto("https://www.xiaohongshu.com/explore", wait_until="domcontentloaded", timeout=60000)
                    await page.wait_for_timeout(5000)  # 增加等待时间到5秒
                    signature_loaded = await page.evaluate("typeof window._webmsxyw === 'function'")
                
                if signature_loaded:
                    utils.logger.info(f"[CookiePoolManager] ✅ Signature function loaded successfully")
                else:
                    utils.logger.warning(f"[CookiePoolManager] ⚠️ Signature function still not detected, API requests may fail")
                    
                utils.logger.info(f"[CookiePoolManager] Page reloaded successfully")
        except Exception as e:
            utils.logger.warning(f"[CookiePoolManager] Failed to reload page after cookie switch: {e}")
        
        utils.logger.info(f"[CookiePoolManager] Applied cookie for account: {cookie_info.account_id}")
    
    def _get_domain_for_platform(self) -> str:
        """获取平台对应的域名"""
        domain_map = {
            "xhs": ".xiaohongshu.com",
            "dy": ".douyin.com",
            "ks": ".kuaishou.com",
            "bili": ".bilibili.com",
            "wb": ".weibo.com",
            "tieba": ".baidu.com",
            "zhihu": ".zhihu.com"
        }
        return domain_map.get(self.platform, ".example.com")
    
    def add_account_cookie(self, account_id: str, cookie_str: str, storage_state_path: Optional[str] = None):
        """添加账号Cookie到池中"""
        cookie_dict = utils.convert_str_cookie_to_dict(cookie_str)
        cookie_info = CookieInfo(
            account_id=account_id,
            cookie_dict=cookie_dict,
            cookie_str=cookie_str,
            storage_state_path=storage_state_path
        )
        self.cookie_pool.add_cookie(cookie_info)
        self.cookie_pool.save_to_file()
    
    def get_pool_status(self) -> Dict:
        """获取Cookie池状态"""
        return {
            "total": len(self.cookie_pool.cookie_list),
            "valid": self.cookie_pool.get_valid_cookie_count(),
            "current": self.cookie_pool.current_index,
            "current_account": self.cookie_pool.cookie_list[self.cookie_pool.current_index].account_id if self.cookie_pool.cookie_list else None
        }


async def create_cookie_pool_manager(
    platform: str,
    client,
    browser_context: BrowserContext,
    enable_auto_switch: bool = True
) -> CookiePoolManager:
    """
    创建Cookie池管理器
    
    Args:
        platform: 平台名称
        client: API客户端
        browser_context: 浏览器上下文
        enable_auto_switch: 是否启用自动切换
    
    Returns:
        CookiePoolManager实例
    """
    manager = CookiePoolManager(
        platform=platform,
        client=client,
        browser_context=browser_context,
        enable_auto_switch=enable_auto_switch
    )
    
    utils.logger.info(
        f"[CookiePoolManager] Initialized with {manager.cookie_pool.get_valid_cookie_count()} valid cookies"
    )
    
    return manager
