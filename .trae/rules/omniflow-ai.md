
我们现在开始构建 OmniFlowAI：一个 AI 驱动的研发全流程引擎。
当前环境：
- Conda 环境名: omniflowai
- Python 版本: 3.11
## 八荣八耻
瞎猜接口🚫 → 查Swagger/源码再写
模糊执行🚫 → 需求不明先注释TODO(human)
臆想业务🚫 → 不确定逻辑必须暂停确认
创造接口🚫 → 先搜api/目录是否已有
跳过验证🚫 → Agent输出必须Pydantic校验
破坏架构🚫 → 严守分层，禁止越层调用
假装理解🚫 → 不熟悉的库注释说明
盲目修改🚫 → 改文件前读懂全部上下文


## 架构分层（铁律）
```
api/ → service/ → agents/（唯一能调LLM的地方）
                ↓
            models/（只定表结构）
```
## 关键禁止
- 禁止在agents/外直接调用litellm/openai
- 禁止any类型，禁止硬编码密钥
- 禁止在非pages/组件里fetch数据
- 禁止吞掉异常（except: pass）
- Agent输出必须剥离markdown再parse JSON
## 版本锁定
python=3.11 fastapi=0.115 sqlmodel=0.0.21
langgraph=0.2 litellm=1.51 celery=5.4
react=18.3 vite=5.4 typescript=5.6
reactflow=11.11 zustand=5.0 tanstack-query=5.59
## 响应格式
所有API统一返回 `{success, data, error, request_id}`
- **极简风格**：优先使用函数式组件和 Hooks。
- **状态管理**：小型状态用 Zustand，服务器缓存用 TanStack Query，禁止混用。
- **样式规范**：只允许使用 Tailwind CSS 原子类，禁止新建 .css 文件。
- **代码提交**：每完成一个子功能（如：Pipeline 启动接口），立即请求用户确认并执行 Git Commit，备注清晰。