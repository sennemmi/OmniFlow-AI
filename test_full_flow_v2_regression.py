import requests
import time
import json
import sys

BASE_URL = "http://localhost:8000/api/v1"

# 更加复杂的重构需求
REQUIREMENT = """
1. 增强健康检查：修改 api/v1/health.py，使其返回 database_status (检查数据库连接是否正常)。
2. 自动化清理：新增 service/cleanup_service.py，实现清理 7 天前备份文件的功能。
3. 暴露接口：在 api/v1/system.py 中新增 POST /system/cleanup 触发清理。
注意：必须复用 CodeExecutorService 中定义的备份目录逻辑，严禁硬编码路径。
"""

def wait_for_state(p_id, target_status, stage_name=None):
    print(f"\n⏳ 等待 Pipeline 进入 {target_status} 状态...")
    while True:
        resp = requests.get(f"{BASE_URL}/pipeline/{p_id}/status").json()
        data = resp["data"]
        status = data["status"]
        curr_stage = data["current_stage"]
        
        sys.stdout.write(f"\r[ID: {p_id}] 当前阶段: {curr_stage} | 整体状态: {status}")
        sys.stdout.flush()

        if status == target_status:
            if stage_name:
                # 检查特定阶段是否出现在 stages 列表中
                names = [s["name"] for s in data["stages"]]
                if stage_name in names: return data
            else:
                return data
        if status == "failed":
            print("\n❌ 流程失败！")
            return data
        time.sleep(3)

def get_output(data, stage_name):
    for s in data["stages"]:
        if s["name"] == stage_name: return s["output_data"]
    return None

# --- 开始测试 ---
print("🚀 [V2 测试] 启动：重构任务与自动回归验证")

# 1. 创建 Pipeline
res = requests.post(f"{BASE_URL}/pipeline/create", json={"requirement": REQUIREMENT}).json()
p_id = res["data"]["pipeline_id"]
print(f"\n✅ Pipeline 创建成功: ID {p_id}")

# 2. 审批架构 (REQUIREMENT)
wait_for_state(p_id, "paused", "REQUIREMENT")
print("\n\n架构师已完成分析。")
requests.post(f"{BASE_URL}/pipeline/{p_id}/approve", json={"notes": "架构拆解 OK"})

# 3. 第一次设计 (DESIGN) - 我们要在这里驳回它！
wait_for_state(p_id, "paused", "DESIGN")
design_output = get_output(requests.get(f"{BASE_URL}/pipeline/{p_id}/status").json()["data"], "DESIGN")
print("\n\n🎨 收到第一版技术设计。")
print(f"AI 原本的设计: {design_output.get('technical_design')[:100]}...")

# 模拟驳回逻辑
print("⚠️ [模拟驳回] 反馈：设计中没有体现对 CodeExecutorService 的复用，请重新检查代码库中关于备份路径的定义！")
requests.post(f"{BASE_URL}/pipeline/{p_id}/reject", json={
    "reason": "未遵循复用原则",
    "suggested_changes": "请查阅 backend/app/service/code_executor.py，复用其 BACKUP_DIR_NAME 属性，不要自己定义备份路径。"
}).json()

# 4. 等待自动回归后的第二次设计
print("\n🔄 AI 正在根据反馈进行自动回归（重新设计）...")
data = wait_for_state(p_id, "paused") # 驳回后会重新进入运行再进入暂停
new_design_output = get_output(data, "DESIGN")

print("\n\n🎨 收到回归后的技术设计：")
print(f"AI 修正后的设计: {new_design_output.get('technical_design')}")
input("\n方案已修正，按回车 [Approve] 开始编码...")
requests.post(f"{BASE_URL}/pipeline/{p_id}/approve", json={"notes": "修正后的设计非常出色，符合复用原则"})

# 5. 等待编码完成并检查结果
print("\n⌨️ Coder Agent 正在执行代码重构并推送 GitHub...")
final_data = wait_for_state(p_id, "success")

print("\n\n" + "="*50)
print("🎉 V2 全流程重构测试完成！")
print(f"交付分支: {final_data['delivery']['git_branch']}")
print(f"PR 链接: {final_data['delivery'].get('pr_url', '请去 GitHub 查看')}")
print("="*50)