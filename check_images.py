import lark_oapi as lark
from lark_oapi.api.bitable.v1 import *

# 配置
USER_ACCESS_TOKEN = "u-cOt7D_ElZbvpeuVEUZw4l_g0i5Z05l0ppU0004iG0fVK"
APP_TOKEN = "VHT3bJRIsavFwIslubOcwzEvnYd"
TABLE_ID = "tblhJJKhOCG1YVdg"

# 创建客户端
client = lark.Client.builder() \
    .enable_set_token(True) \
    .log_level(lark.LogLevel.INFO) \
    .build()

option = lark.RequestOption.builder() \
    .user_access_token(USER_ACCESS_TOKEN) \
    .build()

# 获取所有记录
print("正在检查表格中的图片...")
request = ListAppTableRecordRequest.builder() \
    .app_token(APP_TOKEN) \
    .table_id(TABLE_ID) \
    .page_size(500) \
    .build()

response = client.bitable.v1.app_table_record.list(request, option)

if not response.success():
    print(f"获取记录失败: {response.code}, {response.msg}")
    exit(1)

records = response.data.items
print(f"表格共 {len(records)} 条记录\n")

# 统计screen_shots字段
has_screenshot = 0
no_screenshot = 0

for i, record in enumerate(records, 1):
    fields = record.fields
    
    if 'screen_shots' in fields and fields['screen_shots']:
        has_screenshot += 1
        # 显示前5条作为示例
        if has_screenshot <= 5:
            print(f"记录 {i}: ✓ 有图片 - {fields['screen_shots']}")
    else:
        no_screenshot += 1
        if no_screenshot <= 5:
            comments_screenshot = fields.get('comments_screenshot', '无')
            print(f"记录 {i}: ✗ 无图片 - 原路径: {comments_screenshot}")

print(f"\n统计结果:")
print(f"✓ 已上传图片: {has_screenshot} 条")
print(f"✗ 未上传图片: {no_screenshot} 条")
print(f"上传成功率: {has_screenshot/len(records)*100:.1f}%")
