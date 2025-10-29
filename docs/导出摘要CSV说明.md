# 小红书笔记摘要CSV导出功能说明

## 📊 功能说明

除了原有的详细CSV文件外，程序会自动生成一个**摘要CSV文件**，包含以下10个字段：

| 字段编号 | 字段名 | 说明 |
|---------|--------|------|
| 1 | `time` | 笔记发布时间 |
| 2 | `source_keyword` | 搜索关键词 |
| 3 | `nickname` | 作者昵称 |
| 4 | `note_url` | 笔记链接 |
| 5 | `title` | 笔记标题 |
| 6 | `desc` | 笔记内容描述 |
| 7 | `author_profile_url` | 作者主页链接 |
| 8 | `liked_count` | 该笔记的点赞量 |
| 9 | `comment_count` | 该笔记的总评论数 |
| 10 | `comments_screenshot` | 评论区长截图路径 |

## 📁 文件位置

摘要CSV文件保存在：
```
data/xhs/csv/search_summary_YYYY-MM-DD.csv
```

例如：
```
data/xhs/csv/search_summary_2025-10-16.csv
```

## ⚙️ 触发条件

摘要CSV会在以下条件**同时满足**时自动生成：
1. ✅ `SAVE_DATA_OPTION = "csv"` （CSV模式）
2. ✅ 评论截图功能已开启（`ENABLE_GET_COMMENTS_SCREENSHOT = True`）
3. ✅ 截图成功生成

## 🎯 使用场景

摘要CSV适合用于：
- 📈 **快速浏览**：只查看关键信息，不需要完整的爬取数据
- 📊 **数据分析**：直接导入Excel/Python进行分析
- 🖼️ **截图管理**：方便查看哪些笔记有评论截图
- 📝 **报告制作**：提取关键数据用于报告

## 💡 示例数据

```csv
time,source_keyword,nickname,note_url,title,desc,author_profile_url,liked_count,comment_count,comments_screenshot
2024-03-04,雅诗兰黛,筱龙,https://www.xiaohongshu.com/explore/65e159...,蔡徐坤演唱会,欢迎有缘人...,https://www.xiaohongshu.com/user/profile/68da5c3c...,2345,156,data/xhs/screenshots/comments_65e159...png
```

## 📝 注意事项

1. **去重机制**：
   - 程序会在截图完成后才导出摘要
   - 不会产生重复记录

2. **作者主页链接格式**：
   ```
   https://www.xiaohongshu.com/user/profile/{user_id}
   ```

3. **如果截图失败**：
   - 该笔记不会出现在摘要CSV中
   - 只有成功生成截图的笔记才会被导出

4. **与详细CSV的区别**：
   - **详细CSV** (`search_contents_*.csv`)：包含所有字段，用于完整数据存储
   - **摘要CSV** (`search_summary_*.csv`)：只包含10个关键字段，用于快速浏览和分析

## 🔧 配置要求

确保配置文件中设置：
```python
# config/base_config.py

# 数据保存格式为CSV
SAVE_DATA_OPTION = "csv"

# 开启评论截图功能
ENABLE_GET_COMMENTS_SCREENSHOT = True

# 设置截图的评论数量
SCREENSHOT_COMMENTS_COUNT = 10  # 或其他数值
```

## 📊 数据完整性

摘要CSV中的数据保证：
- ✅ 所有笔记都已成功爬取
- ✅ 所有评论都已成功获取
- ✅ 所有截图都已成功生成
- ✅ 所有字段都完整填充

这样可以确保摘要CSV中的数据是高质量、可靠的数据集。

---

**提示：如果需要查看所有笔记（包括截图失败的），请查看详细CSV文件。**

