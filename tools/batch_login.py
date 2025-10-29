# -*- coding: utf-8 -*-
"""
批量登录工具
用于批量登录多个账号并保存到Cookie池
"""

import asyncio
import os
import sys

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playwright.async_api import async_playwright
from tools.cookie_pool import CookiePool, CookieInfo
from tools import utils


async def batch_login_accounts(platform: str = "xhs", account_count: int = 3):
    """
    批量登录多个账号并保存Cookie
    
    Args:
        platform: 平台名称（xhs, dy, ks等）
        account_count: 要登录的账号数量
    """
    
    # 平台URL映射
    platform_urls = {
        "xhs": "https://www.xiaohongshu.com",
        "dy": "https://www.douyin.com",
        "ks": "https://www.kuaishou.com",
        "bili": "https://www.bilibili.com",
        "wb": "https://weibo.com",
        "tieba": "https://tieba.baidu.com",
        "zhihu": "https://www.zhihu.com"
    }
    
    if platform not in platform_urls:
        print(f"❌ 不支持的平台: {platform}")
        print(f"支持的平台: {', '.join(platform_urls.keys())}")
        return
    
    url = platform_urls[platform]
    cookie_pool = CookiePool(platform=platform)
    
    # 加载已有的Cookie池
    cookie_pool.load_from_file()
    existing_count = len(cookie_pool.cookie_list)
    
    print(f"\n{'='*60}")
    print(f"批量登录工具 - {platform.upper()}")
    print(f"{'='*60}")
    print(f"已有账号数: {existing_count}")
    print(f"计划新增: {account_count} 个账号")
    print(f"{'='*60}\n")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=['--start-maximized']
        )
        
        for i in range(account_count):
            account_id = f"account_{existing_count + i + 1}"
            
            print(f"\n{'='*60}")
            print(f"正在登录第 {i+1}/{account_count} 个账号")
            print(f"账号ID: {account_id}")
            print(f"{'='*60}\n")
            
            # 创建新的上下文（独立会话）
            context = await browser.new_context(
                viewport={'width': 1920, 'height': 1080}
            )
            page = await context.new_page()
            
            try:
                # 访问平台
                print(f"正在访问 {url} ...")
                await page.goto(url, wait_until="networkidle", timeout=30000)
                await asyncio.sleep(2)
                
                # 等待用户手动登录
                print(f"\n{'*'*60}")
                print(f"请在浏览器中完成登录操作：")
                print(f"1. 扫码登录 或 手机号登录")
                print(f"2. 确保登录成功（能看到个人主页）")
                print(f"3. 完成后在此按回车继续...")
                print(f"{'*'*60}\n")
                
                input("按回车继续...")
                
                # 等待页面稳定
                await asyncio.sleep(2)
                
                # 获取Cookie
                print("正在获取Cookie...")
                cookies = await context.cookies()
                cookie_str, cookie_dict = utils.convert_cookies(cookies)
                
                if not cookie_dict:
                    print(f"❌ 未能获取到Cookie，请确保已成功登录")
                    await context.close()
                    continue
                
                # 创建Cookie池目录
                os.makedirs("cookie_pool", exist_ok=True)
                
                # 保存storage state
                storage_path = f"cookie_pool/{platform}_{account_id}_state.json"
                await context.storage_state(path=storage_path)
                print(f"✅ 已保存浏览器状态到: {storage_path}")
                
                # 添加到Cookie池
                cookie_info = CookieInfo(
                    account_id=account_id,
                    cookie_dict=cookie_dict,
                    cookie_str=cookie_str,
                    storage_state_path=storage_path
                )
                cookie_pool.add_cookie(cookie_info)
                
                print(f"✅ 账号 {account_id} 登录成功并添加到Cookie池")
                
                # 显示Cookie信息（部分）
                if "web_session" in cookie_dict:
                    session = cookie_dict["web_session"]
                    print(f"   Session: {session[:20]}...{session[-10:]}")
                
            except Exception as e:
                print(f"❌ 登录失败: {e}")
            finally:
                await context.close()
            
            # 短暂延迟
            if i < account_count - 1:
                print("\n准备登录下一个账号...")
                await asyncio.sleep(2)
        
        await browser.close()
    
    # 保存Cookie池
    cookie_pool.save_to_file()
    
    print(f"\n{'='*60}")
    print(f"批量登录完成！")
    print(f"{'='*60}")
    print(f"总账号数: {len(cookie_pool.cookie_list)}")
    print(f"有效账号: {cookie_pool.get_valid_cookie_count()}")
    print(f"Cookie池文件: {cookie_pool.pool_file}")
    print(f"{'='*60}\n")


async def list_cookie_pool(platform: str = "xhs"):
    """查看Cookie池状态"""
    cookie_pool = CookiePool(platform=platform)
    
    if not cookie_pool.load_from_file():
        print(f"❌ 未找到 {platform} 的Cookie池")
        return
    
    print(f"\n{'='*60}")
    print(f"Cookie池状态 - {platform.upper()}")
    print(f"{'='*60}")
    print(f"总账号数: {len(cookie_pool.cookie_list)}")
    print(f"有效账号: {cookie_pool.get_valid_cookie_count()}")
    print(f"当前使用: {cookie_pool.current_index + 1}")
    print(f"{'='*60}\n")
    
    for i, cookie in enumerate(cookie_pool.cookie_list):
        status = "✅ 有效" if cookie.is_valid else "❌ 无效"
        print(f"{i+1}. {cookie.account_id}")
        print(f"   状态: {status}")
        print(f"   失败次数: {cookie.fail_count}")
        if cookie.storage_state_path:
            print(f"   状态文件: {cookie.storage_state_path}")
        print()


async def reset_cookie_pool(platform: str = "xhs"):
    """重置Cookie池（将所有Cookie标记为有效）"""
    cookie_pool = CookiePool(platform=platform)
    
    if not cookie_pool.load_from_file():
        print(f"❌ 未找到 {platform} 的Cookie池")
        return
    
    cookie_pool.reset_all_cookies()
    cookie_pool.save_to_file()
    
    print(f"✅ 已重置 {platform} Cookie池，所有Cookie已标记为有效")


def print_usage():
    """打印使用说明"""
    print("""
批量登录工具使用说明
==================

1. 批量登录账号：
   python tools/batch_login.py --action login --platform xhs --count 3

2. 查看Cookie池状态：
   python tools/batch_login.py --action list --platform xhs

3. 重置Cookie池：
   python tools/batch_login.py --action reset --platform xhs

参数说明：
  --action    操作类型 (login/list/reset)
  --platform  平台名称 (xhs/dy/ks/bili/wb/tieba/zhihu)
  --count     登录账号数量 (仅login时需要)

支持的平台：
  xhs    - 小红书
  dy     - 抖音
  ks     - 快手
  bili   - 哔哩哔哩
  wb     - 微博
  tieba  - 百度贴吧
  zhihu  - 知乎
""")


async def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description="批量登录工具")
    parser.add_argument("--action", type=str, default="login", 
                       choices=["login", "list", "reset"],
                       help="操作类型")
    parser.add_argument("--platform", type=str, default="xhs",
                       help="平台名称")
    parser.add_argument("--count", type=int, default=3,
                       help="登录账号数量")
    
    args = parser.parse_args()
    
    if args.action == "login":
        await batch_login_accounts(
            platform=args.platform,
            account_count=args.count
        )
    elif args.action == "list":
        await list_cookie_pool(platform=args.platform)
    elif args.action == "reset":
        await reset_cookie_pool(platform=args.platform)
    else:
        print_usage()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n用户中断操作")
    except Exception as e:
        print(f"\n❌ 发生错误: {e}")
        import traceback
        traceback.print_exc()
