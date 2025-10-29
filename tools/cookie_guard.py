# -*- coding: utf-8 -*-
"""
Cookie守护装饰器
自动检测Cookie被封并切换
"""

import functools
from typing import Callable, Any
from tools import utils
import config


class CookieBlockedException(Exception):
    """Cookie被封锁异常"""
    pass


def detect_cookie_blocked(response_data: Any) -> bool:
    """
    检测响应是否表明Cookie被封
    
    Args:
        response_data: API响应数据
    
    Returns:
        是否被封
    """
    if not response_data:
        return False
    
    # 检测常见的封禁标志
    if isinstance(response_data, dict):
        # 小红书封禁标志
        if response_data.get("code") in [-100, -101, -102, 300012]:
            return True
        
        # 通用封禁关键词
        msg = str(response_data.get("msg", "")).lower()
        error_keywords = [
            "账号异常", "account blocked", "banned", 
            "封禁", "限制", "restricted",
            "验证失败", "authentication failed",
            "登录失效", "login expired",
            "需要登录", "need login"
        ]
        
        for keyword in error_keywords:
            if keyword in msg:
                return True
    
    return False


def cookie_guard(cookie_pool_manager=None):
    """
    Cookie守护装饰器
    自动检测Cookie被封并切换到新Cookie
    
    使用方法:
        @cookie_guard(cookie_pool_manager=self.cookie_pool_manager)
        async def get_data(self):
            return await self.client.get_note_by_id(note_id)
    
    Args:
        cookie_pool_manager: Cookie池管理器实例
    """
    def decorator(func: Callable):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            max_retry = 3  # 最多重试3次
            retry_count = 0
            
            while retry_count < max_retry:
                try:
                    # 执行原函数
                    result = await func(*args, **kwargs)
                    
                    # 检测响应是否表明Cookie被封
                    if detect_cookie_blocked(result):
                        utils.logger.warning(
                            f"[CookieGuard] Cookie blocked detected in {func.__name__}"
                        )
                        raise CookieBlockedException("Cookie is blocked")
                    
                    # 成功返回
                    return result
                    
                except CookieBlockedException as e:
                    retry_count += 1
                    utils.logger.warning(
                        f"[CookieGuard] Attempt {retry_count}/{max_retry}: {e}"
                    )
                    
                    # 如果有Cookie池管理器，尝试切换Cookie
                    if cookie_pool_manager and config.ENABLE_COOKIE_AUTO_SWITCH:
                        switched = await cookie_pool_manager.handle_cookie_blocked()
                        
                        if not switched:
                            utils.logger.error(
                                f"[CookieGuard] Failed to switch cookie, giving up"
                            )
                            raise
                        
                        # 切换成功，继续重试
                        utils.logger.info(
                            f"[CookieGuard] Cookie switched, retrying {func.__name__}..."
                        )
                        continue
                    else:
                        # 没有Cookie池，直接抛出异常
                        utils.logger.error(
                            f"[CookieGuard] Cookie pool not available, cannot switch"
                        )
                        raise
                
                except Exception as e:
                    # 其他异常直接抛出
                    utils.logger.error(f"[CookieGuard] Error in {func.__name__}: {e}")
                    raise
            
            # 重试次数用完
            raise Exception(f"[CookieGuard] Max retry attempts ({max_retry}) reached")
        
        return wrapper
    return decorator


def with_cookie_rotation(interval: int = 10):
    """
    Cookie轮换装饰器
    每隔N次请求自动轮换Cookie（主动轮换，不等被封）
    
    使用方法:
        @with_cookie_rotation(interval=10)
        async def get_data(self):
            return await self.client.get_note_by_id(note_id)
    
    Args:
        interval: 轮换间隔（请求次数）
    """
    request_count = {"count": 0}
    
    def decorator(func: Callable):
        @functools.wraps(func)
        async def wrapper(self, *args, **kwargs):
            # 执行原函数
            result = await func(self, *args, **kwargs)
            
            # 增加请求计数
            request_count["count"] += 1
            
            # 检查是否需要轮换
            if request_count["count"] >= interval:
                request_count["count"] = 0
                
                # 如果有Cookie池管理器，主动切换
                if (hasattr(self, 'cookie_pool_manager') and 
                    self.cookie_pool_manager and 
                    config.ENABLE_COOKIE_POOL):
                    
                    utils.logger.info(
                        f"[CookieRotation] Proactively rotating cookie after {interval} requests"
                    )
                    
                    next_cookie = self.cookie_pool_manager.cookie_pool.switch_to_next_cookie()
                    if next_cookie:
                        await self.cookie_pool_manager._apply_cookie(next_cookie)
                        utils.logger.info("[CookieRotation] Cookie rotated successfully")
            
            return result
        
        return wrapper
    return decorator


class CookieHealthMonitor:
    """Cookie健康监控器"""
    
    def __init__(self, cookie_pool_manager):
        self.cookie_pool_manager = cookie_pool_manager
        self.success_count = 0
        self.fail_count = 0
        self.total_requests = 0
    
    def record_success(self):
        """记录成功请求"""
        self.success_count += 1
        self.total_requests += 1
        self.cookie_pool_manager.cookie_pool.mark_current_success()
    
    def record_failure(self):
        """记录失败请求"""
        self.fail_count += 1
        self.total_requests += 1
    
    def get_success_rate(self) -> float:
        """获取成功率"""
        if self.total_requests == 0:
            return 0.0
        return self.success_count / self.total_requests
    
    def should_switch_cookie(self, threshold: float = 0.5) -> bool:
        """
        判断是否应该切换Cookie
        
        Args:
            threshold: 成功率阈值，低于此值时建议切换
        
        Returns:
            是否应该切换
        """
        if self.total_requests < 10:  # 样本太少，不判断
            return False
        
        success_rate = self.get_success_rate()
        return success_rate < threshold
    
    def reset(self):
        """重置统计"""
        self.success_count = 0
        self.fail_count = 0
        self.total_requests = 0
    
    def get_stats(self) -> dict:
        """获取统计信息"""
        return {
            "total_requests": self.total_requests,
            "success_count": self.success_count,
            "fail_count": self.fail_count,
            "success_rate": self.get_success_rate()
        }
