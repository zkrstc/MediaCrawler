# -*- coding: utf-8 -*-
"""
快速检查截图状态
"""
import csv
import os
from collections import defaultdict

# 配置
CRAWLER_TYPE = "search"
CURRENT_DATE = "2025-10-17"
TARGET_COMMENT_COUNT = 20

# 文件路径
content_file = f"data/xhs/csv/{CRAWLER_TYPE}_contents_{CURRENT_DATE}.csv"
comments_file = f"data/xhs/csv/{CRAWLER_TYPE}_comments_{CURRENT_DATE}.csv"
screenshot_dir = "data/xhs/screenshots"

print("=" * 80)
print("截图状态检查工具")
print("=" * 80)

# 1. 检查文件是否存在
print(f"\n[1] 检查文件...")
if not os.path.exists(content_file):
    print(f"❌ Content 文件不存在: {content_file}")
    exit(1)
else:
    print(f"✅ Content 文件: {content_file}")

if not os.path.exists(comments_file):
    print(f"❌ Comments 文件不存在: {comments_file}")
    exit(1)
else:
    print(f"✅ Comments 文件: {comments_file}")

if not os.path.exists(screenshot_dir):
    print(f"⚠️  截图目录不存在: {screenshot_dir}")
    os.makedirs(screenshot_dir, exist_ok=True)
else:
    print(f"✅ 截图目录: {screenshot_dir}")

# 2. 统计评论数量
print(f"\n[2] 统计评论数量...")
note_comment_counts = defaultdict(int)
with open(comments_file, 'r', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    for row in reader:
        note_id = row.get('note_id')
        parent_comment_id = row.get('parent_comment_id', '')
        # 只统计一级评论（parent_comment_id 为 '0' 或为空）
        if parent_comment_id == '0' or parent_comment_id == '' or not parent_comment_id:
            note_comment_counts[note_id] += 1

print(f"✅ 找到 {len(note_comment_counts)} 个笔记有评论")

# 3. 检查每个笔记
print(f"\n[3] 检查每个笔记...")
print("-" * 80)
print(f"{'笔记ID':<25} {'一级评论':<10} {'截图':<10} {'状态':<20}")
print("-" * 80)

total_notes = 0
notes_with_screenshot = 0
notes_without_comments = 0
notes_need_screenshot = 0

with open(content_file, 'r', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    for row in reader:
        note_id = row.get('note_id')
        if not note_id:
            continue
        
        total_notes += 1
        
        # 检查截图
        screenshot_exists = False
        screenshot_filename = ""
        if os.path.exists(screenshot_dir):
            for filename in os.listdir(screenshot_dir):
                if note_id in filename and filename.endswith('.png') and 'comments' in filename:
                    screenshot_exists = True
                    screenshot_filename = filename
                    break
        
        # 检查评论
        comment_count = note_comment_counts.get(note_id, 0)
        
        # 判断状态
        if screenshot_exists:
            status = "✅ 完整"
            notes_with_screenshot += 1
        elif comment_count < TARGET_COMMENT_COUNT:
            status = f"⚠️  评论不足 ({comment_count}/{TARGET_COMMENT_COUNT})"
            notes_without_comments += 1
        else:
            status = f"❌ 缺少截图"
            notes_need_screenshot += 1
        
        screenshot_status = "✅" if screenshot_exists else "❌"
        
        print(f"{note_id:<25} {comment_count:<10} {screenshot_status:<10} {status:<20}")

print("-" * 80)

# 4. 统计摘要
print(f"\n[4] 统计摘要")
print("-" * 80)
print(f"总笔记数: {total_notes}")
print(f"有完整截图: {notes_with_screenshot} (✅)")
print(f"评论不足: {notes_without_comments} (⚠️  需要重新爬取评论)")
print(f"需要截图: {notes_need_screenshot} (❌ 可以补全)")
print("-" * 80)

# 5. 建议
print(f"\n[5] 建议")
if notes_need_screenshot > 0:
    print(f"✅ 有 {notes_need_screenshot} 个笔记可以补全截图")
    print(f"   运行: python main.py")
    print(f"   或者: python tools/complete_screenshots.py")
elif notes_without_comments > 0:
    print(f"⚠️  有 {notes_without_comments} 个笔记评论不足")
    print(f"   需要重新爬取评论，或者降低 CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES")
else:
    print(f"🎉 所有笔记都有完整截图！")

print("\n" + "=" * 80)
