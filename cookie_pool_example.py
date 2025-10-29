#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Cookie池快速示例
演示如何使用Cookie池功能
"""

import asyncio
from tools.cookie_pool import CookiePool, CookieInfo
from tools import utils


async def example_basic_usage():
    """基础使用示例"""
    print("\n" + "="*60)
    print("示例1: 基础Cookie池使用")
    print("="*60)
    
    # 1. 创建Cookie池
    cookie_pool = CookiePool(platform="xhs", max_fail_count=3)
    
    # 2. 添加多个Cookie
    cookies_data = [
        {
            "account_id": "account_1",
            "cookie_str": "a1=xxx; webId=xxx; gid=xxx; ...",
        },
        {
            "account_id": "account_2", 
            "cookie_str": "a1=yyy; webId=yyy; gid=yyy; ...",
        },
        {
            "account_id": "account_3",
            "cookie_str": "a1=zzz; webId=zzz; gid=zzz; ...",
        }
    ]
    
    for cookie_data in cookies_data:
        cookie_dict = utils.convert_str_cookie_to_dict(cookie_data["cookie_str"])
        cookie_info = CookieInfo(
            account_id=cookie_data["account_id"],
            cookie_dict=cookie_dict,
            cookie_str=cookie_data["cookie_str"],
        )
        cookie_pool.add_cookie(cookie_info)
    
    # 3. 保存到文件
    cookie_pool.save_to_file()
    print(f"✅ 已添加 {len(cookie_pool.cookie_list)} 个Cookie")
    
    # 4. 获取当前Cookie
    current = cookie_pool.get_current_cookie()
    if current:
        print(f"📍 当前使用: {current.account_id}")
    
    # 5. 模拟切换
    print("\n模拟Cookie失败，切换到下一个...")
    next_cookie = cookie_pool.switch_to_next_cookie()
    if next_cookie:
        print(f"✅ 切换成功: {next_cookie.account_id}")
    
    # 6. 查看状态
    print(f"\n📊 Cookie池状态:")
    print(f"   总数: {len(cookie_pool.cookie_list)}")
    print(f"   有效: {cookie_pool.get_valid_cookie_count()}")


async def example_load_from_file():
    """从文件加载示例"""
    print("\n" + "="*60)
    print("示例2: 从文件加载Cookie池")
    print("="*60)
    
    # 1. 创建Cookie池并加载
    cookie_pool = CookiePool(platform="xhs")
    loaded = cookie_pool.load_from_file()
    
    if loaded:
        print(f"✅ 成功加载 {len(cookie_pool.cookie_list)} 个Cookie")
        
        # 2. 显示所有Cookie
        print("\n📋 Cookie列表:")
        for idx, cookie in enumerate(cookie_pool.cookie_list, 1):
            status = "✅" if cookie.is_valid else "❌"
            print(f"   {idx}. {cookie.account_id} {status} (失败: {cookie.fail_count}次)")
    else:
        print("⚠️  未找到Cookie池文件，请先运行示例1或使用管理工具添加Cookie")


async def example_cookie_rotation():
    """Cookie轮换示例"""
    print("\n" + "="*60)
    print("示例3: Cookie轮换机制")
    print("="*60)
    
    cookie_pool = CookiePool(platform="xhs", max_fail_count=2)
    
    # 添加测试Cookie
    for i in range(3):
        cookie_info = CookieInfo(
            account_id=f"test_account_{i+1}",
            cookie_dict={"a1": f"test_{i+1}"},
            cookie_str=f"a1=test_{i+1}",
        )
        cookie_pool.add_cookie(cookie_info)
    
    print(f"初始状态: {cookie_pool.get_valid_cookie_count()}/{len(cookie_pool.cookie_list)} 个有效Cookie\n")
    
    # 模拟多次失败和切换
    for round_num in range(5):
        print(f"--- 第 {round_num + 1} 轮 ---")
        current = cookie_pool.get_current_cookie()
        
        if not current:
            print("❌ 没有可用的Cookie了！")
            break
        
        print(f"使用: {current.account_id} (失败次数: {current.fail_count})")
        
        # 模拟失败
        next_cookie = cookie_pool.switch_to_next_cookie()
        if next_cookie:
            print(f"切换到: {next_cookie.account_id}")
        
        print(f"有效Cookie: {cookie_pool.get_valid_cookie_count()}/{len(cookie_pool.cookie_list)}\n")


async def example_reset_cookies():
    """重置Cookie状态示例"""
    print("\n" + "="*60)
    print("示例4: 重置Cookie状态")
    print("="*60)
    
    cookie_pool = CookiePool(platform="xhs")
    cookie_pool.load_from_file()
    
    if not cookie_pool.cookie_list:
        print("⚠️  Cookie池为空")
        return
    
    print(f"重置前: {cookie_pool.get_valid_cookie_count()}/{len(cookie_pool.cookie_list)} 个有效")
    
    # 重置所有Cookie
    cookie_pool.reset_all_cookies()
    cookie_pool.save_to_file()
    
    print(f"重置后: {cookie_pool.get_valid_cookie_count()}/{len(cookie_pool.cookie_list)} 个有效")
    print("✅ 所有Cookie已重置为有效状态")


async def main():
    """主函数"""
    print("\n🎯 Cookie池功能示例")
    print("="*60)
    
    while True:
        print("\n请选择要运行的示例:")
        print("1. 基础使用（创建和添加Cookie）")
        print("2. 从文件加载Cookie池")
        print("3. Cookie轮换机制演示")
        print("4. 重置Cookie状态")
        print("0. 退出")
        
        choice = input("\n请输入选项 (0-4): ").strip()
        
        if choice == '0':
            print("\n👋 再见！")
            break
        elif choice == '1':
            await example_basic_usage()
        elif choice == '2':
            await example_load_from_file()
        elif choice == '3':
            await example_cookie_rotation()
        elif choice == '4':
            await example_reset_cookies()
        else:
            print("❌ 无效的选项")
        
        input("\n按回车键继续...")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n👋 程序已退出")
    except Exception as e:
        print(f"\n❌ 发生错误: {e}")
        import traceback
        traceback.print_exc()
