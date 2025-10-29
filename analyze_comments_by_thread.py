"""
小红书评论情感分析工具 - 按评论楼层统计版
功能：将一级评论和它的所有二级评论作为一个整体（一层），综合判断这一层的情感
使用Ollama API进行情感分析

更新：
- 支持关键词相关性分析：从summary CSV中读取source_keyword字段
- 分析时会判断评论是否与搜索关键词相关
- 如果评论讨论的是其他产品/品牌（与关键词无关），会被判定为中性
- 例如：搜索"雅诗兰黛"，但评论只说"兰蔻很好用"，会被判定为中性
"""

import time
import json
import requests
import pandas as pd
import logging
import traceback
from collections import defaultdict
from typing import Optional, List, Dict

# ================== 配置参数 ==================
# Ollama API配置
BASE_URL = "http://192.168.2.21:11434"  # Ollama服务地址
MODEL_NAME = "qwen2.5:7b"  # Ollama模型名称
TIMEOUT = 60  # 请求超时时间（秒）

# 文件路径配置
INPUT_COMMENTS_CSV = "data/xhs/csv/search_comments_2025-10-19.csv"  # 评论CSV
INPUT_SUMMARY_CSV = "data/xhs/csv/search_summary_with_ai_comments.csv"  # 摘要CSV
OUTPUT_SUMMARY_CSV = "data/xhs/csv/search_summary_with_ai_comments.csv"  # 更新后的摘要CSV
OUTPUT_DETAILS_CSV = "data/xhs/csv/comments_thread_analysis.csv"  # 按楼层的详细分析
STATS_CSV = "data/xhs/csv/comments_thread_stats.csv"  # 统计报告

# API调用参数
REQUEST_INTERVAL = 0.1  # API调用间隔(秒) - Ollama本地调用可以更快

# 判定参数
POSITIVE_THRESHOLD = 0.5  # 积极评论占比超过此值，判定该层为积极
NEGATIVE_THRESHOLD = 0.5  # 消极评论占比超过此值，判定该层为消极

# ================== 初始化设置 ==================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler("./comments_thread_analysis.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)


# ================== 核心函数 ==================


def analyze_thread_sentiment(thread_comments, keyword='', max_retries=3):
    """
    使用Ollama API分析整层楼评论的情感（带重试机制）
    一次性传入整层楼的所有评论，让AI综合判断整体情感倾向
    
    Args:
        thread_comments: 整层楼的所有评论列表，格式：[{'level': 1, 'content': '...'}, ...]
        keyword: 搜索关键词，用于判断评论是否与关键词相关
        max_retries: 最大重试次数
    
    Returns:
        dict: 情感分析结果
            - sentiment: 情感极性（0=消极，1=中性，2=积极）
            - positive_prob: 正面概率
            - negative_prob: 负面概率
            - confidence: 置信度
            - total_comments: 该楼层的评论总数
    """
    # 构建系统提示词，根据是否有关键词调整
    if keyword:
        system_prompt = f"""你是一个专业的情感分析助手。你将收到一个评论楼层的所有评论（包括一级评论和所有回复），请综合分析整个楼层的情感倾向。

**重要：本次分析的搜索关键词是「{keyword}」**

分析时请注意：
1. 综合考虑所有评论的情感
2. 权重可以考虑楼层关系（一级评论权重更高）
3. 注意评论之间的互动关系和情感传递
4. **关键：必须判断评论内容是否与关键词「{keyword}」相关**
   - 如果评论主要讨论的是「{keyword}」，则根据情感判断为积极/消极/中性
   - 如果评论主要讨论的是其他产品/品牌/话题（与「{keyword}」无关），则应判断为中性
   - 例如：关键词是「雅诗兰黛」，但评论只说「兰蔻很好用」，这应该是中性，因为不是在讨论雅诗兰黛

请严格按照以下JSON格式返回结果：
{{
  "sentiment": 2,
  "positive_prob": 0.85,
  "negative_prob": 0.05,
  "confidence": 0.90
}}

其中：
- sentiment: 情感极性，0=消极，1=中性，2=积极
- positive_prob: 正面概率（0-1之间的小数）
- negative_prob: 负面概率（0-1之间的小数）
- confidence: 置信度（0-1之间的小数）

判断标准：
- 积极(2)：整体表达对「{keyword}」的正面情绪、赞美、支持、喜欢等
- 消极(0)：整体表达对「{keyword}」的负面情绪、批评、抱怨、不满等
- 中性(1)：陈述事实、询问问题、无明显情感倾向，或主要讨论其他产品/话题

只返回JSON，不要有其他文字说明。"""
    else:
        system_prompt = """你是一个专业的情感分析助手。你将收到一个评论楼层的所有评论（包括一级评论和所有回复），请综合分析整个楼层的情感倾向。

分析时请注意：
1. 综合考虑所有评论的情感
2. 权重可以考虑楼层关系（一级评论权重更高）
3. 注意评论之间的互动关系和情感传递

请严格按照以下JSON格式返回结果：
{
  "sentiment": 2,
  "positive_prob": 0.85,
  "negative_prob": 0.05,
  "confidence": 0.90
}

其中：
- sentiment: 情感极性，0=消极，1=中性，2=积极
- positive_prob: 正面概率（0-1之间的小数）
- negative_prob: 负面概率（0-1之间的小数）
- confidence: 置信度（0-1之间的小数）

判断标准：
- 积极(2)：整体表达正面情绪、赞美、支持、喜欢等
- 消极(0)：整体表达负面情绪、批评、抱怨、不满等
- 中性(1)：陈述事实、询问问题、无明显情感倾向

只返回JSON，不要有其他文字说明。"""

    # 构建评论内容字符串
    comments_text = "【评论楼层】\n"
    for i, comment in enumerate(thread_comments, 1):
        level = comment.get('level', 1)
        content = comment.get('content', '')
        indent = "  " * (level - 1)  # 根据层级缩进
        comments_text += f"{indent}[L{level}] {content}\n"
    
    for retry in range(max_retries):
        try:
            # 发送请求到Ollama API
            response = requests.post(
                f"{BASE_URL}/api/chat",
                json={
                    "model": MODEL_NAME,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": f"请分析这个评论楼层的整体情感：\n\n{comments_text}"}
                    ],
                    "stream": False,
                    "options": {
                        "temperature": 0.3
                    }
                },
                timeout=TIMEOUT
            )
            
            if response.status_code != 200:
                logging.error(f"Ollama API错误: {response.status_code}")
                raise Exception(f"API返回错误状态码: {response.status_code}")
            
            result_json = response.json()
            result_text = result_json.get('message', {}).get('content', '').strip()
            
            # 解析JSON结果
            if "```json" in result_text:
                result_text = result_text.split("```json")[1].split("```")[0].strip()
            elif "```" in result_text:
                result_text = result_text.split("```")[1].split("```")[0].strip()
            
            result = json.loads(result_text)
            
            return {
                'sentiment': result.get('sentiment', 1),
                'positive_prob': result.get('positive_prob', 0),
                'confidence': result.get('confidence', 0),
                'negative_prob': result.get('negative_prob', 0),
                'total_comments': len(thread_comments)
            }
                
        except Exception as e:
            logging.error(f"楼层情感分析失败 (重试{retry+1}/{max_retries}): 楼层评论数={len(thread_comments)} | 错误: {str(e)}")
            if retry < max_retries - 1:
                wait_time = (retry + 1) * 2
                time.sleep(wait_time)
                continue
    
    # 所有重试都失败，返回中性
    logging.error(f"❌ 达到最大重试次数（{max_retries}次），返回中性结果。")
    return {'sentiment': 1, 'positive_prob': 0, 'confidence': 0, 'negative_prob': 0, 'total_comments': len(thread_comments)}


def build_comment_tree(comments_dict, parent_id, level=1):
    """
    递归构建评论树，找出所有直接和间接关联的子评论
    
    Args:
        comments_dict: 所有评论的字典 {comment_id: comment_data}
        parent_id: 父评论ID
        level: 当前层级
    
    Returns:
        list: 该父评论下的所有子评论列表（包括间接子评论）
    """
    result = []
    
    for comment_id, comment_data in comments_dict.items():
        if comment_data.get('parent_id') == parent_id:
            # 找到直接子评论
            comment_info = {
                'comment_id': comment_id,
                'content': comment_data.get('content', ''),
                'level': level
            }
            result.append(comment_info)
            
            # 递归查找该评论的子评论（间接关联）
            sub_comments = build_comment_tree(comments_dict, comment_id, level + 1)
            result.extend(sub_comments)
    
    return result


def process_comments():
    """
    处理评论CSV文件，按楼层进行情感分析并统计
    """
    # 1. 读取评论CSV
    try:
        df_comments = pd.read_csv(INPUT_COMMENTS_CSV, encoding='utf-8-sig')
        logging.info(f"成功读取 {len(df_comments)} 条评论")
    except Exception as e:
        logging.error(f"读取评论CSV失败: {e}")
        return
    
    if df_comments.empty:
        logging.warning("评论CSV文件为空")
        return
    
    # 2. 读取摘要CSV
    try:
        df_summary = pd.read_csv(INPUT_SUMMARY_CSV, encoding='utf-8-sig')
        logging.info(f"成功读取 {len(df_summary)} 条笔记摘要")
    except Exception as e:
        logging.error(f"读取摘要CSV失败: {e}")
        return
    
    # 3. 检查Ollama服务
    try:
        test_response = requests.get(f"{BASE_URL}/api/tags", timeout=5)
        if test_response.status_code == 200:
            logging.info("Ollama服务连接成功")
        else:
            logging.warning(f"Ollama服务响应异常: {test_response.status_code}")
    except Exception as e:
        logging.error(f"Ollama服务连接失败: {e}")
        logging.error("请确保Ollama服务已启动，并且BASE_URL配置正确")
        return
    
    # 4. 为 summary 新增统计列（只添加P10和N10）
    df_summary['P10'] = 0  # 前10层中积极的层数
    df_summary['N10'] = 0  # 前10层中消极的层数
    
    # 4.5 构建note_id到keyword的映射
    note_keyword_map = {}  # note_id -> keyword
    for idx, row in df_summary.iterrows():
        note_url = str(row.get('note_url', ''))
        keyword = str(row.get('source_keyword', '')).strip()
        
        # 从 note_url 中提取 note_id
        if 'explore/' in note_url:
            try:
                note_id = note_url.split('explore/')[1].split('?')[0]
                if keyword and keyword != 'nan':
                    note_keyword_map[note_id] = keyword
                    logging.info(f"笔记 {note_id[:8]}.. 关键词: {keyword}")
            except:
                pass
    
    logging.info(f"成功映射 {len(note_keyword_map)} 个笔记的关键词")
    
    # 5. 按笔记ID分组处理
    note_stats = {}  # 存储每个笔记的统计数据
    thread_details = []  # 存储每个楼层的详细信息
    
    # 6. 按笔记分组评论，构建评论字典
    logging.info("开始按笔记分组评论并构建评论树...")
    note_comments_dict = defaultdict(dict)  # note_id -> {comment_id: comment_data}
    note_root_comments = defaultdict(list)  # note_id -> [root_comment_ids]
    
    for index, row in df_comments.iterrows():
        note_id = str(row.get('note_id', ''))
        parent_id = str(row.get('parent_comment_id', '0'))
        comment_id = str(row.get('comment_id', ''))
        content = str(row.get('content', ''))
        
        # 处理空值和NaN
        if parent_id == '' or parent_id == 'nan' or pd.isna(parent_id):
            parent_id = '0'
        
        # 存储评论数据
        note_comments_dict[note_id][comment_id] = {
            'parent_id': parent_id,
            'content': content,
            'row': row
        }
        
        # 记录一级评论（根评论）
        if parent_id == '0':
            note_root_comments[note_id].append(comment_id)
    
    # 7. 逐笔记、逐楼层分析情感
    logging.info("开始进行情感分析...")
    
    for note_id in note_root_comments.keys():
        # 获取该笔记的关键词
        keyword = note_keyword_map.get(note_id, '')
        keyword_info = f" [关键词: {keyword}]" if keyword else " [无关键词]"
        logging.info(f"\n处理笔记: {note_id[:15]}...{keyword_info}")
        
        if note_id not in note_stats:
            note_stats[note_id] = {
                'total_threads': 0,
                'positive_threads': 0,
                'negative_threads': 0,
                'neutral_threads': 0,
                'p10': 0,
                'n10': 0,
                'threads': []
            }
        
        thread_count = 0
        root_comments = note_root_comments[note_id]
        
        for root_comment_id in root_comments:
            thread_count += 1
            
            # 获取一级评论内容
            root_comment_data = note_comments_dict[note_id][root_comment_id]
            parent_content = root_comment_data['content']
            
            # 构建整层楼的评论列表（包含一级评论和所有直接、间接子评论）
            thread_comments = [{
                'comment_id': root_comment_id,
                'content': parent_content,
                'level': 1
            }]
            
            # 递归获取所有子评论（包括间接关联）
            all_sub_comments = build_comment_tree(note_comments_dict[note_id], root_comment_id, level=2)
            thread_comments.extend(all_sub_comments)
            
            logging.info(f"  楼层 {thread_count}: 共 {len(thread_comments)} 条评论（包含所有层级）")
            logging.info(f"    一级评论: {parent_content[:50]}...")
            
            # 一次性分析整层楼的情感（传入关键词）
            thread_result = analyze_thread_sentiment(thread_comments, keyword=keyword)
            time.sleep(REQUEST_INTERVAL)
            
            # 转换sentiment数值为字符串
            sentiment_value = thread_result['sentiment']
            if sentiment_value == 2:
                thread_sentiment = 'positive'
            elif sentiment_value == 0:
                thread_sentiment = 'negative'
            else:
                thread_sentiment = 'neutral'
            
            logging.info(f"  楼层 {thread_count} 综合判定: {thread_sentiment.upper()} "
                        f"(置信度:{thread_result['confidence']:.2f}, "
                        f"正面概率:{thread_result['positive_prob']:.2f}, "
                        f"负面概率:{thread_result['negative_prob']:.2f})")
            
            # 记录楼层详情
            thread_details.append({
                'note_id': note_id,
                'thread_num': thread_count,
                'parent_content': parent_content[:100],
                'total_comments': len(thread_comments),
                'max_level': max(c['level'] for c in thread_comments),  # 最深层级
                'thread_sentiment': thread_sentiment,
                'confidence': thread_result['confidence'],
                'positive_prob': thread_result['positive_prob'],
                'negative_prob': thread_result['negative_prob']
            })
            
            # 更新统计
            note_stats[note_id]['total_threads'] += 1
            note_stats[note_id]['threads'].append(thread_sentiment)
            
            if thread_sentiment == 'positive':
                note_stats[note_id]['positive_threads'] += 1
            elif thread_sentiment == 'negative':
                note_stats[note_id]['negative_threads'] += 1
            else:
                note_stats[note_id]['neutral_threads'] += 1
            
            # 统计前10层
            if thread_count <= 10:
                if thread_sentiment == 'positive':
                    note_stats[note_id]['p10'] += 1
                elif thread_sentiment == 'negative':
                    note_stats[note_id]['n10'] += 1
    
    # 8. 保存楼层详细分析结果
    try:
        df_details = pd.DataFrame(thread_details)
        df_details.to_csv(OUTPUT_DETAILS_CSV, index=False, encoding='utf-8-sig')
        logging.info(f"✓ 楼层详细分析结果已保存: {OUTPUT_DETAILS_CSV}")
    except Exception as e:
        logging.error(f"保存详细结果失败: {e}")
    
    # 9. 更新 summary CSV
    logging.info("更新摘要CSV中的统计数据...")
    
    for idx, row in df_summary.iterrows():
        note_url = str(row.get('note_url', ''))
        
        # 从 note_url 中提取 note_id
        if 'explore/' in note_url:
            try:
                note_id = note_url.split('explore/')[1].split('?')[0]
            except:
                note_id = ''
        else:
            note_id = ''
        
        # 如果该笔记有统计数据，更新到 summary（只更新P10和N10）
        if note_id in note_stats:
            stats = note_stats[note_id]
            
            df_summary.at[idx, 'P10'] = stats['p10']
            df_summary.at[idx, 'N10'] = stats['n10']
            
            logging.info(f"笔记 {note_id[:8]}.. 统计: P10={stats['p10']}, N10={stats['n10']}")
    
    # 10. 保存更新后的 summary CSV
    try:
        df_summary.to_csv(OUTPUT_SUMMARY_CSV, index=False, encoding='utf-8-sig')
        logging.info(f"✓ 摘要CSV已更新并保存: {OUTPUT_SUMMARY_CSV}")
    except Exception as e:
        logging.error(f"保存摘要CSV失败: {e}")
    
    # 11. 生成总体统计报告
    try:
        stats_data = []
        
        total_notes = len(note_stats)
        total_threads = sum(s['total_threads'] for s in note_stats.values())
        total_positive = sum(s['positive_threads'] for s in note_stats.values())
        total_negative = sum(s['negative_threads'] for s in note_stats.values())
        total_neutral = sum(s['neutral_threads'] for s in note_stats.values())
        total_p10 = sum(s['p10'] for s in note_stats.values())
        total_n10 = sum(s['n10'] for s in note_stats.values())
        
        stats_data.append({'统计项': '分析笔记总数', '数值': total_notes})
        stats_data.append({'统计项': '分析楼层总数', '数值': total_threads})
        stats_data.append({'统计项': '积极楼层总数', '数值': total_positive})
        stats_data.append({'统计项': '消极楼层总数', '数值': total_negative})
        stats_data.append({'统计项': '中性楼层总数', '数值': total_neutral})
        stats_data.append({'统计项': '前10层中积极楼层数(P10)', '数值': total_p10})
        stats_data.append({'统计项': '前10层中消极楼层数(N10)', '数值': total_n10})
        stats_data.append({'统计项': '积极比例(%)', '数值': f'{(total_positive/total_threads*100):.2f}' if total_threads > 0 else '0.00'})
        stats_data.append({'统计项': '消极比例(%)', '数值': f'{(total_negative/total_threads*100):.2f}' if total_threads > 0 else '0.00'})
        
        stats_df = pd.DataFrame(stats_data)
        stats_df.to_csv(STATS_CSV, index=False, encoding='utf-8-sig')
        logging.info(f"✓ 统计报告已保存: {STATS_CSV}")
        
        # 在控制台打印统计结果
        print("\n" + "="*80)
        print("📊 评论楼层情感分析总体统计")
        print("="*80)
        print(stats_df.to_string(index=False))
        print("="*80)
        print(f"\n💡 说明：")
        print(f"  - 楼层 = 一级评论 + 它的所有二级评论")
        print(f"  - P10 = 前10层中，积极楼层的数量")
        print(f"  - N10 = 前10层中，消极楼层的数量")
        print(f"  - 判定标准：楼层中积极评论占比>{POSITIVE_THRESHOLD*100}%为积极，消极>{NEGATIVE_THRESHOLD*100}%为消极")
        print("="*80)
        print(f"\n✓ 已将P10、N10等统计数据添加到: {OUTPUT_SUMMARY_CSV}")
        print("="*80)
        
    except Exception as e:
        logging.error(f"生成统计报告失败: {e}")
    
    return note_stats


def main():
    """主函数"""
    print("="*80)
    print("小红书评论情感分析工具 - 按楼层统计版 (Ollama API)")
    print("="*80)
    print(f"📌 分析逻辑：")
    print(f"  1. 将一级评论和它的所有二级评论作为一个整体（一层/一楼）")
    print(f"  2. 综合判断这一层的情感（积极/消极/中性）")
    print(f"  3. 统计前10层中有多少积极、多少消极")
    print("="*80)
    print(f"⚙️  API配置：")
    print(f"  - 使用模型: {MODEL_NAME}")
    print(f"  - Ollama地址: {BASE_URL}")
    print(f"  - 调用间隔: {REQUEST_INTERVAL} 秒/次")
    print("="*80)
    print(f"📁 文件路径：")
    print(f"  输入评论: {INPUT_COMMENTS_CSV}")
    print(f"  输入摘要: {INPUT_SUMMARY_CSV}")
    print(f"  输出摘要: {OUTPUT_SUMMARY_CSV} (会添加P10/N10)")
    print(f"  详细分析: {OUTPUT_DETAILS_CSV}")
    print(f"  统计报告: {STATS_CSV}")
    print("="*80)
    print(f"💡 分析说明：")
    print(f"  - 每个楼层的所有评论（包括间接回复）会一次性传给AI分析")
    print(f"  - AI会综合判断整层楼的情感倾向")
    print(f"  - 如需调整API调用间隔，可修改第27行 REQUEST_INTERVAL")
    print("="*80)
    
    # 确认开始
    confirm = input("\n按Enter键开始分析，或输入'q'退出: ")
    if confirm.lower() == 'q':
        print("已取消操作")
        return
    
    # 开始分析
    start_time = time.time()
    
    try:
        stats = process_comments()
        
        elapsed_time = time.time() - start_time
        
        print("\n" + "="*80)
        print(f"✓ 分析完成！耗时: {elapsed_time:.2f} 秒")
        print(f"✓ 摘要CSV(已添加P10/N10): {OUTPUT_SUMMARY_CSV}")
        print(f"✓ 楼层详细分析: {OUTPUT_DETAILS_CSV}")
        print(f"✓ 统计报告: {STATS_CSV}")
        print("="*80)
        
    except Exception as e:
        logging.error(f"程序执行出错: {e}")
        logging.error(traceback.format_exc())


if __name__ == "__main__":
    main()

