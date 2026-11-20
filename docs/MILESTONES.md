# GradMatch 实施里程碑 v1.0

日期：2026-11-12  
项目位置：`D:\UW\EEP500d\GradMatch`  

Product language: English for the current application and every future user-facing feature, including agent replies and exported assessment text. See `AGENTS.md`.
依据：`docs/PROGRAM_DESIGN.md`、`Project_Proposal.md` 及课程要求

## 执行方式

项目分为 **8 个里程碑（M0–M7）**。每次只推进当前里程碑；先运行自动检查，再按该阶段的交互步骤验收，保存结果后进入下一阶段。当前阶段未通过时，先修复，不把后续功能堆到未验证的基础上。

每个里程碑交付五项：可运行的代码/资料、明确的验证命令、预期结果、实际验证记录、剩余限制。模型 API、公开部署和正式成绩都必须实际验证，不能用 mock、截图或预填结果代替。

状态分为：待开始、进行中、自动验收通过/待手动验收、已验收、受阻。自动检查成功和用户手动确认分开记录。阶段完成后停在该检查点汇报，不自动把后续所有阶段连续做完。

## 总览

| 阶段 | 交付能力 | 核心验证 | 依赖/费用 | 当前状态 |
| --- | --- | --- | --- | --- |
| M0 工程基础 | 独立 Python 环境、最小网页、SQLite 只读访问、测试入口 | 页面能启动、HTTP 健康检查、禁止数据库写入、断网运行检查 | 无 API 密钥，无调用费用 | 已验收（用户确认可正常打开） |
| M1 数据与规则 | 8–12 个真实项目、来源追溯、资格与费用计算 | 边界测试、来源抽查、预算变化后筛选结果正确 | 官网公开资料；不依赖收费模型 | 自动验收通过，待用户页面/来源抽查 |
| M2 固定基线与会话 | 表单、追问、结构化背景更新、一次推荐生成、统一验证 | 真实模型推荐与 70,000 → 50,000 更新，其他背景保留 | 需要选定模型并配置密钥，有 API 用量 | User-accepted on 2026-11-15 |
| M3 早期公开部署 | Streamlit 公共 URL、服务器端密钥与用户隔离 | 另一设备无痕访问，两用户独立，重启后基础库可恢复 | GitHub/Streamlit 账号，免费托管 | Passed: public URL, hosted model, isolation, reboot and user another-device check |
| M3.5 Recommendation pilot | Degree / GRE inputs, sourced tier explanation, full tuition and application checklist | Fictional profile: USD 140,000 → 100,000, preserved background, unsupported evidence blocked | Official sources; bounded real model checks | 107 checks, real local model and hosted loop passed; user acceptance pending |
| M4 ReAct 与实时工具 | 自适应工具调用、官方 HTML/PDF、暂停恢复与预算限制 | 缺证据会补查、失败能停止、真实官网核验 | 模型/搜索服务；计量真实费用 | Automated and user budget-update acceptance passed 2026-11-19; follow-up guard passed 146 offline checks |
| M5 显式规划 Agent | Plan-and-replan、计划版本与重规划日志 | 同一任务在工具失败/条件变化后调整计划 | 沿用同一模型、证据和预算 | Automated acceptance passed 2026-11-19: 181 checks, hosted generation/budget update and zero-call reuse; user page accepted 2026-11-19 |
| M6 数据集与评测工具 | 40–60 个项目、210 主任务、50 安全提示、可复现 runner | 数据一致性、参考答案隔离、断点继续、少量真实试运行 | 小规模 API 试运行 | M6.1c: 16 programs / 62 sources, 7 computable estimates; 246 checks passed; full M6 remains incomplete |
| M7 完整评测与发布验收 | 三组正式成绩、人工审计、云端最终验证、复现说明 | 630 次主任务 + 150 次安全运行，失败保留并汇总 | 正式运行 API 费用，按 pilot 估算 | 待开始 |

M3 提前部署，用于尽早发现云端限制；最终应用可用性在 M7 再验收。M6 的合成测试夹具和 mock 只用于检查 runner，不能计作 M7 的真实模型成绩。

## M0 — 工程基础

### 要做的内容

- 在已有仓库建立独立 Python 环境，锁定依赖；不改系统 PATH 和原 proposal。M0 初始为 3.11，M1 因本机应用控制限制改为已有可执行的 3.12，并重跑全部检查通过。
- 建立程序包、Streamlit 入口、脚本与测试目录。
- 创建空的 programs/sources 表；开发用数据库可由版本化 schema 重建。
- 页面以只读方式打开 SQLite，显示真实记录数；不写入虚构学校或推荐。
- 提供一个命令执行环境检查、页面交互检查和 HTTP 启动检查，并导出 JSON 记录。

### 自动验证

从项目根目录运行：

```powershell
.\.venv\Scripts\python.exe -m scripts.build_catalog
.\.venv\Scripts\python.exe -m scripts.verify_m0
```

预期：6 项集成检查全部通过，报告为 passed。检查覆盖只读连接不能修改数据库、缺失库不会被悄悄新建、损坏库被拒绝、构建脚本不覆盖已有数据、页面和按钮在外网连接被禁止时仍能运行，以及真实 Streamlit 进程的 HTTP 健康端点返回 200。

### 手动验证

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501
```

打开 `http://127.0.0.1:8501`：应看到 GradMatch、M0 状态、项目 0 条/证据 0 条。点击“运行基础检查”显示通过；刷新不报错。0 条表示尚未导入真实资料，不能被当成完整推荐系统。

### 完成门槛

自动检查通过且页面按上述步骤可访问；保存 Python/依赖版本和验证报告。此阶段不代表资格判断、模型推荐或公开部署完成。

## M1 — 数据与确定性规则

### 要做的内容

- 用 Pydantic 落实申请者、项目、证据、学费及检查结果 schema。
- 整理 8–12 个美国 CS/ECE 项目，区分同校不同学位/校区。
- 保存官网 URL、正文片段、获取日期、适用年份/intake 和来源 ID。
- 实现资料导入、字段覆盖报告、pass/fail/unknown/not_applicable 检查。
- 实现 Decimal 学费计算、预算上界检查、明确资格和 deadline 规则。
- 缺失学费/资格/分档资料如实标记，不先做四档推荐。

### 验证方法

命令入口：`python -m scripts.verify_m1`，同时运行该阶段的 pytest 和目录一致性检查；该入口在 M1 实现。

至少验证：1,500 USD/credit × 32 credits = 48,000 USD；50,000 预算通过、47,000 不通过；缺少学分数为 unknown；区间跨预算不能通过；不同 GPA 分制不擅自换算；英语必要单项缺失不能达标；资料错误 intake 被识别。人工逐一抽查引用是否确实支持字段。

### 完成门槛

至少 8 个真实项目可导入、来源可以追溯，规则和边界检查全部通过；输出覆盖报告，公开列出未知项。资格/预算检查可验证不等于已有充分录取风险证据。

## M2 — 固定基线与会话交互

### 要做的内容

- 页面接入背景表单、必要追问、聊天和 profile_version。
- 实现 ProfilePatch，仅更新用户明确修改的字段；使旧检查失效。
- 选定并接入一个真实模型，记录调用、tokens、耗时和费用；密钥只在环境配置中。
- 实现固定 top-k 检索、共享分档 rubric、一次推荐生成和统一验证器。
- 正式推荐、待核实候选和证据不足状态分别展示。

### 验证方法

命令入口：`python -m scripts.verify_m2`；确定性/模拟测试与 `--live-model` 的真实集成验证分别报告。后者未运行则不能宣称模型链路完成。

用虚构申请者完成推荐，预算 70,000 → 50,000 后 GPA、语言、目标和 intake 保持；不超预算；被移除的项目有原因。验证缺失关键信息先追问、伪造引用被拦截，以及“无资格通过候选”与“证据不够”不混淆。来源或录取证据不足时允许诚实短缺。

### 完成门槛

同一页面完成“输入 → 追问 → 真实模型生成 → 验证 → 预算修改”，并保存脱敏的合成任务日志。基线没有模型驱动的补查/修复循环，内部调用全部计费。

## M3 — 早期公开部署

### 要做的内容

- 将应用部署到 Streamlit Community Cloud，设置公开 URL。
- 部署版本内带可恢复的基础数据库/来源资料，应用只读。
- profile、对话和临时证据仅在各自会话中；不依赖临时磁盘保存历史。
- 配置 Secrets、并发限制、错误提示和可重现的启动说明。

### 验证方法

先执行已有自动回归，再用另一设备和无痕窗口实际验收：无开发者账号可打开、可以输入新条件、模型返回真实响应、预算修改有效。两窗口输入不同预算，彼此内容不串；应用重启后基础项目库仍可重建/加载，临时会话丢失按设计说明。

### 完成门槛

记录真实 URL、部署版本和手动检查结果。只有“可以部署”或本地 localhost 不算本阶段通过。账号登录或云端配置未完成时保持待验收，不虚报公共链接。

## M4 — ReAct、官网工具与恢复

### 要做的内容

- 完成五个共享工具及统一调度器。
- 加入官方 HTML/PDF 读取、来源版本、目标字段提取和冲突处理。
- 实现 ReAct 的行动/观察循环、追问暂停恢复、累计调用/时间预算。
- 搜索参数不包含完整个人背景；网络拒绝私网/元数据地址和越界重定向。
- snapshot 模式禁外网，live 模式明确实际核验日期和失败状态。

### 验证方法

命令入口：`python -m scripts.verify_m4`。使用可控缺失字段/错误页面：确认 Agent 根据观察补查，而非固定脚本；官方来源冲突时保留 unknown；恢复不会重复付费；耗尽预算确实停止；恶意网页不能修改用户条件或造成外传。

再进行至少一次真实官网读取，保留 URL、时间、片段和依赖该片段的结果。人工核对真实读取不是搜索摘要或伪造来源。

### 完成门槛

ReAct 可通过同一应用服务运行并有可审查的工具日志；安全/超时回归通过；至少一个真实 live 核验任务通过。与固定基线在相同 pilot 场景上可比较。

## M5 — Plan-and-replan

### 要做的内容

- 实现结构化计划、逐步执行、done_criteria 和最多 3 次重规划。
- 在用户条件更新、缺失证据、冲突或工具失败时调整计划。
- 与其他策略共用模型、数据、工具、约束、rubric、预算和最终验证器。
- 计划/重规划调用和工具内模型请求都纳入同一用量统计。

### 验证方法

命令入口：`python -m scripts.verify_m5`。正常任务能结束；故障注入任务产生有原因的计划 revision；没有变化不无故重规划；达到预算停止。日志明确三组策略差异，不能把固定步骤改个名字当成第二个 Agent。

### 完成门槛

三组可由同一入口运行同一 pilot 集，输出和计量格式一致；存在实际观察结果驱动的计划变化记录。不要求第二种 Agent 分数一定优于 ReAct。

## M6 — 完整资料、任务集与评测程序

### 要做的内容

- 扩展至 40–60 个项目，产出逐项目字段与分档证据覆盖报告。
- 构建 210 个有意义的不同主任务和至少 50 个不同安全提示，保存人工核对的参考规则。
- 固定快照、日期、配置、rubric 和任务版本；隔离 pilot 与正式场景家族。
- 实现脚本回复器、故障覆盖层、三组交错执行、断点继续及汇总。
- 参考规则不能提供给模型/工具；故障覆盖结构化事实和原文，不能泄露干净答案。
- 预先固定 30 个分层人工审计任务，提供盲审导出。

### 验证方法

命令入口：`python -m scripts.verify_m6`。检查 ID 唯一、数量和五类构成、oracle 一致性、资料版本及引用；用可控输出检查汇总的分子/分母，失败/超时不能消失；中断后恢复不重复覆盖结果；证明 snapshot 没有外网调用。

用少量 pilot 做真实模型预运行，确认成本、调用和耗时，再冻结正式参数；这批试运行不计作 210 个正式成绩。

### 完成门槛

正式集定义、资料覆盖报告、runner 回归全部通过；三组可对同一任务运行并导出一致格式；正式实验成本已根据真实 pilot 用量估算。尚未执行的成绩标记“待测”。

## M7 — 正式评测与最终程序验收

### 要做的内容

- 三组各运行 210 个主任务，首轮共 630 次；三组各运行 50 个安全提示，共 150 次。
- 保存全部失败、超时、预算耗尽和重试记录；不只报告成功执行。
- 输出任务成功率、平均轮数、平均/中位/p95 耗时、调用量、token、费用和安全处理率。
- 对 30 个主任务的三组输出进行盲审，对全部安全输出及相关工具记录复核。
- 完成公共应用和干净环境复现验收，保留完整版本与限制说明。

### 验证方法

使用设计文档中的 `run_benchmark`、`run_safety` 和 `summarize_results` 命令；检查每组是否覆盖 210/50 个不同 ID，汇总值是否能从原始记录重新计算。人工审计分子/分母和样本范围单列。

最后在公共 URL 重做“初次推荐 → 必要追问 → 预算改为 50,000 → 查询留下项目的找工匹配”；测试无匹配/证据不足、网络失败与两用户隔离。用锁定依赖和资料在干净环境启动。

### 完成门槛

三组真实运行和人工审计齐全，指标可重算，公共 URL 可交互，README 可指导复现。80% 任务成功率、95% 审计主张支持率和零已知硬约束违规是项目目标；未达到时如实记录、修复并按新版本重跑，不改参考规则来提高分数。

## 当前检查点

2026-11-20 M6.1d direction: expose all 83 imported leads for browsing/search/comparison, then deepen official-field coverage for 20–30 priority programs in batches of 10–15. This user-approved sequence supersedes the earlier 40–60 reviewed-program expansion target. The separate 210-task/50-safety evaluation gates remain. See `docs/DIRECTORY_PLAN.md`.

2026-11-15: M0 and M2 are user-accepted. M1's reviewed catalog and deterministic rules remain in use: 8 programs, 20 official sources, 3 computable tuition estimates and explicitly incomplete eligibility/goal/tier evidence. M2 real-model acceptance and the budget/follow-up workflow passed; its six-request development log is preserved separately.

M3 is complete: https://gradmatch-nathan-sie.streamlit.app/ . All 84 regression checks, anonymous access, real hosted model generation/update/follow-up, independent connection isolation, actual reboot recovery and the user another-device check passed. Cloud model acceptance used four requests, 43,501 input / 946 output tokens and an estimated USD 0.03688275. Cloud Secrets were entered by the user and are not in GitHub or exported artifacts. See `docs/verification/M3.md`.

`verify_m0`, `verify_m1`, `verify_m2`, `verify_m3`, `verify_m4`, `verify_m5` and `run_task` are implemented. M4 automated acceptance passed on 2026-11-19: shared tools, ReAct, registered HTML/PDF retrieval, session evidence, pause/resume and cumulative limits. The fresh six-request live task restored the missing credit evidence and a USD 50,850 tuition estimate, preserving eligibility gaps and the profile. The user-provided session confirms budget-update page acceptance; a subsequent premature-finish guard passed 146 offline checks without another model request. M5 plan/replan passed 181 checks and hosted acceptance on 2026-11-19. The four-request generation/budget-update task and zero-call reuse passed; earlier eight requests and failures are preserved. User page acceptance passed on 2026-11-19; M6.1a audit is complete. See `docs/verification/M61.md`. Broader tier evidence and final-project 210/50 evaluation remain later stages. See `docs/M5_SCOPE.md`. No final-project benchmark score is claimed. See `docs/M4_SCOPE.md` and `docs/verification/M4.md`.

2026-11-16 M3.5: the fixed baseline now has a verified small recommendation loop, explicit degree/GRE fields and full tuition accounting. Current seed: 10 programs / 30 sources. All 107 checks, clean-host recovery, the final local model pair and the actual hosted generation/budget-update pair passed. MSAII supplies one formal Lottery planning label; MCDS remains pending and Target/Safer lack comparable cases. Eight model requests across development and hosted acceptance cost an estimated USD 0.160275, including preserved failed development pairs. See `docs/verification/M35.md`. Stop for user acceptance before M4.
