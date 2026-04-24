import requests
import time
import json

BASE_URL = "http://localhost:8000/api/v1"

def wait_for_pause(pipeline_id):
    while True:
        resp = requests.get(f"{BASE_URL}/pipeline/{pipeline_id}/status").json()
        if not resp.get("success"):
            print(f"❌ 查询失败: {resp.get('error')}")
            return None
        
        data = resp.get("data")
        if not data:
            print("❌ 无数据返回")
            return None
        
        status = data.get("status")
        print(f"当前状态: {status}...")
        
        if status == "paused":
            return data
        if status == "failed":
            print("❌ Pipeline 失败:", json.dumps(data, indent=2, ensure_ascii=False))
            return None
        if status == "success":
            return data
        time.sleep(3)

def get_last_stage_output(data):
    """获取最后一个阶段的输出"""
    stages = data.get("stages", [])
    if not stages:
        return None
    return stages[-1].get("output_data")

# 1. 创建需求
print("🚀 1. 提交需求...")
req = {"requirement": "在 api/v1 下新增一个 /system/stats 接口，返回内存和 CPU 占用率，需要遵循 api -> service -> models 的分层规范。"}
res = requests.post(f"{BASE_URL}/pipeline/create", json=req).json()

if not res.get("success"):
    print(f"❌ 创建 Pipeline 失败: {res.get('error')}")
    exit(1)

p_id = res["data"]["pipeline_id"]
print(f"✅ Pipeline 已创建: ID {p_id}")

# 2. 等待需求分析完成并审批
print("\n🔍 2. 等待架构师分析完成...")
data = wait_for_pause(p_id)
if not data:
    print("❌ 架构师分析阶段失败")
    exit(1)

output = get_last_stage_output(data)
if output:
    print(f"💡 架构师方案: {json.dumps(output, indent=2, ensure_ascii=False)}")
else:
    print("⚠️ 架构师方案为空")

input("确认方案无误？按回车进行 [Approve]...")
approve_res = requests.post(f"{BASE_URL}/pipeline/{p_id}/approve", json={"notes": "架构拆解合理，同意进入设计阶段"}).json()
if not approve_res.get("success"):
    print(f"❌ 审批失败: {approve_res.get('error')}")
    exit(1)

# 3. 等待技术设计完成并审批
print("\n🎨 3. 等待设计师输出技术方案...")
data = wait_for_pause(p_id)
if not data:
    print("❌ 设计师阶段失败")
    exit(1)

output = get_last_stage_output(data)
if output:
    print(f"💡 设计师方案: {json.dumps(output, indent=2, ensure_ascii=False)}")
else:
    print("⚠️ 设计师方案为空")

input("确认技术细节无误？按回车进行 [Approve] 启动编码...")
approve_res = requests.post(f"{BASE_URL}/pipeline/{p_id}/approve", json={"notes": "设计符合规范，开始编码"}).json()
if not approve_res.get("success"):
    print(f"❌ 审批失败: {approve_res.get('error')}")
    exit(1)

# 4. 等待编码完成
print("\n⌨️ 4. Coder 正在疯狂码字中...")
final_data = wait_for_pause(p_id)

if not final_data:
    print("❌ 编码阶段失败")
    exit(1)

if final_data.get("status") == "success":
    print("\n🎉 任务圆满完成！")
    delivery = final_data.get("delivery", {})
    print(f"📦 交付分支: {delivery.get('git_branch')}")
    print(f"📝 变更摘要: {delivery.get('summary')}")
    print("-" * 50)
    print("请去查看代码库变更，并切到对应分支运行测试！")
else:
    print(f"❌ Pipeline 最终状态: {final_data.get('status')}")
    print(json.dumps(final_data, indent=2, ensure_ascii=False))
