# AGENTS.md — 文档规则

本仓库文档服务于"AI 连续开发"：文档必须是**当前事实的单一来源**，不是过程日志。

## 文档分层（一条事实只有一个家）

| 层 | 位置 | 放什么 | 不放什么 |
| --- | --- | --- | --- |
| 常驻规则 | `/AGENTS.md` | 每个会话都必须知道的 1–3 行规则 + 链接 | 故事、教程、易变细节 |
| 框架/宪法 | `docs/architecture/framework.md` | 分层、所有权、硬性不变量、改动落点决策 | 逐文件实现细节 |
| 能力矩阵 | `docs/architecture/feature-roadmap.md` | 能力状态、扩展 recipe、优先级 | 实现教程 |
| 模块规则 | 各目录 `AGENTS.md` | 该目录的改动规则/检查清单 | 仓库级规则（在根文件） |
| 接触点合同 | `docs/architecture/seams/*.md` | 上游包/文件/锚点/失败模式/迁移目标 | 泛泛介绍 |
| 兼容层清单 | `adaptation/compat.json` + `compat-layer.md` | 模块→消费者→gate→决策 | 运行日志 |
| 机器证据 | `docs/evidence/**` | gate/device/release 的 JSON 与 scoreboard | 手写叙述、凭据 |
| 方案/决策记录 | `docs/work/*.md` | 计划、调研、实施记录、历史 | 当前权威规则（会被 framework 覆盖） |
| 研究 | `docs/research/*.md` | 平台探索、可行性、实验结论 | 发布 runbook |

## 写作规则

- **写当前状态**：历史放 `docs/work`/提交；不要写"以后会…"（除非在 feature-roadmap 的待办表）。
- **可执行**：写命令、路径、gate 名、锚点名；不要只写"要小心"。
- **一处定义、多处链接**：规则在根/模块 AGENTS 或 framework；别处给链接。
- **中文为主，标识符用英文**：命令、路径、gate id、状态码保持原样。
- **证据不放文档正文**：正文引用 `docs/evidence/...` 的 JSON；不要把大段输出贴进文档。
- **敏感信息**：token、cookie、账号、私钥不得出现在文档/证据/提交里。
- **同改**：行为/接口/补丁变化时，同一提交更新对应模块 AGENTS、seam 合同、TARGETS、
  feature-roadmap 状态；只改代码不改文档视为未完成。

## 必须保持的入口

- 根 `AGENTS.md` 必须链接 `docs/architecture/framework.md` 与 `feature-roadmap.md`；
- `framework.md` 必须含分层、所有权、不变量、改动落点、门禁模型、已知边界；
- 每个模块目录必须有 `AGENTS.md`（由 `scripts/adaptation/guidance_check.py` 检查）；
- `docs/architecture/README.md` 必须索引 framework/roadmap/compat/seams/runbook/交付文档。

## 文档验证

- `python3 scripts/adaptation/guidance_check.py`（G1 `guidance-docs`）：检查必需文件与关键章节；
- `python3 scripts/adaptation/workflow_check.py`：检查 CI 与 gate 脚本接线；
- 修改文档后跑 `python3 gates/run.py --tier G0,G1`，并把证据写入台账。
