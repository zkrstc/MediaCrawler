# -*- coding: utf-8 -*-
"""
Cookie自动刷新工具
用于定期更新Cookie，防止过期
"""

import asyncio
from typing import Optional
from playwright.async_api import BrowserContext
from tools import utils


class CookieRefresher:
    """Cookie自动刷新器"""
    
    def __init__(
        self,
        browser_context: BrowserContext,
        client,
        refresh_interval: int = 1800  # 默认30分钟刷新一次
    ):
        """
        初始化Cookie刷新器
        
        Args:
            browser_context: 浏览器上下文
            client: API客户端（需要有update_cookies方法）
            refresh_interval: 刷新间隔（秒）
        """
        self.browser_context = browser_context
        self.client = client
        self.refresh_interval = refresh_interval
        self._task: Optional[asyncio.Task] = None
        self._running = False
    
    async def start(self):
        """启动自动刷新"""
        if self._running:
            utils.logger.warning("[CookieRefresher] Already running")
            return
        
        self._running = True
        self._task = asyncio.create_task(self._refresh_loop())
        utils.logger.info(f"[CookieRefresher] Started (interval: {self.refresh_interval}s)")
    
    async def stop(self):
        """停止自动刷新"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        utils.logger.info("[CookieRefresher] Stopped")
    
    async def _refresh_loop(self):
        """刷新循环"""
        while self._running:
            try:
                await asyncio.sleep(self.refresh_interval)
                
                if not self._running:
                    break
                
                # 刷新Cookie
                await self.refresh_now()
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                utils.logger.error(f"[CookieRefresher] Error in refresh loop: {e}")
    
    async def refresh_now(self):
        """立即刷新Cookie"""
        try:
            utils.logger.info("[CookieRefresher] Refreshing cookies...")
            
            # 从浏览器上下文更新Cookie
            await self.client.update_cookies(self.browser_context)
            
            utils.logger.info("[CookieRefresher] Cookies refreshed successfully")
            
        except Exception as e:
            utils.logger.error(f"[CookieRefresher] Failed to refresh cookies: {e}")


async def create_cookie_refresher(
    browser_context: BrowserContext,
    client,
    refresh_interval: int = 1800,
    auto_start: bool = True
) -> CookieRefresher:
    """
    创建Cookie刷新器
    
    Args:
        browser_context: 浏览器上下文
        client: API客户端
        refresh_interval: 刷新间隔（秒）
        auto_start: 是否自动启动
    
    Returns:
        CookieRefresher实例
    """
    refresher = CookieRefresher(browser_context, client, refresh_interval)
    
    if auto_start:
        await refresher.start()
    
    return refresher
