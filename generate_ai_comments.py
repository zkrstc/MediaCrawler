"""
使用Ollama API为小红书笔记生成AI评论
功能：读取CSV → 结合关键词和内容 → 生成评论 → 添加ai_comment字段
"""

import os
import csv
import logging
import time
import requests
from tqdm import tqdm
from typing import Optional, List, Dict

# ================== 配置参数 ==================
# Ollama API配置
BASE_URL = "http://192.168.2.21:11434"  # Ollama服务地址
MODEL_NAME = "qwen2.5:7b"  # Ollama模型名称
TIMEOUT = 60  # 请求超时时间（秒）

# 文件路径配置
INPUT_CSV = "data/xhs/csv/search_summary_2025-10-19.csv"  # 输入CSV文件
OUTPUT_CSV = "data/xhs/csv/search_summary_with_ai_comments.csv"  # 输出CSV文件

# API调用参数
MAX_RETRIES = 3  # 最大重试次数
REQUEST_INTERVAL = 2  # API调用间隔(秒)
COMMENT_COUNT = 5  # 每条笔记生成的评论数量

# ================== 初始化设置 ==================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler("./ai_comments_generation.log"),
        logging.StreamHandler()
    ]
)


# ================== 核心函数 ==================
def generate_comments(source_keyword, desc, comment_count=5):
    """
    使用Ollama API生成评论
    
    Args:
        source_keyword: 搜索关键词
        desc: 笔记描述内容
        comment_count: 生成评论数量
    
    Returns:
        str: 生成的评论，用分号分隔
    """
    # 限制描述长度，避免token过多
    desc_preview = desc[:500] if len(desc) > 500 else desc
    
    system_prompt = """你是一个小红书用户，负责根据笔记内容生成真实自然的评论。

要求：
1. 评论要贴合笔记内容，体现真实用户的反馈
2. 评论风格要多样化：有赞美、提问、分享经验、表达共鸣等
3. 语气要自然，使用口语化表达，可以使用表情符号
4. 每条评论长度控制在10-30字
5. 评论之间要有区别，不要重复

评论类型示例：
- 赞美类：好实用！马克了～、太详细了！感谢分享
- 提问类：请问这个在哪里买的呀？、姐妹用了多久有效果？
- 共鸣类：我也是这样！、说到我心坎里了
- 经验分享类：我用过，确实不错、建议搭配xx一起用
- 感谢类：谢谢分享！正需要这个、收藏了慢慢看
"""

    user_prompt = f"""请根据以下小红书笔记信息，生成{comment_count}条真实自然的用户评论。

关键词：{source_keyword}
笔记内容：
{desc_preview}

要求：
1. 生成{comment_count}条评论
2. 评论要与【关键词】和【笔记内容】相关
3. 评论风格多样化，贴合小红书用户习惯
4. 直接输出评论，每条评论用分号(；)分隔，不要添加序号或其他标记
5. 格式示例：评论1；评论2；评论3；评论4；评论5

现在请生成评论："""

    for retry in range(MAX_RETRIES):
        try:
            # 发送请求到Ollama API
            response = requests.post(
                f"{BASE_URL}/api/chat",
                json={
                    "model": MODEL_NAME,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    "stream": False,
                    "options": {
                        "temperature": 0.9  # 增加随机性，让评论更多样化
                    }
                },
                timeout=TIMEOUT
            )
            
            if response.status_code == 200:
                result = response.json()
                comments = result.get('message', {}).get('content', '').strip()
            else:
                logging.error(f"Ollama API错误: {response.status_code}")
                raise Exception(f"API返回错误状态码: {response.status_code}")
            
            # 清理可能的格式问题
            comments = comments.replace('\n', '；')  # 替换换行为分号
            comments = comments.replace('；；', '；')  # 去除重复分号
            comments = comments.strip('；')  # 去除首尾分号
            
            logging.info(f"成功生成评论: {comments[:50]}...")
            return comments
            
        except Exception as e:
            logging.warning(f"API调用失败 (重试 {retry+1}/{MAX_RETRIES}): {str(e)}")
            if retry < MAX_RETRIES - 1:
                time.sleep(REQUEST_INTERVAL * (retry + 1))  # 递增等待时间
            else:
                logging.error(f"生成评论失败，已达最大重试次数")
                return "生成失败"
    
    return "生成失败"


def process_csv():
    """
    处理CSV文件，为每条记录生成AI评论
    """
    # 检查输入文件是否存在
    if not os.path.exists(INPUT_CSV):
        logging.error(f"输入文件不存在: {INPUT_CSV}")
        return
    
    logging.info(f"开始处理CSV文件: {INPUT_CSV}")
    
    # 读取CSV数据
    rows = []
    try:
        with open(INPUT_CSV, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        logging.info(f"成功读取 {len(rows)} 条记录")
    except Exception as e:
        logging.error(f"读取CSV失败: {e}")
        return
    
    if not rows:
        logging.warning("CSV文件为空")
        return
    
    # 为每条记录生成评论
    logging.info("开始生成AI评论...")
    for idx, row in enumerate(tqdm(rows, desc="生成评论进度"), 1):
        source_keyword = row.get('source_keyword', '')
        desc = row.get('desc', '')
        
        if not source_keyword or not desc:
            logging.warning(f"第 {idx} 条记录缺少必要字段，跳过")
            row['ai_comment'] = "数据不完整"
            continue
        
        logging.info(f"正在处理第 {idx}/{len(rows)} 条: 关键词='{source_keyword}'")
        
        # 生成评论
        comments = generate_comments(source_keyword, desc, COMMENT_COUNT)
        row['ai_comment'] = comments
        
        # API调用间隔，避免触发限流
        if idx < len(rows):  # 最后一条不需要等待
            time.sleep(REQUEST_INTERVAL)
    
    # 写入新的CSV文件
    try:
        fieldnames = list(rows[0].keys())
        if 'ai_comment' not in fieldnames:
            fieldnames.append('ai_comment')
        
        with open(OUTPUT_CSV, 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        
        logging.info(f"✓ 成功生成带AI评论的CSV文件: {OUTPUT_CSV}")
        logging.info(f"✓ 共处理 {len(rows)} 条记录")
        
    except Exception as e:
        logging.error(f"写入CSV失败: {e}")


def main():
    """主函数"""
    print("=" * 60)
    print("小红书笔记AI评论生成工具")
    print("=" * 60)
    print(f"输入文件: {INPUT_CSV}")
    print(f"输出文件: {OUTPUT_CSV}")
    print(f"每条笔记生成: {COMMENT_COUNT} 条评论")
    print(f"API调用间隔: {REQUEST_INTERVAL} 秒")
    print("=" * 60)
    
    # 确认开始
    confirm = input("\n按Enter键开始处理，或输入'q'退出: ")
    if confirm.lower() == 'q':
        print("已取消操作")
        return
    
    # 开始处理
    start_time = time.time()
    process_csv()
    elapsed_time = time.time() - start_time
    
    print("\n" + "=" * 60)
    print(f"✓ 处理完成！耗时: {elapsed_time:.2f} 秒")
    print(f"✓ 输出文件: {OUTPUT_CSV}")
    print("=" * 60)


if __name__ == "__main__":
    main()

