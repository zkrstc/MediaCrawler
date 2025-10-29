import json
import csv
import os
from pathlib import Path
import time

import lark_oapi as lark
from lark_oapi.api.bitable.v1 import *
from lark_oapi.api.drive.v1 import *


class FeishuBitableManager:
    """飞书多维表格管理器"""
    
    def __init__(self, user_access_token: str):
        """初始化客户端
        
        Args:
            user_access_token: 用户访问令牌
        """
        self.client = lark.Client.builder() \
            .enable_set_token(True) \
            .log_level(lark.LogLevel.INFO) \
            .build()
        
        self.option = lark.RequestOption.builder() \
            .user_access_token(user_access_token) \
            .build()
    
    def create_bitable(self, name: str, folder_token: str = None) -> str:
        """创建多维表格
        
        Args:
            name: 表格名称
            folder_token: 文件夹token（可选）
            
        Returns:
            app_token: 多维表格的app_token
        """
        print(f"正在创建多维表格: {name}...")
        
        request = CreateAppRequest.builder() \
            .request_body(App.builder()
                .name(name)
                .folder_token(folder_token)
                .build()) \
            .build()
        
        response: CreateAppResponse = self.client.bitable.v1.app.create(request, self.option)
        
        if not response.success():
            error_msg = f"创建多维表格失败: code={response.code}, msg={response.msg}"
            print(error_msg)
            raise Exception(error_msg)
        
        app_token = response.data.app.app_token
        print(f"✓ 多维表格创建成功! app_token: {app_token}")
        print(f"访问链接: https://feishu.cn/base/{app_token}")
        return app_token
    
    def get_default_table(self, app_token: str) -> str:
        """获取多维表格的默认数据表
        
        Args:
            app_token: 多维表格token
            
        Returns:
            table_id: 数据表ID
        """
        print("正在获取默认数据表...")
        
        request = ListAppTableRequest.builder() \
            .app_token(app_token) \
            .build()
        
        response: ListAppTableResponse = self.client.bitable.v1.app_table.list(request, self.option)
        
        if not response.success():
            error_msg = f"获取数据表失败: code={response.code}, msg={response.msg}"
            print(error_msg)
            raise Exception(error_msg)
        
        if not response.data.items:
            raise Exception("未找到数据表")
        
        table_id = response.data.items[0].table_id
        print(f"✓ 获取到数据表ID: {table_id}")
        return table_id
    
    def create_field(self, app_token: str, table_id: str, field_name: str, field_type: int) -> str:
        """创建字段
        
        Args:
            app_token: 多维表格token
            table_id: 数据表ID
            field_name: 字段名称
            field_type: 字段类型 (1=文本, 2=数字, 17=附件等)
            
        Returns:
            field_id: 字段ID
        """
        print(f"正在创建字段: {field_name}...")
        
        request = CreateAppTableFieldRequest.builder() \
            .app_token(app_token) \
            .table_id(table_id) \
            .request_body(AppTableField.builder()
                .field_name(field_name)
                .type(field_type)
                .build()) \
            .build()
        
        response: CreateAppTableFieldResponse = self.client.bitable.v1.app_table_field.create(request, self.option)
        
        if not response.success():
            error_msg = f"创建字段失败: code={response.code}, msg={response.msg}"
            print(error_msg)
            raise Exception(error_msg)
        
        field_id = response.data.field.field_id
        print(f"✓ 字段创建成功! field_id: {field_id}")
        return field_id
    
    def delete_field(self, app_token: str, table_id: str, field_id: str) -> bool:
        """删除字段
        
        Args:
            app_token: 多维表格token
            table_id: 数据表ID
            field_id: 字段ID
            
        Returns:
            是否删除成功
        """
        request = DeleteAppTableFieldRequest.builder() \
            .app_token(app_token) \
            .table_id(table_id) \
            .field_id(field_id) \
            .build()
        
        response: DeleteAppTableFieldResponse = self.client.bitable.v1.app_table_field.delete(request, self.option)
        
        if not response.success():
            print(f"删除字段失败: code={response.code}, msg={response.msg}")
            return False
        
        return True
    
    def list_fields(self, app_token: str, table_id: str) -> dict:
        """列出所有字段
        
        Args:
            app_token: 多维表格token
            table_id: 数据表ID
            
        Returns:
            字段名称到字段ID的映射
        """
        request = ListAppTableFieldRequest.builder() \
            .app_token(app_token) \
            .table_id(table_id) \
            .build()
        
        response: ListAppTableFieldResponse = self.client.bitable.v1.app_table_field.list(request, self.option)
        
        if not response.success():
            error_msg = f"获取字段列表失败: code={response.code}, msg={response.msg}"
            print(error_msg)
            raise Exception(error_msg)
        
        field_map = {}
        for field in response.data.items:
            field_map[field.field_name] = field.field_id
        
        return field_map
    
    def delete_empty_records(self, app_token: str, table_id: str):
        """删除空记录
        
        Args:
            app_token: 多维表格token
            table_id: 数据表ID
        """
        print("\n正在检查并删除空记录...")
        
        # 获取所有记录
        request = ListAppTableRecordRequest.builder() \
            .app_token(app_token) \
            .table_id(table_id) \
            .page_size(500) \
            .build()
        
        response: ListAppTableRecordResponse = self.client.bitable.v1.app_table_record.list(request, self.option)
        
        if not response.success():
            print(f"获取记录失败: code={response.code}, msg={response.msg}")
            return
        
        records = response.data.items
        deleted_count = 0
        
        for record in records:
            # 如果记录的所有字段都为空，则删除
            if not record.fields or len(record.fields) == 0:
                delete_request = DeleteAppTableRecordRequest.builder() \
                    .app_token(app_token) \
                    .table_id(table_id) \
                    .record_id(record.record_id) \
                    .build()
                
                delete_response: DeleteAppTableRecordResponse = self.client.bitable.v1.app_table_record.delete(
                    delete_request, self.option)
                
                if delete_response.success():
                    deleted_count += 1
                    time.sleep(0.2)
        
        print(f"✓ 共删除 {deleted_count} 条空记录\n")
    
    def delete_default_fields(self, app_token: str, table_id: str):
        """删除新建表格的默认字段
        
        Args:
            app_token: 多维表格token
            table_id: 数据表ID
        """
        print("\n正在删除默认字段...")
        
        # 获取所有字段
        field_map = self.list_fields(app_token, table_id)
        print(f"当前字段: {list(field_map.keys())}")
        
        # 删除默认字段（通常是"文本"、"数字"等）
        # 注意：第一个字段通常是主字段，无法删除
        deleted_count = 0
        skipped_count = 0
        
        for field_name, field_id in field_map.items():
            # 可以根据需要自定义要删除的字段名称
            if field_name in ["文本", "数字", "单选", "多选", "日期", "复选框", "人员", "电话", "超链接", "附件"]:
                print(f"正在删除字段: {field_name}...")
                if self.delete_field(app_token, table_id, field_id):
                    deleted_count += 1
                    print(f"✓ 已删除字段: {field_name}")
                    time.sleep(0.3)  # 避免请求过快
                else:
                    skipped_count += 1
                    print(f"⊘ 跳过字段: {field_name} (可能是主字段)")
        
        print(f"✓ 共删除 {deleted_count} 个默认字段，跳过 {skipped_count} 个\n")
    
    def upload_image(self, image_path: str, app_token: str) -> str:
        """上传图片到飞书
        
        Args:
            image_path: 图片路径
            app_token: 多维表格token
            
        Returns:
            file_token: 文件token
        """
        if not os.path.exists(image_path):
            print(f"警告: 图片不存在 {image_path}")
            return None
        
        print(f"正在上传图片: {os.path.basename(image_path)}...")
        
        request = UploadAllMediaRequest.builder() \
            .request_body(UploadAllMediaRequestBody.builder()
                .file_name(os.path.basename(image_path))
                .parent_type("bitable_image")
                .parent_node(app_token)
                .size(os.path.getsize(image_path))
                .file(open(image_path, 'rb'))
                .build()) \
            .build()
        
        response: UploadAllMediaResponse = self.client.drive.v1.media.upload_all(request, self.option)
        
        if not response.success():
            print(f"上传图片失败: code={response.code}, msg={response.msg}")
            return None
        
        file_token = response.data.file_token
        print(f"✓ 图片上传成功! file_token: {file_token}")
        return file_token
    
    def add_record(self, app_token: str, table_id: str, fields: dict) -> str:
        """添加记录
        
        Args:
            app_token: 多维表格token
            table_id: 数据表ID
            fields: 字段数据
            
        Returns:
            record_id: 记录ID
        """
        request = CreateAppTableRecordRequest.builder() \
            .app_token(app_token) \
            .table_id(table_id) \
            .request_body(AppTableRecord.builder()
                .fields(fields)
                .build()) \
            .build()
        
        response: CreateAppTableRecordResponse = self.client.bitable.v1.app_table_record.create(request, self.option)
        
        if not response.success():
            print(f"添加记录失败: code={response.code}, msg={response.msg}")
            if response.raw and response.raw.content:
                try:
                    error_detail = json.loads(response.raw.content)
                    print(f"详细错误: {json.dumps(error_detail, indent=2, ensure_ascii=False)}")
                except Exception as e:
                    print(f"无法解析错误响应: {e}")
            return None
        
        record_id = response.data.record.record_id
        return record_id
    
    def import_csv_to_bitable(self, app_token: str, table_id: str, csv_path: str):
        """导入CSV数据到多维表格
        
        Args:
            app_token: 多维表格token
            table_id: 数据表ID
            csv_path: CSV文件路径
        """
        print(f"\n正在导入CSV数据: {csv_path}...")
        
        # 读取CSV文件
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        
        print(f"CSV文件共 {len(rows)} 条记录")
        
        # 获取现有字段
        field_map = self.list_fields(app_token, table_id)
        print(f"现有字段: {list(field_map.keys())}")
        
        # 获取CSV的列名
        csv_columns = list(rows[0].keys()) if rows else []
        print(f"CSV列: {csv_columns}")
        
        # 为CSV中的每个列创建字段（如果不存在）
        for col in csv_columns:
            if col not in field_map:
                try:
                    field_id = self.create_field(app_token, table_id, col, 1)  # 类型1=文本
                    field_map[col] = field_id
                    time.sleep(0.5)  # 避免请求过快
                except Exception as e:
                    print(f"创建字段 {col} 失败: {e}")
        
        # 导入数据
        success_count = 0
        fail_count = 0
        
        for i, row in enumerate(rows, 1):
            try:
                # 构建字段数据 - 使用字段名称而不是字段ID
                fields = {}
                for col, value in row.items():
                    if value:  # 只添加非空值
                        fields[col] = value
                
                # 添加记录
                record_id = self.add_record(app_token, table_id, fields)
                if record_id:
                    success_count += 1
                    if i % 10 == 0:
                        print(f"已导入 {i}/{len(rows)} 条记录...")
                else:
                    fail_count += 1
                
                # 避免请求过快
                time.sleep(0.3)
                
            except Exception as e:
                fail_count += 1
                print(f"导入第 {i} 条记录失败: {e}")
        
        print(f"\n✓ CSV导入完成! 成功: {success_count}, 失败: {fail_count}")
        return success_count, fail_count
    
    def update_screenshots(self, app_token: str, table_id: str, base_path: str):
        """更新截图字段
        
        Args:
            app_token: 多维表格token
            table_id: 数据表ID
            base_path: 项目根路径
        """
        print("\n正在处理截图上传...")
        
        # 获取字段映射并验证字段存在
        field_map = self.list_fields(app_token, table_id)
        print(f"当前表格字段列表: {list(field_map.keys())}")
        
        if 'comments_screenshot' not in field_map:
            print("错误: 未找到 comments_screenshot 字段")
            return
        
        if 'screen_shots' not in field_map:
            print("错误: 未找到 screen_shots 字段")
            print("请确保 screen_shots 字段已经创建")
            return
        
        print("✓ 字段验证通过")
        
        # 获取所有记录
        print("正在获取所有记录...")
        request = ListAppTableRecordRequest.builder() \
            .app_token(app_token) \
            .table_id(table_id) \
            .page_size(500) \
            .build()
        
        response: ListAppTableRecordResponse = self.client.bitable.v1.app_table_record.list(request, self.option)
        
        if not response.success():
            print(f"获取记录失败: code={response.code}, msg={response.msg}")
            return
        
        records = response.data.items
        print(f"表格中共 {len(records)} 条记录")
        
        # 统计有comments_screenshot的记录
        valid_records = 0
        for record in records:
            if 'comments_screenshot' in record.fields and record.fields['comments_screenshot']:
                valid_records += 1
        print(f"其中有截图路径的记录: {valid_records} 条\n")
        
        # 处理每条记录
        success_count = 0
        fail_count = 0
        
        for i, record in enumerate(records, 1):
            try:
                # 获取图片路径 - 使用字段名称
                fields = record.fields
                if 'comments_screenshot' not in fields:
                    continue
                
                image_path = fields['comments_screenshot']
                if not image_path:
                    continue
                
                # 构建完整路径
                full_image_path = os.path.join(base_path, image_path)
                
                # 上传图片
                file_token = self.upload_image(full_image_path, app_token)
                
                if file_token:
                    # 使用requests直接调用API，避免SDK的JSON解析问题
                    try:
                        import requests
                        
                        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/{record.record_id}"
                        headers = {
                            "Authorization": f"Bearer {self.option.user_access_token}",
                            "Content-Type": "application/json"
                        }
                        data = {
                            "fields": {
                                "screen_shots": [{
                                    "file_token": file_token
                                }]
                            }
                        }
                        
                        resp = requests.put(url, headers=headers, json=data, timeout=30)
                        
                        if resp.status_code == 200:
                            result = resp.json()
                            if result.get("code") == 0:
                                success_count += 1
                                if i % 10 == 0 or i == len(records):
                                    print(f"✓ [{i}/{len(records)}] 更新成功")
                            else:
                                fail_count += 1
                                print(f"✗ [{i}/{len(records)}] 更新失败: code={result.get('code')}, msg={result.get('msg')}")
                        else:
                            fail_count += 1
                            print(f"✗ [{i}/{len(records)}] HTTP错误: {resp.status_code}")
                    
                    except Exception as update_err:
                        fail_count += 1
                        print(f"✗ [{i}/{len(records)}] 更新异常: {update_err}")
                else:
                    fail_count += 1
                    print(f"✗ [{i}/{len(records)}] 图片上传失败，跳过更新")
                
                # 避免请求过快（API限制：50次/秒 = 0.02秒/次）
                time.sleep(0.03)
                
            except json.JSONDecodeError as je:
                # JSON解析错误，但这不应该发生在我们的代码中
                fail_count += 1
                print(f"✗ 处理第 {i} 条记录时发生JSON解析错误: {je}")
                print(f"这可能是SDK内部问题，但图片可能已成功上传")
            except Exception as e:
                fail_count += 1
                print(f"✗ 处理第 {i} 条记录失败: {e}")
                print(f"错误类型: {type(e).__name__}")
                import traceback
                traceback.print_exc()
        
        print(f"\n✓ 截图处理完成! 成功: {success_count}, 失败: {fail_count}")


def main():
    """主函数"""
    # ==================== 配置区域 ====================
    USER_ACCESS_TOKEN = "u-cOt7D_ElZbvpeuVEUZw4l_g0i5Z05l0ppU0004iG0fVK"  # 请替换为你的token
    CSV_PATH = r"data\xhs\csv\search_summary_with_ai_comments.csv"
    BASE_PATH = os.path.dirname(os.path.abspath(__file__))
    BITABLE_NAME = "小红书数据分析"
    
    # ===== 快速模式配置 =====
    # 如果已经创建过表格，可以直接填写app_token和table_id，跳过创建和导入步骤
    # 第一次运行后，会输出这两个值，复制到这里即可
    EXISTING_APP_TOKEN = ""  # 例如: "CPbPbZ5pCaaxVys8pdUcApEzn5g"
    EXISTING_TABLE_ID = ""   # 例如: "tblWSpvHjPx6rKnL"
    
    # 运行模式选择
    SKIP_CREATE = bool(EXISTING_APP_TOKEN and EXISTING_TABLE_ID)  # 如果填写了token，则跳过创建
    SKIP_IMPORT = SKIP_CREATE  # 跳过CSV导入
    ONLY_UPDATE_IMAGES = SKIP_CREATE  # 只更新图片
    # ================================================
    
    print("="*60)
    print("飞书多维表格导入工具")
    if ONLY_UPDATE_IMAGES:
        print("【快速模式】仅更新图片")
    else:
        print("【完整模式】创建表格并导入数据")
    print("="*60)
    
    try:
        # 初始化管理器
        manager = FeishuBitableManager(USER_ACCESS_TOKEN)
        
        if SKIP_CREATE:
            # 使用已存在的表格
            print(f"\n使用已存在的表格...")
            app_token = EXISTING_APP_TOKEN
            table_id = EXISTING_TABLE_ID
            print(f"app_token: {app_token}")
            print(f"table_id: {table_id}")
        else:
            # 1. 创建多维表格
            app_token = manager.create_bitable(BITABLE_NAME)
            
            # 2. 获取默认数据表
            table_id = manager.get_default_table(app_token)
            
            # 3. 删除默认字段
            manager.delete_default_fields(app_token, table_id)
            
            # 3.5 删除空记录
            manager.delete_empty_records(app_token, table_id)
            
            # 4. 导入CSV数据
            if not SKIP_IMPORT:
                csv_full_path = os.path.join(BASE_PATH, CSV_PATH)
                manager.import_csv_to_bitable(app_token, table_id, csv_full_path)
            
            # 5. 添加 screen_shots 字段（附件类型）
            print("\n正在创建 screen_shots 字段...")
            try:
                manager.create_field(app_token, table_id, "screen_shots", 17)  # 类型17=附件
                print("等待字段创建生效...")
                time.sleep(2)  # 等待字段创建生效
            except Exception as e:
                print(f"创建字段失败（可能已存在）: {e}")
        
        # 6. 上传图片并更新 screen_shots 字段
        manager.update_screenshots(app_token, table_id, BASE_PATH)
        
        print("\n" + "="*60)
        print("✓ 所有操作完成!")
        print(f"访问链接: https://feishu.cn/base/{app_token}")
        
        if not SKIP_CREATE:
            print("\n【下次快速运行】复制以下配置到脚本第472-473行:")
            print(f'EXISTING_APP_TOKEN = "{app_token}"')
            print(f'EXISTING_TABLE_ID = "{table_id}"')
        
        print("="*60)
        
    except Exception as e:
        print(f"\n✗ 执行失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()