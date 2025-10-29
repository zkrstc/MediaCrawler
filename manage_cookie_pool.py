#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Cookie池管理工具
用于添加、查看、删除Cookie池中的账号Cookie
"""

import asyncio
import json
import os
import sys
from typing import Optional

from tools.cookie_pool import CookiePool, CookieInfo
from tools import utils


class CookiePoolCLI:
    """Cookie池命令行管理工具"""
    
    def __init__(self, platform: str = "xhs"):
        self.platform = platform
        self.cookie_pool = CookiePool(platform=platform)
        self.cookie_pool.load_from_file()
    
    def show_menu(self):
        """显示主菜单"""
        print("\n" + "="*50)
        print(f"  Cookie池管理工具 - {self.platform.upper()}")
        print("="*50)
        print("1. 查看Cookie池状态")
        print("2. 添加新Cookie")
        print("3. 删除Cookie")
        print("4. 重置所有Cookie状态")
        print("5. 测试Cookie有效性")
        print("0. 退出")
        print("="*50)
    
    def show_pool_status(self):
        """显示Cookie池状态"""
        print("\n" + "-"*50)
        print("Cookie池状态:")
        print("-"*50)
        
        if not self.cookie_pool.cookie_list:
            print("⚠️  Cookie池为空，请先添加Cookie")
            return
        
        print(f"总数: {len(self.cookie_pool.cookie_list)}")
        print(f"有效: {self.cookie_pool.get_valid_cookie_count()}")
        print(f"当前使用: #{self.cookie_pool.current_index + 1}")
        print("\n账号列表:")
        
        for idx, cookie in enumerate(self.cookie_pool.cookie_list):
            status = "✅ 有效" if cookie.is_valid else "❌ 无效"
            current = " [当前]" if idx == self.cookie_pool.current_index else ""
            print(f"  {idx + 1}. {cookie.account_id} - {status} (失败次数: {cookie.fail_count}){current}")
        
        print("-"*50)
    
    def add_cookie(self):
        """添加新Cookie"""
        print("\n" + "-"*50)
        print("添加新Cookie")
        print("-"*50)
        
        account_id = input("请输入账号ID（用于标识，如: account_1）: ").strip()
        if not account_id:
            print("❌ 账号ID不能为空")
            return
        
        # 检查是否已存在
        for cookie in self.cookie_pool.cookie_list:
            if cookie.account_id == account_id:
                print(f"❌ 账号 {account_id} 已存在")
                return
        
        print("\n请输入Cookie字符串（格式: key1=value1; key2=value2; ...）")
        print("提示: 可以从浏览器开发者工具中复制完整的Cookie")
        cookie_str = input("Cookie: ").strip()
        
        if not cookie_str:
            print("❌ Cookie不能为空")
            return
        
        # 解析Cookie
        try:
            cookie_dict = utils.convert_str_cookie_to_dict(cookie_str)
            if not cookie_dict:
                print("❌ Cookie格式错误")
                return
        except Exception as e:
            print(f"❌ Cookie解析失败: {e}")
            return
        
        # 创建CookieInfo
        cookie_info = CookieInfo(
            account_id=account_id,
            cookie_dict=cookie_dict,
            cookie_str=cookie_str,
            is_valid=True,
            fail_count=0
        )
        
        # 添加到池中
        self.cookie_pool.add_cookie(cookie_info)
        self.cookie_pool.save_to_file()
        
        print(f"✅ 成功添加Cookie: {account_id}")
    
    def delete_cookie(self):
        """删除Cookie"""
        print("\n" + "-"*50)
        print("删除Cookie")
        print("-"*50)
        
        if not self.cookie_pool.cookie_list:
            print("⚠️  Cookie池为空")
            return
        
        self.show_pool_status()
        
        try:
            index = int(input("\n请输入要删除的Cookie编号: ").strip())
            if index < 1 or index > len(self.cookie_pool.cookie_list):
                print("❌ 无效的编号")
                return
            
            cookie = self.cookie_pool.cookie_list[index - 1]
            confirm = input(f"确认删除 {cookie.account_id}? (y/n): ").strip().lower()
            
            if confirm == 'y':
                self.cookie_pool.cookie_list.pop(index - 1)
                # 调整current_index
                if self.cookie_pool.current_index >= index - 1:
                    self.cookie_pool.current_index = max(0, self.cookie_pool.current_index - 1)
                
                self.cookie_pool.save_to_file()
                print(f"✅ 已删除Cookie: {cookie.account_id}")
            else:
                print("❌ 取消删除")
                
        except ValueError:
            print("❌ 请输入有效的数字")
    
    def reset_cookies(self):
        """重置所有Cookie状态"""
        print("\n" + "-"*50)
        print("重置所有Cookie状态")
        print("-"*50)
        
        if not self.cookie_pool.cookie_list:
            print("⚠️  Cookie池为空")
            return
        
        confirm = input("确认重置所有Cookie状态为有效? (y/n): ").strip().lower()
        
        if confirm == 'y':
            self.cookie_pool.reset_all_cookies()
            self.cookie_pool.save_to_file()
            print("✅ 已重置所有Cookie状态")
        else:
            print("❌ 取消重置")
    
    async def test_cookie(self):
        """测试Cookie有效性"""
        print("\n" + "-"*50)
        print("测试Cookie有效性")
        print("-"*50)
        print("⚠️  此功能需要启动浏览器，暂未实现")
        print("建议直接运行爬虫程序测试Cookie")
        print("-"*50)
    
    def run(self):
        """运行CLI"""
        while True:
            self.show_menu()
            choice = input("\n请选择操作 (0-5): ").strip()
            
            if choice == '0':
                print("\n👋 再见！")
                break
            elif choice == '1':
                self.show_pool_status()
            elif choice == '2':
                self.add_cookie()
            elif choice == '3':
                self.delete_cookie()
            elif choice == '4':
                self.reset_cookies()
            elif choice == '5':
                asyncio.run(self.test_cookie())
            else:
                print("❌ 无效的选择，请重新输入")
            
            input("\n按回车键继续...")


def main():
    """主函数"""
    print("\n欢迎使用Cookie池管理工具！")
    
    # 选择平台
    print("\n支持的平台:")
    print("1. xhs (小红书)")
    print("2. dy (抖音)")
    print("3. ks (快手)")
    print("4. bili (B站)")
    print("5. wb (微博)")
    print("6. tieba (贴吧)")
    print("7. zhihu (知乎)")
    
    platform_map = {
        '1': 'xhs',
        '2': 'dy',
        '3': 'ks',
        '4': 'bili',
        '5': 'wb',
        '6': 'tieba',
        '7': 'zhihu'
    }
    
    choice = input("\n请选择平台 (1-7, 默认为1): ").strip() or '1'
    platform = platform_map.get(choice, 'xhs')
    
    # 创建CLI实例并运行
    cli = CookiePoolCLI(platform=platform)
    cli.run()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n👋 程序已退出")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ 发生错误: {e}")
        sys.exit(1)
