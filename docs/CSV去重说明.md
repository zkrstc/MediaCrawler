# CSV 去重功能说明

## 🎯 问题

之前的代码会导致 `search_contents_*.csv` 文件中出现**重复记录**：

```csv
note_id,...,comments_screenshot
65e159e5...,  (第一次保存 - 无截图)
65e159e5...,data\xhs\screenshots\... (第二次保存 - 有截图)
```

**原因：**
1. 第一次保存笔记数据时，截图还未生成
2. 第二次更新笔记数据时（截图完成后），CSV 是追加模式，导致重复

## ✅ 解决方案

### 去重策略

在 `store/xhs/_store_impl.py` 中实现了智能去重：

```python
# 使用集合记录已保存的笔记ID
self.saved_note_ids = set()

async def store_content(self, content_item: Dict):
    note_id = content_item.get("note_id")
    comments_screenshot = content_item.get("comments_screenshot", "")
    
    # 1. 如果已经保存过，跳过
    if note_id in self.saved_note_ids:
        return
    
    # 2. 如果开启了截图功能，等待截图完成再写入
    if config.ENABLE_GET_COMMENTS_SCREENSHOT and not comments_screenshot:
        return  # 等待第二次调用（有截图时）
    
    # 3. 记录并写入
    self.saved_note_ids.add(note_id)
    await self.writer.write_to_csv(item_type="contents", item=content_item)
```

### 工作流程

#### 情况1：开启截图功能

```
1. 获取笔记详情 → 第一次调用 store_content (无截图)
   ↓ 跳过（等待截图）
2. 获取评论并截图
   ↓
3. 第二次调用 store_content (有截图)
   ↓ 写入CSV（包含截图路径）
4. 完成 ✅
```

**结果：CSV 中只有一条记录，且包含截图路径**

#### 情况2：未开启截图功能

```
1. 获取笔记详情 → 第一次调用 store_content (无截图)
   ↓ 直接写入CSV
2. 完成 ✅
```

**结果：CSV 中只有一条记录，无截图路径**

## 📊 对比

### 修复前

```csv
note_id,title,comments_screenshot
65e159e5...,标题,                    ← 第一次（重复）
65e159e5...,标题,data/xhs/screenshots/... ← 第二次（重复）
```

### 修复后

```csv
note_id,title,comments_screenshot
65e159e5...,标题,data/xhs/screenshots/... ← 只有一条，且完整
```

## 🎨 CSV 文件说明

运行后会生成两个 CSV 文件：

### 1. `search_contents_*.csv` - 完整数据
- **用途**：保存所有笔记的完整信息
- **去重**：✅ 已实现（每个笔记只保存一次）
- **截图**：如果开启截图功能，记录都会包含截图路径

### 2. `search_summary_*.csv` - 摘要数据
- **用途**：保存关键字段的摘要
- **去重**：✅ 天然去重（只在有截图时写入）
- **截图**：所有记录都包含截图路径

## 💡 注意事项

1. **内存缓存**：
   - 使用 `self.saved_note_ids` 集合记录已保存的笔记ID
   - 仅在程序运行期间有效
   - 重启程序后缓存会清空（但不影响，因为会生成新的CSV文件）

2. **截图失败的情况**：
   - 如果截图失败（返回空路径），笔记**不会**出现在 contents CSV 中
   - 但评论数据仍会保存到 comments CSV 中

3. **向后兼容**：
   - 如果没有开启截图功能，行为与之前一致
   - 不会影响 DB/JSON/SQLite 等其他存储方式

## 🔧 清理旧的重复数据

如果你的 CSV 文件中已经有重复数据，可以：

### 方法1：删除旧文件重新运行
```bash
# 删除旧的CSV文件
del data\xhs\csv\*.csv

# 重新运行程序
python main.py
```

### 方法2：使用 pandas 去重（Python）
```python
import pandas as pd

# 读取CSV
df = pd.read_csv('data/xhs/csv/search_contents_2025-10-16.csv')

# 去重（保留最后一条，即有截图的那条）
df_dedup = df.drop_duplicates(subset=['note_id'], keep='last')

# 保存
df_dedup.to_csv('data/xhs/csv/search_contents_2025-10-16_clean.csv', index=False)
```

### 方法3：Excel 手动去重
1. 打开 CSV 文件
2. 选择数据 → 删除重复项
3. 选择 `note_id` 列作为去重依据
4. 保存

---

**提示：新运行的程序会自动避免重复，无需手动处理。**

