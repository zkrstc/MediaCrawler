# -*- coding: utf-8 -*-
"""
调试评论数据
"""
import csv
import os

# 配置
CRAWLER_TYPE = "search"
CURRENT_DATE = "2025-10-17"
comments_file = f"data/xhs/csv/{CRAWLER_TYPE}_comments_{CURRENT_DATE}.csv"

print("=" * 80)
print("评论数据调试工具")
print("=" * 80)

if not os.path.exists(comments_file):
    print(f"❌ Comments 文件不存在: {comments_file}")
    exit(1)

print(f"✅ Comments 文件: {comments_file}")

# 读取评论
print(f"\n[1] 读取评论数据...")
total_comments = 0
primary_comments = 0
sub_comments = 0
notes_with_comments = set()

with open(comments_file, 'r', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    
    # 显示表头
    print(f"\n表头字段: {reader.fieldnames}")
    
    print(f"\n[2] 前10条评论数据:")
    print("-" * 120)
    print(f"{'笔记ID':<25} {'评论ID':<25} {'父评论ID':<25} {'类型':<10} {'内容':<30}")
    print("-" * 120)
    
    for idx, row in enumerate(reader):
        total_comments += 1
        
        note_id = row.get('note_id', '')
        comment_id = row.get('comment_id', '')
        parent_comment_id = row.get('parent_comment_id', '')
        content = row.get('content', '')[:30]
        
        notes_with_comments.add(note_id)
        
        # 判断类型（parent_comment_id 为 '0' 或为空才是一级评论）
        if parent_comment_id == '0' or parent_comment_id == '' or not parent_comment_id:
            comment_type = "一级评论"
            primary_comments += 1
        else:
            comment_type = "二级评论"
            sub_comments += 1
        
        # 只显示前10条
        if idx < 10:
            print(f"{note_id:<25} {comment_id:<25} {parent_comment_id:<25} {comment_type:<10} {content:<30}")

print("-" * 120)

# 统计
print(f"\n[3] 统计摘要")
print("-" * 80)
print(f"总评论数: {total_comments}")
print(f"一级评论: {primary_comments}")
print(f"二级评论: {sub_comments}")
print(f"有评论的笔记数: {len(notes_with_comments)}")
print("-" * 80)

# 按笔记统计
print(f"\n[4] 按笔记统计一级评论")
print("-" * 80)
print(f"{'笔记ID':<25} {'一级评论数':<15} {'总评论数':<15}")
print("-" * 80)

note_stats = {}
with open(comments_file, 'r', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    for row in reader:
        note_id = row.get('note_id', '')
        parent_comment_id = row.get('parent_comment_id', '')
        
        if note_id not in note_stats:
            note_stats[note_id] = {'primary': 0, 'total': 0}
        
        note_stats[note_id]['total'] += 1
        
        # 只统计一级评论（parent_comment_id 为 '0' 或为空）
        if parent_comment_id == '0' or parent_comment_id == '' or not parent_comment_id:
            note_stats[note_id]['primary'] += 1

for note_id, stats in note_stats.items():
    print(f"{note_id:<25} {stats['primary']:<15} {stats['total']:<15}")

print("-" * 80)

# 诊断
print(f"\n[5] 诊断")
if primary_comments == 0:
    print("❌ 问题：没有一级评论！")
    print("\n可能原因：")
    print("1. parent_comment_id 字段全部有值（都被识别为二级评论）")
    print("2. 评论爬取逻辑有问题")
    print("\n建议：")
    print("- 检查评论爬取代码")
    print("- 检查 parent_comment_id 的判断逻辑")
else:
    print(f"✅ 有 {primary_comments} 条一级评论")

print("\n" + "=" * 80)
