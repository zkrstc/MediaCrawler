# -*- coding: utf-8 -*-
"""
补全截图工具
用于检查并重新截图不完整的笔记
"""
import asyncio
import csv
import os
import sys
from datetime import datetime

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from tools import utils
from media_platform.xhs import XiaoHongShuCrawler


async def check_incomplete_screenshots():
    """
    检查所有笔记的截图完整性
    返回：需要重新截图的笔记列表
    """
    utils.logger.info("[CompleteScreenshots] Checking screenshot completeness...")
    
    crawler_type = config.CRAWLER_TYPE
    current_date = utils.get_current_date()
    
    # 读取 content.csv 获取所有笔记
    content_file = f"data/xhs/csv/{crawler_type}_contents_{current_date}.csv"
    if not os.path.exists(content_file):
        utils.logger.error(f"[CompleteScreenshots] Content file not found: {content_file}")
        return []
    
    # 读取 comments.csv 获取评论数量
    comments_file = f"data/xhs/csv/{crawler_type}_comments_{current_date}.csv"
    if not os.path.exists(comments_file):
        utils.logger.error(f"[CompleteScreenshots] Comments file not found: {comments_file}")
        return []
    
    # 统计每个笔记的一级评论数量
    note_comment_counts = {}
    with open(comments_file, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            note_id = row.get('note_id')
            parent_comment_id = row.get('parent_comment_id', '')
            
            # 只统计一级评论（parent_comment_id 为 '0' 或为空）
            if parent_comment_id == '0' or parent_comment_id == '' or not parent_comment_id:
                note_comment_counts[note_id] = note_comment_counts.get(note_id, 0) + 1
    
    # 检查截图完整性
    screenshot_dir = "data/xhs/screenshots"
    temp_base_dir = os.path.join(screenshot_dir, "temp")
    
    incomplete_notes = []
    
    with open(content_file, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            note_id = row.get('note_id')
            xsec_token = row.get('xsec_token', '')
            
            if not note_id:
                continue
            
            # 检查是否有最终截图
            screenshot_exists = False
            if os.path.exists(screenshot_dir):
                for filename in os.listdir(screenshot_dir):
                    if note_id in filename and filename.endswith('.png') and 'comments' in filename:
                        screenshot_exists = True
                        break
            
            if screenshot_exists:
                continue
            
            # 检查评论数量
            comment_count = note_comment_counts.get(note_id, 0)
            target_count = config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES
            
            if comment_count < target_count:
                utils.logger.info(f"[CompleteScreenshots] Note {note_id}: comments incomplete ({comment_count}/{target_count})")
                continue
            
            # 检查临时层文件
            note_temp_dir = os.path.join(temp_base_dir, note_id)
            layer_count = 0
            if os.path.exists(note_temp_dir):
                for filename in os.listdir(note_temp_dir):
                    if 'layer_' in filename and note_id in filename and filename.endswith('.png'):
                        layer_count += 1
            
            # 判断是否需要重新截图
            if layer_count == 0:
                # 没有任何截图
                utils.logger.info(f"[CompleteScreenshots] Note {note_id}: no screenshot (comments: {comment_count}/{target_count})")
                incomplete_notes.append({
                    'note_id': note_id,
                    'xsec_token': xsec_token,
                    'comment_count': comment_count,
                    'layer_count': 0,
                    'reason': 'no_screenshot'
                })
            elif layer_count < target_count:
                # 截图不完整
                utils.logger.info(f"[CompleteScreenshots] Note {note_id}: incomplete screenshot ({layer_count}/{target_count} layers)")
                incomplete_notes.append({
                    'note_id': note_id,
                    'xsec_token': xsec_token,
                    'comment_count': comment_count,
                    'layer_count': layer_count,
                    'reason': 'incomplete_screenshot'
                })
    
    return incomplete_notes


async def complete_screenshots(incomplete_notes):
    """
    为不完整的笔记重新截图
    """
    if not incomplete_notes:
        utils.logger.info("[CompleteScreenshots] All screenshots are complete!")
        return
    
    utils.logger.info(f"[CompleteScreenshots] Found {len(incomplete_notes)} notes need screenshot")
    utils.logger.info(f"[CompleteScreenshots] Starting to complete screenshots...")
    
    # 创建爬虫实例
    crawler = XiaoHongShuCrawler()
    
    try:
        # 启动浏览器
        await crawler.start()
        
        # 逐个处理
        for idx, note_info in enumerate(incomplete_notes, 1):
            note_id = note_info['note_id']
            xsec_token = note_info['xsec_token']
            layer_count = note_info['layer_count']
            comment_count = note_info['comment_count']
            
            utils.logger.info(f"[CompleteScreenshots] ({idx}/{len(incomplete_notes)}) Processing note {note_id}")
            utils.logger.info(f"  - Comments: {comment_count}")
            utils.logger.info(f"  - Current layers: {layer_count}")
            utils.logger.info(f"  - Target layers: {config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES}")
            
            try:
                # 构建笔记URL
                note_url = f"https://www.xiaohongshu.com/explore/{note_id}?xsec_token={xsec_token}&xsec_source=pc_search"
                
                # 截图
                screenshot_path = await crawler.xhs_client.screenshot_comments_section(
                    note_id=note_id,
                    note_url=note_url
                )
                
                if screenshot_path:
                    utils.logger.info(f"[CompleteScreenshots] ✓ Screenshot completed: {screenshot_path}")
                else:
                    utils.logger.warning(f"[CompleteScreenshots] ✗ Failed to screenshot note {note_id}")
                
                # 休眠
                await asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC)
                
            except Exception as e:
                utils.logger.error(f"[CompleteScreenshots] Error processing note {note_id}: {e}")
                continue
        
        utils.logger.info(f"[CompleteScreenshots] Completed! Processed {len(incomplete_notes)} notes")
        
    finally:
        # 关闭浏览器
        await crawler.close()


async def main():
    """主函数"""
    utils.logger.info("=" * 60)
    utils.logger.info("[CompleteScreenshots] Screenshot Completion Tool")
    utils.logger.info("=" * 60)
    
    # 检查不完整的截图
    incomplete_notes = await check_incomplete_screenshots()
    
    if not incomplete_notes:
        utils.logger.info("[CompleteScreenshots] All screenshots are complete!")
        return
    
    # 显示统计
    utils.logger.info(f"\n[CompleteScreenshots] Summary:")
    utils.logger.info(f"  - Total notes need screenshot: {len(incomplete_notes)}")
    
    no_screenshot = [n for n in incomplete_notes if n['reason'] == 'no_screenshot']
    incomplete_screenshot = [n for n in incomplete_notes if n['reason'] == 'incomplete_screenshot']
    
    if no_screenshot:
        utils.logger.info(f"  - No screenshot: {len(no_screenshot)}")
    if incomplete_screenshot:
        utils.logger.info(f"  - Incomplete screenshot: {len(incomplete_screenshot)}")
        for note in incomplete_screenshot[:3]:  # 显示前3个
            utils.logger.info(f"    - {note['note_id']}: {note['layer_count']}/{config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES} layers")
    
    # 询问是否继续
    print("\n" + "=" * 60)
    print("Do you want to complete these screenshots? (y/n): ", end='')
    choice = input().strip().lower()
    
    if choice != 'y':
        utils.logger.info("[CompleteScreenshots] Cancelled by user")
        return
    
    # 执行补全
    await complete_screenshots(incomplete_notes)


if __name__ == "__main__":
    asyncio.run(main())
