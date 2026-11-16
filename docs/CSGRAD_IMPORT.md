# CS Grad tracker 获取与候选导入

核查日期：2026-11-12  
状态：已完成获取、独立 SQLite 候选导入及重复导入验证；尚未进行大学官网事实核验，不计为完整 M1 验收。

## 已定位的数据入口

tracker 页面：https://csgrad.com/tracker  
公开项目仓库：https://github.com/csms-apply/csgrad  
结构化数据文件：`src/lib/tracker/school-list.json`  
页面源码 `src/pages/tracker.jsx` 直接 import 此 JSON，因此不需要逐行解析网页，也不需要登录或逐个打开 83 个学校介绍页才能取得清单。

本次固定上游提交为 `a60f321365c0f00594e4d593de6f0383428bd59d`，不依赖随时变化的 main：

https://raw.githubusercontent.com/csms-apply/csgrad/a60f321365c0f00594e4d593de6f0383428bd59d/src/lib/tracker/school-list.json

实际读到的元数据：`generated = 2026-10-25`、`cycle = Fall 2027`、`rows = 83`，83 个来源 ID 唯一。这里的日期是上游数据的生成标记，不是我们已经核实了所有大学官网。

## 获取与导入命令

在项目目录运行；过程不调用模型或搜索 API。第一条下载一个公开文件，导入脚本本身只处理本地 JSON，不访问网络。

```powershell
Set-Location -LiteralPath 'D:\UW\EEP500d\GradMatch'
New-Item -ItemType Directory -Path work -Force | Out-Null
Invoke-WebRequest -Uri 'https://raw.githubusercontent.com/csms-apply/csgrad/a60f321365c0f00594e4d593de6f0383428bd59d/src/lib/tracker/school-list.json' -OutFile 'work/csgrad-school-list.json'
.\.venv\Scripts\python.exe -m scripts.import_csgrad_candidates --input work/csgrad-school-list.json --source-commit a60f321365c0f00594e4d593de6f0383428bd59d --report work/csgrad_import_report.json
```

脚本：`scripts/import_csgrad_candidates.py`  
候选数据库：`work/csgrad_candidates.db`  
原始文件：`work/csgrad-school-list.json`  
导入报告：`work/csgrad_import_report.json`

使用同一文件重复执行不会增加重复行。将来更换提交或 intake 前先检查上游 schema/数量变化，不能把现有 source_id 当作我们永久不变的 program_id；来源 ID 含其梯队前缀，重新分组时可能变化。

## SQLite 保存什么

候选数据库有两张表：`candidate_programs` 与 `import_manifests`。它与应用基础库 `data/gradmatch.db` 分开，导入脚本拒绝直接以应用基础库为目标。

| 上游字段 | 候选中保存的含义 |
| --- | --- |
| `id`、`name` | 来源 ID 与显示名称 |
| `schoolFull`、`official` | 来源报告的学校及项目全名，等待身份核实 |
| `site`、`apply` | 项目主页与申请入口线索，尚未独立验证 |
| `tier` | CS Grad 自己的项目梯队，存为 source_tier |
| `halt` | 来源报告本季停招与否，不冒充我们核实过的状态 |
| `rounds` | 原样保留轮次、日期和适用说明，不把所有日期混成一个 ddl |
| `gre` | 来源的 GRE 要求标记 |
| `lang` | 旧版/新版托福、雅思等原始值及 kind，保留硬门槛/建议/未知区别 |
| `fee` | 申请费原始值，不能作为 tuition；币种在未核实前保持未知 |
| 生成日期、提交、SHA256、来源 URL | 可追溯元数据；导入时间与资料生成年份分开 |

每条候选均为 `verification_status = community_unverified`、`recommendation_eligible = 0`。`tuition_total_usd` 和 `personalized_tier` 为空，不能因导入而自动变成“预算通过”或四档推荐。

## 实际验证结果

- 第一次导入：83 条；83 个唯一来源 ID。
- 第二次导入同一文件：仍为 83 条。
- 来源标记停招：4 条，保留待复核标记。
- 正式推荐资格：0 条；本次未核验资格、学费或录取风险。
- 应用基础库 SHA256 前后相同，未修改其数据；原 M0 页面仍显示 0 项目/0 来源。
- 新增候选导入测试和原 M0 回归合计：**10 passed in 1.78s**。

可在 SQLite 查看工具中打开候选库，执行：

```sql
SELECT COUNT(*) FROM candidate_programs; -- 83
SELECT COUNT(*) FROM candidate_programs WHERE source_reports_halted = 1; -- 4
SELECT COUNT(*) FROM candidate_programs WHERE recommendation_eligible = 1; -- 0
SELECT display_name, school_name, source_tier, verification_status
FROM candidate_programs
ORDER BY display_name;
```

自动回归命令：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

## 从 83 条候选到 M1 的正式库

1. 保留 83 条作为候选清单，检查硕士/博士录取路径、学科、校区和 track，不直接宣布 83 个都符合项目范围。
2. 先选 8–12 个有代表性的项目，逐个核对官网身份、Fall 2027 招生、语言/先修要求、学费和 deadline。
3. 将核实后的稳定项目身份写入主库 programs，将实际读取的官方证据写入 sources；社区数据仍带来源和不确定状态。
4. 完成费用/资格规则及相应检查，才算 M1 通过。后续扩展到 40–60 个已整理项目，不要求立即核实全部 83 条。

尤其不能把源站 SSS/SS/A/B 梯队直接转换成 Lottery/Reach/Target/Safer。前者是源站的项目分组，后者必须结合申请者背景和允许使用的录取证据判断。该 JSON 没有全项目 tuition 数据，申请费不能填进学费字段。

## 来源说明

保留 CS Grad、项目仓库、文件路径、版本和来源 URL。CS Grad 首页显示 CC BY-NC-SA 4.0 标注；公开分发源站内容时仍须核对适用范围并保留相应归属和许可信息，不能因为代码在 GitHub 就默认全部内容属于 MIT 或可任意复用。

另外，CS Grad DataPoints（DP）有单独的禁止自动采集和衍生数据库使用政策。本次没有访问其 DP 数据接口或采集录取记录，tracker 项目清单不能被当作 DP 授权。后续风险分档需要另找允许复用的证据。

参考：

- https://csgrad.com/tracker
- https://github.com/csms-apply/csgrad/blob/a60f321365c0f00594e4d593de6f0383428bd59d/src/lib/tracker/school-list.json
- https://github.com/csms-apply/csgrad/blob/a60f321365c0f00594e4d593de6f0383428bd59d/src/pages/tracker.jsx
- https://csgrad.com/
- https://csgrad.com/robots.txt
- https://csgrad.com/dp-use-policy.txt
