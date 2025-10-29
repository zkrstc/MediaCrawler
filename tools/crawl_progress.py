# -*- coding: utf-8 -*-
"""
爬取进度管理工具
用于实现断点续爬功能，避免重复爬取已保存的内容
"""
import os
import csv
from typing import Set
from tools import utils


class CrawlProgressManager:
    """爬取进度管理器"""
    
    def __init__(self, platform: str, crawler_type: str):
        """
        初始化进度管理器
        Args:
            platform: 平台名称 (xhs, dy, bili等)
            crawler_type: 爬取类型 (search, detail等)
        """
        self.platform = platform
        self.crawler_type = crawler_type
        self.crawled_ids: Set[str] = set()
        self.crawled_comment_note_ids: Set[str] = set()  # 已爬取评论的笔记ID
        
    def load_crawled_ids(self) -> Set[str]:
        """
        从已有的CSV文件中加载已爬取的ID列表
        Returns:
            已爬取的ID集合
        """
        from tools.utils import utils
        
        # 构建CSV文件路径
        base_path = f"data/{self.platform}/csv"
        if not os.path.exists(base_path):
            utils.logger.info(f"[CrawlProgressManager] CSV directory not found: {base_path}, starting fresh crawl")
            return set()
        
        file_name = f"{self.crawler_type}_contents_{utils.get_current_date()}.csv"
        file_path = os.path.join(base_path, file_name)
        
        if not os.path.exists(file_path):
            utils.logger.info(f"[CrawlProgressManager] CSV file not found: {file_path}, starting fresh crawl")
            return set()
        
        crawled_ids = set()
        try:
            with open(file_path, 'r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                # 根据不同平台使用不同的ID字段名
                id_field = self._get_id_field_name()
                
                for row in reader:
                    item_id = row.get(id_field)
                    if item_id:
                        crawled_ids.add(item_id)
            
            utils.logger.info(f"[CrawlProgressManager] Loaded {len(crawled_ids)} crawled IDs from {file_path}")
        except Exception as e:
            utils.logger.error(f"[CrawlProgressManager] Error loading crawled IDs: {e}")
        
        self.crawled_ids = crawled_ids
        return crawled_ids
    
    def _get_id_field_name(self) -> str:
        """
        根据平台获取ID字段名
        Returns:
            ID字段名
        """
        id_field_map = {
            "xhs": "note_id",
            "dy": "aweme_id",
            "bili": "video_id",
            "ks": "video_id",
            "wb": "note_id",
            "tieba": "note_id",
            "zhihu": "content_id",
        }
        return id_field_map.get(self.platform, "note_id")
    
    def is_crawled(self, item_id: str) -> bool:
        """
        检查某个ID是否已经爬取过
        Args:
            item_id: 内容ID
        Returns:
            True表示已爬取，False表示未爬取
        """
        return item_id in self.crawled_ids
    
    def mark_as_crawled(self, item_id: str):
        """
        标记某个ID为已爬取
        Args:
            item_id: 内容ID
        """
        self.crawled_ids.add(item_id)
    
    def get_crawled_count(self) -> int:
        """
        获取已爬取的数量
        Returns:
            已爬取的数量
        """
        return len(self.crawled_ids)
    
    def load_crawled_comment_note_ids(self, min_comment_count: int = 10, check_screenshot: bool = True) -> Set[str]:
        """
        从已有的comments CSV文件中加载已爬取评论的笔记ID列表
        只统计一级评论数量（parent_comment_id为空），因为二级评论数量是动态的
        如果开启了截图功能，还会检查截图文件是否存在
        Args:
            min_comment_count: 最小一级评论数量，默认为10（与 CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES 保持一致）
            check_screenshot: 是否检查截图文件存在，默认True
        Returns:
            已爬取完整评论且有截图的笔记ID集合
        """
        from tools.utils import utils
        from collections import Counter, defaultdict
        
        # 构建 CSV文件路径
        base_path = f"data/{self.platform}/csv"
        if not os.path.exists(base_path):
            utils.logger.info(f"[CrawlProgressManager] CSV directory not found: {base_path}, starting fresh comment crawl")
            return set()
        
        file_name = f"{self.crawler_type}_comments_{utils.get_current_date()}.csv"
        file_path = os.path.join(base_path, file_name)
        
        if not os.path.exists(file_path):
            utils.logger.info(f"[CrawlProgressManager] Comments CSV file not found: {file_path}, starting fresh comment crawl")
            return set()
        
        # 统计每个笔记的一级评论数量（不包括二级评论）
        note_primary_comment_counts = Counter()
        note_total_comment_counts = Counter()
        
        try:
            with open(file_path, 'r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                # 根据不同平台使用不同的ID字段名
                id_field = self._get_id_field_name()
                
                for row in reader:
                    note_id = row.get(id_field)
                    if not note_id:
                        continue
                    
                    # 统计总评论数
                    note_total_comment_counts[note_id] += 1
                    
                    # 只统计一级评论（parent_comment_id 为 '0' 或为空）
                    parent_comment_id = row.get('parent_comment_id', '')
                    if parent_comment_id == '0' or parent_comment_id == '' or not parent_comment_id:
                        note_primary_comment_counts[note_id] += 1
            
            # 只有一级评论数量 >= min_comment_count 的笔记才被认为已完成
            complete_note_ids = set()
            incomplete_note_ids = {}
            
            for note_id in note_total_comment_counts.keys():
                primary_count = note_primary_comment_counts.get(note_id, 0)
                total_count = note_total_comment_counts.get(note_id, 0)
                
                if primary_count >= min_comment_count:
                    complete_note_ids.add(note_id)
                else:
                    incomplete_note_ids[note_id] = {
                        'primary': primary_count,
                        'total': total_count
                    }
            
            # 如果开启了截图检查，过滤掉没有截图的笔记
            if check_screenshot:
                import config
                if config.ENABLE_GET_COMMENTS_SCREENSHOT:
                    screenshot_dir = f"data/{self.platform}/screenshots"
                    temp_dir = os.path.join(screenshot_dir, "temp")
                    notes_without_screenshot = set()
                    notes_with_incomplete_screenshot = set()
                    
                    for note_id in list(complete_note_ids):
                        # 检查是否存在截图文件（模糊匹配）
                        screenshot_exists = False
                        if os.path.exists(screenshot_dir):
                            for filename in os.listdir(screenshot_dir):
                                if note_id in filename and filename.endswith('.png') and 'comments' in filename:
                                    screenshot_exists = True
                                    break
                        
                        if not screenshot_exists:
                            # 检查该笔记的临时层文件（按note_id精确匹配）
                            layer_count = 0
                            note_temp_dir = os.path.join(temp_dir, note_id)
                            if os.path.exists(note_temp_dir):
                                for filename in os.listdir(note_temp_dir):
                                    if 'layer_' in filename and note_id in filename and filename.endswith('.png'):
                                        layer_count += 1
                            
                            if layer_count > 0 and layer_count < min_comment_count:
                                notes_with_incomplete_screenshot.add(note_id)
                                utils.logger.info(f"[CrawlProgressManager] Note {note_id} has incomplete screenshot ({layer_count} layers < {min_comment_count})")
                            
                            complete_note_ids.remove(note_id)
                            notes_without_screenshot.add(note_id)
                    
                    if notes_without_screenshot:
                        utils.logger.info(f"[CrawlProgressManager] Found {len(notes_without_screenshot)} notes with complete comments but missing/incomplete screenshots")
                        if notes_with_incomplete_screenshot:
                            utils.logger.info(f"  - {len(notes_with_incomplete_screenshot)} notes have incomplete screenshots (will be re-captured)")
                        utils.logger.info(f"  - These notes will be re-crawled to generate screenshots")
            
            utils.logger.info(f"[CrawlProgressManager] Comment crawl status:")
            utils.logger.info(f"  - Complete notes (>={min_comment_count} primary comments + screenshot): {len(complete_note_ids)}")
            if incomplete_note_ids:
                utils.logger.info(f"  - Incomplete notes (<{min_comment_count} primary comments): {len(incomplete_note_ids)}")
                # 显示前几个不完整的笔记详情
                sample_notes = list(incomplete_note_ids.items())[:3]
                for note_id, counts in sample_notes:
                    utils.logger.info(f"    - {note_id}: {counts['primary']} primary + {counts['total'] - counts['primary']} sub = {counts['total']} total")
        except Exception as e:
            utils.logger.error(f"[CrawlProgressManager] Error loading comment note IDs: {e}")
            complete_note_ids = set()
        
        self.crawled_comment_note_ids = complete_note_ids
        return complete_note_ids
    
    def is_comment_crawled(self, note_id: str) -> bool:
        """
        检查某个笔记的评论是否已经爬取过
        Args:
            note_id: 笔记ID
        Returns:
            True表示已爬取，False表示未爬取
        """
        return note_id in self.crawled_comment_note_ids
    
    def mark_comment_as_crawled(self, note_id: str):
        """
        标记某个笔记的评论为已爬取
        Args:
            note_id: 笔记ID
        """
        self.crawled_comment_note_ids.add(note_id)
    
    def get_crawled_comment_count(self) -> int:
        """
        获取已爬取评论的笔记数量
        Returns:
            已爬取评论的笔记数量
        """
        return len(self.crawled_comment_note_ids)
    
    def delete_incomplete_note_data(self, note_id: str) -> bool:
        """
        删除某个笔记的所有数据（content + comments + screenshot）
        Args:
            note_id: 笔记ID
        Returns:
            是否删除成功
        """
        from tools.utils import utils
        import shutil
        
        deleted_something = False
        
        # 1. 删除 content.csv 中的记录
        base_path = f"data/{self.platform}/csv"
        content_file = os.path.join(base_path, f"{self.crawler_type}_contents_{utils.get_current_date()}.csv")
        if os.path.exists(content_file):
            try:
                all_rows = []
                deleted_count = 0
                with open(content_file, 'r', encoding='utf-8-sig') as f:
                    reader = csv.DictReader(f)
                    fieldnames = reader.fieldnames
                    # 小红书使用 note_id
                    id_field = 'note_id'
                    
                    for row in reader:
                        if row.get(id_field) != note_id:
                            all_rows.append(row)
                        else:
                            deleted_count += 1
                
                # 重写文件
                if deleted_count > 0:
                    with open(content_file, 'w', encoding='utf-8-sig', newline='') as f:
                        writer = csv.DictWriter(f, fieldnames=fieldnames)
                        writer.writeheader()
                        writer.writerows(all_rows)
                    utils.logger.info(f"[CrawlProgressManager] Deleted {deleted_count} content record for note {note_id}")
                    deleted_something = True
            except Exception as e:
                utils.logger.error(f"[CrawlProgressManager] Error deleting content for {note_id}: {e}")
        
        # 2. 删除 comments.csv 中的记录
        comments_file = os.path.join(base_path, f"{self.crawler_type}_comments_{utils.get_current_date()}.csv")
        if os.path.exists(comments_file):
            try:
                all_rows = []
                comment_deleted = 0
                with open(comments_file, 'r', encoding='utf-8-sig') as f:
                    reader = csv.DictReader(f)
                    fieldnames = reader.fieldnames
                    # 小红书使用 note_id
                    id_field = 'note_id'
                    
                    for row in reader:
                        if row.get(id_field) != note_id:
                            all_rows.append(row)
                        else:
                            comment_deleted += 1
                
                # 重写文件
                if comment_deleted > 0:
                    with open(comments_file, 'w', encoding='utf-8-sig', newline='') as f:
                        writer = csv.DictWriter(f, fieldnames=fieldnames)
                        writer.writeheader()
                        writer.writerows(all_rows)
                    utils.logger.info(f"[CrawlProgressManager] Deleted {comment_deleted} comment records for note {note_id}")
                    deleted_something = True
            except Exception as e:
                utils.logger.error(f"[CrawlProgressManager] Error deleting comments for {note_id}: {e}")
        
        # 3. 删除截图文件
        screenshot_dir = "data/xhs/screenshots"
        if os.path.exists(screenshot_dir):
            # 删除最终截图
            for filename in os.listdir(screenshot_dir):
                if note_id in filename and filename.endswith('.png'):
                    try:
                        filepath = os.path.join(screenshot_dir, filename)
                        os.remove(filepath)
                        utils.logger.info(f"[CrawlProgressManager] Deleted screenshot: {filename}")
                        deleted_something = True
                    except Exception as e:
                        utils.logger.error(f"[CrawlProgressManager] Error deleting screenshot {filename}: {e}")
            
            # 删除临时层文件
            temp_dir = os.path.join(screenshot_dir, "temp", note_id)
            if os.path.exists(temp_dir):
                try:
                    shutil.rmtree(temp_dir)
                    utils.logger.info(f"[CrawlProgressManager] Deleted temp directory for note {note_id}")
                    deleted_something = True
                except Exception as e:
                    utils.logger.error(f"[CrawlProgressManager] Error deleting temp dir for {note_id}: {e}")
        
        return deleted_something
    
    def clean_incomplete_comments(self, min_comment_count: int = 10) -> int:
        """
        清理不完整的评论记录（一级评论数量 < min_comment_count 的笔记）
        删除这些笔记的所有评论（包括一级和二级），以便重新爬取
        Args:
            min_comment_count: 最小一级评论数量
        Returns:
            删除的评论条数（包括一级和二级）
        """
        from tools.utils import utils
        from collections import Counter
        import tempfile
        import shutil
        
        base_path = f"data/{self.platform}/csv"
        file_name = f"{self.crawler_type}_comments_{utils.get_current_date()}.csv"
        file_path = os.path.join(base_path, file_name)
        
        if not os.path.exists(file_path):
            utils.logger.info(f"[CrawlProgressManager] No comments file to clean: {file_path}")
            return 0
        
        # 统计每个笔记的一级评论数量
        note_primary_comment_counts = Counter()
        all_rows = []
        
        try:
            with open(file_path, 'r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                fieldnames = reader.fieldnames
                id_field = self._get_id_field_name()
                
                for row in reader:
                    note_id = row.get(id_field)
                    if note_id:
                        all_rows.append(row)
                        # 只统计一级评论（parent_comment_id 为 '0' 或为空）
                        parent_comment_id = row.get('parent_comment_id', '')
                        if parent_comment_id == '0' or parent_comment_id == '' or not parent_comment_id:
                            note_primary_comment_counts[note_id] += 1
            
            # 找出一级评论不完整的笔记ID
            incomplete_note_ids = set()
            for note_id, primary_count in note_primary_comment_counts.items():
                if primary_count < min_comment_count:
                    incomplete_note_ids.add(note_id)
            
            if not incomplete_note_ids:
                utils.logger.info(f"[CrawlProgressManager] No incomplete comments to clean")
                return 0
            
            # 过滤掉不完整的评论
            filtered_rows = [row for row in all_rows if row.get(id_field) not in incomplete_note_ids]
            deleted_count = len(all_rows) - len(filtered_rows)
            
            # 写入临时文件，然后替换原文件
            temp_file = tempfile.NamedTemporaryFile(mode='w', delete=False, encoding='utf-8-sig', newline='')
            try:
                writer = csv.DictWriter(temp_file, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(filtered_rows)
                temp_file.close()
                
                # 备份原文件
                backup_path = file_path + ".backup"
                shutil.copy2(file_path, backup_path)
                
                # 替换原文件
                shutil.move(temp_file.name, file_path)
                
                utils.logger.info(f"[CrawlProgressManager] Cleaned incomplete comments:")
                utils.logger.info(f"  - Incomplete notes: {len(incomplete_note_ids)}")
                utils.logger.info(f"  - Deleted comment rows: {deleted_count}")
                utils.logger.info(f"  - Backup saved to: {backup_path}")
                
                return deleted_count
            except Exception as e:
                if os.path.exists(temp_file.name):
                    os.unlink(temp_file.name)
                raise e
                
        except Exception as e:
            utils.logger.error(f"[CrawlProgressManager] Error cleaning incomplete comments: {e}")
            return 0
