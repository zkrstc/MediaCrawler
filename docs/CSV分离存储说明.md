# CSV 分离存储说明

## 📋 概述

为了解决中途暂停时数据丢失的问题，同时满足最终汇总需要截图的需求，我们采用了**双CSV文件策略**：

1. **`search_contents_*.csv`** - 完整数据表（不含截图，立即保存）
2. **`search_summary_*.csv`** - 汇总摘要表（含截图，等待截图后保存）

---

## 🎯 设计目标

### 问题
- **中途暂停数据丢失**：之前的策略是等待截图完成后才写入，如果中途暂停，数据会丢失
- **最终需要截图**：用户希望在最终的汇总表中包含截图路径

### 解决方案
- **content.csv**：第一时间保存所有笔记数据（不包含截图字段），确保中途暂停也能保留
- **summary.csv**：只在截图完成后保存，包含精简字段 + 截图路径

---

## 📊 两个CSV文件对比

### 1. `search_contents_*.csv` - 完整数据表

**特点**：
- ✅ **立即保存**：获取笔记详情后立即写入，不等待截图
- ✅ **去重保护**：每个笔记只保存一次
- ✅ **完整字段**：包含所有笔记信息
- ❌ **不含截图**：移除了 `comments_screenshot` 字段

**字段列表**（23个字段）：
```
note_id, type, title, desc, video_url, time, last_update_time,
user_id, nickname, avatar, liked_count, collected_count, 
comment_count, share_count, ip_location, image_list, tag_list,
last_modify_ts, note_url, source_keyword, xsec_token
```

**用途**：
- 数据备份和恢复
- 完整的笔记信息查询
- 中途暂停后继续爬取的依据

---

### 2. `search_summary_*.csv` - 汇总摘要表

**特点**：
- ⏳ **等待截图**：只在截图完成后才写入
- ✅ **包含截图**：包含 `comments_screenshot` 字段
- 📌 **精简字段**：只保留关键信息，便于查看

**字段列表**（10个字段）：
```
time                    - 发布时间（格式化为 YYYY-MM-DD HH:MM:SS）
source_keyword          - 搜索关键词
nickname                - 作者昵称
note_url                - 内容链接
title                   - 标题
desc                    - 内容描述
author_profile_url      - 作者主页链接
liked_count             - 点赞量
comment_count           - 评论数
comments_screenshot     - 评论区截图路径 ⭐
```

**用途**：
- 最终数据分析和展示
- 包含截图的完整记录
- 可直接用于报告和可视化

---

## 🔄 工作流程

### 情况1：开启截图功能（`ENABLE_GET_COMMENTS_SCREENSHOT = True`）

```
1. 获取笔记详情
   ↓
2. 立即写入 content.csv（不含截图）✅
   ↓
3. 获取评论并生成截图
   ↓
4. 写入 summary.csv（含截图）✅
   ↓
5. 完成
```

**结果**：
- `content.csv`：包含所有笔记，无截图字段
- `summary.csv`：只包含有截图的笔记，含截图路径

---

### 情况2：未开启截图功能（`ENABLE_GET_COMMENTS_SCREENSHOT = False`）

```
1. 获取笔记详情
   ↓
2. 立即写入 content.csv（不含截图）✅
   ↓
3. 完成（不生成 summary.csv）
```

**结果**：
- `content.csv`：包含所有笔记，无截图字段
- `summary.csv`：不生成

---

## 💡 使用场景

### 场景1：中途暂停后继续爬取
```bash
# 第一次运行（爬取了100条后暂停）
python main.py

# 检查 content.csv
# ✅ 已保存 100 条记录

# 继续运行
python main.py

# content.csv 会继续追加新记录（去重保护）
```

### 场景2：数据分析和展示
```bash
# 使用 summary.csv 进行分析
# ✅ 包含截图路径
# ✅ 字段精简，易于处理
# ✅ 时间已格式化

# 可以使用配套工具转换为 Excel
python csv_to_excel_with_images.py
```

### 场景3：数据恢复
```bash
# 如果 summary.csv 损坏或丢失
# ✅ content.csv 仍然保留完整数据
# ✅ 可以基于 content.csv 重新生成 summary
```

---

## 🔧 技术实现

### 去重机制
```python
# 使用内存集合记录已保存的笔记ID
self.saved_note_ids = set()

# 每个笔记只保存一次
if note_id in self.saved_note_ids:
    return
self.saved_note_ids.add(note_id)
```

### 立即刷新机制
```python
# 写入后立即刷新到磁盘
f.flush()
os.fsync(f.fileno())
```

### 字段过滤
```python
# content.csv 移除截图字段
content_item_without_screenshot = content_item.copy()
content_item_without_screenshot.pop("comments_screenshot", None)
```

---

## 📁 文件位置

```
data/
└── xhs/
    ├── csv/
    │   ├── search_contents_2025-10-17.csv    # 完整数据（不含截图）
    │   └── search_summary_2025-10-17.csv     # 汇总数据（含截图）
    └── screenshots/
        ├── search_comments_xxx_2025-10-17.png
        └── ...
```

---

## ⚙️ 配置选项

在 `config.py` 中：

```python
# 是否开启评论区截图功能
ENABLE_GET_COMMENTS_SCREENSHOT = True  # True=生成 summary.csv，False=只生成 content.csv

# 数据保存方式
SAVE_DATA_OPTION = "csv"  # 必须是 "csv" 才会生成这两个文件
```

---

## 🎨 对比示例

### content.csv（部分字段）
```csv
note_id,title,nickname,liked_count,comment_count
65e159e5...,秋日穿搭分享,小红薯ABC,1234,56
65e159e6...,美食探店,小红薯XYZ,5678,90
```

### summary.csv（部分字段）
```csv
time,nickname,title,liked_count,comment_count,comments_screenshot
2025-10-17 10:30:00,小红薯ABC,秋日穿搭分享,1234,56,data/xhs/screenshots/search_comments_65e159e5_2025-10-17.png
2025-10-17 10:35:00,小红薯XYZ,美食探店,5678,90,data/xhs/screenshots/search_comments_65e159e6_2025-10-17.png
```

---

## ✅ 优势总结

1. **数据安全**：中途暂停不会丢失数据
2. **灵活使用**：可以根据需求选择使用哪个CSV
3. **性能优化**：不需要等待截图就能保存数据
4. **去重保护**：避免重复记录
5. **立即刷新**：每条记录写入后立即保存到磁盘

---

**提示**：如果只需要完整数据，使用 `content.csv`；如果需要带截图的汇总，使用 `summary.csv`。
