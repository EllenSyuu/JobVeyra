<h1 align="center">JobVeyra</h1>

<p align="center">
  <a href="../../README.md">English</a> ·
  <b>简体中文</b> ·
  <a href="README.zh-TW.md">繁體中文</a> ·
  <a href="README.ja.md">日本語</a> ·
  <a href="README.ko.md">한국어</a> ·
  <a href="README.fr.md">Français</a> ·
  <a href="README.es.md">Español</a> ·
  <a href="README.pt-BR.md">Português</a> ·
  <a href="README.de.md">Deutsch</a> ·
  <a href="README.it.md">Italiano</a> ·
  <a href="README.ru.md">Русский</a> ·
  <a href="README.ar.md">العربية</a> ·
  <a href="README.hi.md">हिन्दी</a>
</p>

<p align="center">
  一个开源的求职引擎：在你选定的地区寻找职位，为每个职位给出有依据的评分，准备诚实的申请材料，
  只提交你批准过的申请，并在每天早上告诉你哪些做法奏效了。
</p>

<p align="center">
  <a href="#quick-start">快速开始</a> ·
  <a href="#how-it-works">工作原理</a> ·
  <a href="#compared-with-other-tools">对比</a> ·
  <a href="../ARCHITECTURE.md">架构</a> ·
  <a href="../../AGENTS.md">智能体规则</a>
</p>

---

大多数求职智能体要么停在“提交”按钮之前，把点击留给你；要么对所有职位一律点击“提交”，然后听天由命。
JobVeyra 把选择权交给你，按工作区分别设置：

| `policy.submission` | 会发生什么 |
|---|---|
| `batch_approve`（默认） | 你在一个页面上审阅一批申请，并一次性批准。每次批准都针对职位的确切内容进行签名；如果职位内容发生变化，它会重新回到审阅流程。 |
| `auto` | 每个通过筛选条件、评分阈值和每日上限的职位都会被提交。 |
| `fill_only` | 只填写表单，并停在“提交”之前，由你亲自点击。 |

在任何模式下，只有在记录到雇主的确认信息后，一份申请才算真正发出。填好的表单、点过的按钮或很高的评分，
都不会被算作进展。

<a id="quick-start"></a>

## 快速开始

```bash
git clone https://github.com/EllenSyuu/JobVeyra.git && cd JobVeyra
pip install ".[charts]"            # Python 3.10+; charts need Pillow

jobveyra init ~/my-search && cd ~/my-search
# edit jobveyra.yml (who you are, where you want to work, policy, sources)
# write your fact base in cv/master.md
jobveyra doctor
jobveyra discover && jobveyra evaluate
jobveyra status
```

然后让智能体处理队列：

| 运行环境 | 配置 |
|---|---|
| Claude Code | `/plugin marketplace add EllenSyuu/JobVeyra`，然后 `/plugin install jobveyra@jobveyra`；命令为 `/jobveyra:search`、`/jobveyra:review`、`/jobveyra:apply`、`/jobveyra:digest` |
| Codex, OpenCode, Cursor, Gemini CLI, Copilot | 打开工作区即可；它们会读取 [`AGENTS.md`](../../AGENTS.md)（`GEMINI.md` 指向同一个文件） |
| 不使用智能体 | 每一步都是普通命令；参见 `jobveyra --help` |
| Docker | `docker build -t jobveyra .`，然后 `docker run --rm -v "$PWD:/workspace" jobveyra discover` |

## 聚焦任意地区

在哪里找工作属于配置，而不是代码。地区按顺序排列并带有权重；远程工作可以设为允许、必需或排除；
每个职位方向（一个 *track*）都有自己的职位关键词、有据可查的技能和简历版本。

```yaml
focus:
  regions:
    - {name: Lisbon, match: [lisbon, lisboa, portugal], weight: 1.0}
    - {name: Remote Europe, match: [remote - europe, emea], weight: 0.7}
  remote: allow
  tracks:
    - {key: ds, label: Data science, titles: [data scientist, machine learning],
       skills: [python, sql, statistics], cv: cv/data-science.md}
  seniority_min: junior
  seniority_max: senior
  salary_floor: 40000
  salary_currency: EUR
```

完整的带注释配置文件见 [`examples/jobveyra.yml`](../../examples/jobveyra.yml)。

<a id="how-it-works"></a>

## 工作原理

```
sources        Greenhouse, Lever, Ashby, Workable, SmartRecruiters,
     │         Recruitee, UN Careers, USAJOBS, Remotive, any page
     │         with schema.org JobPosting, LinkedIn alert emails
     ▼
discover       focus filters, dedup by requisition and content
     ▼
evaluate       legitimacy checks, eight scored dimensions with
     │         evidence, hard blockers, lane
     ▼
materials      fabrication guard, self-negative wording guard,
     │         ATS text check
     ▼
approve        batch review page and signed approval
     ▼
submit         an agent drives the browser; the CLI leases one
     │         job at a time and records only confirmed sends
     ▼
learn          outcomes, funnel, patterns, score calibration,
               skill demand, follow-ups, daily digest
```

每个职位都存放在同一个持久化队列中，任何时刻只有一个状态，并附带进入该状态的原因
（`discovered`、`excluded`、`eligible`、`ready_to_submit`、`in_progress`、`submitted`、
`needs_check`、`retry_wait`、`blocked_auth`、`blocked_human`、`blocked_technical`）。
非法的状态转换会被拒绝，租约会安全过期；如果在点击“提交”之后发生崩溃，该职位会变为 `needs_check`，
而不会产生重复申请。

## 功能

**发现**
- 十一个数据源适配器，全部使用公开、无需登录的接口，并带有重试、退避、按主机的速率限制和 robots.txt 检查。
  发现阶段不调用任何模型。
- 地区、远程、资历（支持英语、法语、西班牙语、葡萄牙语、德语职位名称）、雇佣类型、职位名称和雇主筛选；
  每次拒绝都会记录原因。
- 先按雇主和职位编号去重，再按职位内容去重。

**评估**
- 八个维度：技能、方向、资历、地点、语言、薪酬、时效、雇主。每个维度都附有按来源标注的证据：
  引自职位描述、读自结构化字段，或属于估计。仅由估计支撑的维度会被设上限。
- 在匹配技能之前，先把要求拆分为必需项和优先项。
- 硬性阻断项会直接终止评估：在你无法工作的市场不提供工作签证担保、要求你未达到 B2 及以上水平的语言、
  安全许可、雇佣类型、你要避开的雇主、已关闭的职位。
- 真实性信号：已关闭的职位、重复发布、过期职位、常年招聘的人才库、未写薪资、含糊的职位名称。
- 跨货币和计薪周期解析薪资，折算为年薪后与你的底线比较。
- 可选模型（Anthropic、OpenAI、Ollama 或任何兼容 OpenAI 的接口）可以补充语义层面的技能匹配，
  但其作用受限，并被标注为估计。任何调用之前，你的姓名、邮箱、电话和链接都会被遮蔽。

**申请材料**
- 防捏造检查：文档中的每个数字、日期、雇主、学位和证书都必须出现在你的事实库中。
- 自我贬低措辞检查，支持英语、法语、西班牙语和葡萄牙语。
- ATS 文本检查：关键词覆盖、联系方式、提取噪声。
- 求职信的切入角度只取自职位描述和你有据可查的技能。

**投递之后**
- 结果台账、包含首次回复时间的漏斗、按来源、招聘门户、方向和通道统计的回复规律（附置信区间），
  以及评分校准（Brier 分数、AUC），在你的阈值设置不当时提醒你。
- 汇总你看过的职位中的技能需求，以及与你的资料之间的差距。
- 到期的跟进事项附带草拟消息；截止日期导出为日历文件。
- 面试准备表、STAR+R 故事库（其中的指标必须注明来源），以及薪资谈判话术。

**报告**
- 每日邮件摘要，附带动画图表（在只显示第一帧的邮件客户端中同样可读），支持浅色和深色主题，并提供纯文本版本。
- 通过一个 webhook 设置即可推送到 Telegram、Slack、Discord 或 Teams。
- 可嵌入任意 Markdown 文件的状态区块，例如私有仓库的 README。

<a id="compared-with-other-tools"></a>

## 与其他工具的对比

依据各项目 2026 年 11 月的公开 README。欢迎指正。

| | JobVeyra | career-ops | LinkedIn AI Job Applier Ultimate | JobAppAgent |
|---|---|---|---|---|
| 提交方式 | 由你选择：批量批准、自动或仅填写 | 填写表单；由你提交 | 自动提交 | 逐份或按批批准；智能体停在提交之前 |
| 怎样算已申请 | 仅以雇主确认为准 | 未说明 | 未说明 | 仅以可见的确认为准 |
| 状态模型 | 单一持久化队列，11 种状态，租约，崩溃安全 | Markdown 追踪表 | YAML 结果文件 | 台账 |
| 批准与职位内容绑定 | 是（对内容哈希签名） | 不适用（由你提交） | 无批准步骤 | 批准覆盖所展示的内容，24 小时 |
| 数据源 | Greenhouse, Lever, Ashby, Workable, SmartRecruiters, Recruitee, UN Careers, USAJOBS, Remotive, schema.org 页面, LinkedIn 提醒邮件 | Ashby, Greenhouse, Lever, Wellfound, LinkedIn 提醒邮件 | LinkedIn, Indeed | 招聘网站和招聘页面目录 |
| 地区 | 每位用户自定义的有序、加权地区 | 搜索查询 | 搜索筛选 | 搜索筛选 |
| 评分 | 0–100，覆盖 8 个维度，每个维度标注证据来源，估计值设上限 | 1–5，覆盖 A–H 模块，标注证据来源，估计值设上限 | 1–100 兴趣分 | 匹配度评分 |
| 真实性检查 | 已关闭、重复发布、过期、常年招聘、未写薪资、职位名称含糊 | 存活检查、重复发布、真实性模块 | 未说明 | 在招职位检查 |
| 防捏造检查 | 数字、日期、雇主、学位、证书 | 数字和事实 | 跳过无法回答的问题 | 仅使用已核实的事实 |
| 评分校准 | Brier、AUC、阈值建议 | 建议性校准 | 未说明 | 未说明 |
| 结果分析 | 漏斗、带区间的规律、技能需求 | 漏斗、规律、技能差距 | 技能统计 | 结果台账 |
| 每日报告 | 邮件摘要、Telegram、webhook | 未说明 | Telegram | 未说明 |
| 是否需要模型 | 否（可选，且会遮蔽个人信息） | 需要 AI CLI 或评估器 | 是 | 需要编程智能体 |
| 运行环境 | Claude Code 插件、支持 AGENTS.md 的 CLI、Docker、普通 CLI | 多种 AI CLI、Docker | Python 应用、Docker | 智能体技能加 CLI |

其他工具目前领先的地方：career-ops 拥有庞大的社区、交互式终端仪表盘、公司调研和外联草稿功能，
以及 18 种语言的 README；LinkedIn applier 能直接自动化 LinkedIn 和 Indeed，并提供本地网页控制面板；
JobAppAgent 通过可选的云端后端支持多主机共享状态。

## 隐私

你的数据保存在你的工作区中，绝不会进入本仓库。`jobveyra init` 会写入一个排除整个工作区的 `.gitignore`。
没有遥测，没有后端。模型调用默认关闭，开启时也会遮蔽个人信息。本引擎从不输入密码、不破解验证码、
不创建账户、不接受法律声明，除你自己的摘要外也不发送任何邮件。

## 开发

```bash
pip install -e ".[dev]"
pytest -q
```

模块约定见 [`docs/ARCHITECTURE.md`](../ARCHITECTURE.md)。测试离线运行，每个数据源都有录制好的测试数据。

## 许可证

MIT。参见 [`LICENSE`](../../LICENSE) 和 [`NOTICE`](../../NOTICE)。

---

> 以[英文 README](../../README.md) 为准；各语言译本可能滞后于英文版本。
