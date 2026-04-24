import requests
import time
import json
import sys

# 配置
BASE_URL = "http://localhost:8000/api/v1"
# 更有挑战性的需求：要求跨文件操作
REQUIREMENT = """
实现一个系统信息查询功能：
1. 在 models/system.py 定义 SystemInfo 模型 (包含 uptime, os_version, python_version)。
2. 在 service/system_service.py 实现获取这些信息的逻辑。
3. 在 api/v1/system_info.py 暴露 GET /system/info 接口。
4. 在 main.py 中注册这个新路由。
必须严格遵守 api -> service -> models 的分层架构。
"""

def print_divider(title):
    print(f"\n{'='*20} {title} {'='*20}")

def wait_for_pipeline_state(pipeline_id, target_states=["paused", "success", "failed"]):
    """持续轮询直到进入目标状态"""
    while True:
        try:
            resp = requests.get(f"{BASE_URL}/pipeline/{pipeline_id}/status").json()
            if not resp.get("success"):
                print(f"❌ API 报错: {resp.get('error')}")
                return None
            
            data = resp.get("data")
            status = data.get("status")
            current_stage = data.get("current_stage")
            
            # 打印进度条效果
            sys.stdout.write(f"\r[Pipeline ID: {pipeline_id}] 阶段: {current_stage or 'INIT'} | 状态: {status}...")
            sys.stdout.flush()

            if status in target_states:
                print("\n") # 换行
                return data
            
            time.sleep(3)
        except Exception as e:
            print(f"\n❌ 请求异常: {e}")
            return None

def get_stage_output(data, stage_name):
    """提取特定阶段的输出数据"""
    for stage in data.get("stages", []):
        if stage["name"] == stage_name:
            return stage.get("output_data")
    return None

# --- 执行开始 ---
print_divider("OmniFlowAI 全流程端到端测试")

# 1. 提交需求
print(f"🚀 步骤 1: 提交开发需求...")
res = requests.post(f"{BASE_URL}/pipeline/create", json={"requirement": REQUIREMENT}).json()

if not res.get("success"):
    print(f"❌ 创建失败: {res.get('error')}")
    exit(1)

p_id = res["data"]["pipeline_id"]
print(f"✅ Pipeline 已创建: ID {p_id}")

# 2. 架构分析阶段
print_divider("阶段 1: 架构师需求拆解 (REQUIREMENT)")
data = wait_for_pipeline_state(p_id)
output = get_stage_output(data, "REQUIREMENT")

if output:
    print(f"🤖 AI 拆解方案:\n{json.dumps(output, indent=2, ensure_ascii=False)}")
    print(f"建议修改文件: {output.get('affected_files', [])}")

input("\n👉 请 Review 架构方案。按回车 [Approve] 继续...")
requests.post(f"{BASE_URL}/pipeline/{p_id}/approve", json={"notes": "架构方案符合八荣八耻规范"})

# 3. 技术设计阶段
print_divider("阶段 2: 设计师详细设计 (DESIGN)")
data = wait_for_pipeline_state(p_id)
output = get_stage_output(data, "DESIGN")

if output:
    print(f"🎨 AI 详细设计:\n{json.dumps(output, indent=2, ensure_ascii=False)}")
    print(f"设计逻辑: {output.get('logic_flow', '无')}")

input("\n👉 请 Review 技术细节。按回车 [Approve] 启动 AI 自动编码...")
requests.post(f"{BASE_URL}/pipeline/{p_id}/approve", json={"notes": "设计详尽，同意执行代码变更"})

# 4. 自动编码与交付阶段
print_divider("阶段 3: 编码、推送与 PR (CODING)")
print("⏳ Coder Agent 正在生成代码并尝试 Push 到 GitHub...")
final_data = wait_for_pipeline_state(p_id, target_states=["success", "failed"])

if final_data.get("status") == "success":
    print_divider("🎉 流程全部完成！")
    delivery = final_data.get("delivery", {})
    print(f"✅ 状态: 成功 (SUCCESS)")
    print(f"🌿 Git 分支: {delivery.get('git_branch')}")
    print(f"🔗 Commit Hash: {delivery.get('commit_hash')}")
    print(f"📝 变更摘要: {delivery.get('summary')}")
    
    if delivery.get("diff_summary"):
        print("\n--- 代码变更摘要 (Diff) ---")
        print(delivery.get("diff_summary")[:1000] + "...")
    
    print("\n🚀 [下一步]: 请前往 GitHub 仓库查看 PR 链接！")
    print(f"仓库地址: https://github.com/sennemmi/feishutemp/pulls")
else:
    print_divider("❌ 流程失败")
    print(json.dumps(final_data, indent=2, ensure_ascii=False))