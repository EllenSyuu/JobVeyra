<h1 align="center">JobVeyra</h1>

<p align="center">
  <a href="../../README.md">English</a> ·
  <a href="README.zh-CN.md">简体中文</a> ·
  <b>繁體中文</b> ·
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
  一個開源的求職引擎：在你選定的地區尋找職缺，為每個職缺提出有根據的評分，準備誠實的應徵資料，
  只送出你核准過的應徵，並在每天早上告訴你哪些做法有效。
</p>

<p align="center">
  <a href="#quick-start">快速開始</a> ·
  <a href="#how-it-works">運作方式</a> ·
  <a href="#compared-with-other-tools">比較</a> ·
  <a href="../ARCHITECTURE.md">架構</a> ·
  <a href="../../AGENTS.md">代理規則</a>
</p>

---

多數求職代理不是停在「送出」按鈕之前，把點擊留給你；就是對所有職缺一律按下「送出」，然後聽天由命。
JobVeyra 把選擇權交給你，依工作區分別設定：

| `policy.submission` | 會發生什麼 |
|---|---|
| `batch_approve`（預設） | 你在一個頁面上審閱一批應徵，並一次核准。每次核准都針對職缺的確切內容進行簽章；若職缺內容有變動，它會重新回到審閱流程。 |
| `auto` | 每個通過篩選條件、評分門檻和每日上限的職缺都會被送出。 |
| `fill_only` | 只填寫表單，並停在「送出」之前，由你親自按下。 |

在任何模式下，只有在記錄到雇主的確認訊息後，一份應徵才算真正送出。填好的表單、按過的按鈕或很高的評分，
都不會被算作進展。

<a id="quick-start"></a>

## 快速開始

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

接著讓代理處理佇列：

| 執行環境 | 設定 |
|---|---|
| Claude Code | `/plugin marketplace add EllenSyuu/JobVeyra`，然後 `/plugin install jobveyra@jobveyra`；指令為 `/jobveyra:search`、`/jobveyra:review`、`/jobveyra:apply`、`/jobveyra:digest` |
| Codex, OpenCode, Cursor, Gemini CLI, Copilot | 開啟工作區即可；它們會讀取 [`AGENTS.md`](../../AGENTS.md)（`GEMINI.md` 指向同一個檔案） |
| 不使用代理 | 每一步都是一般指令；請見 `jobveyra --help` |
| Docker | `docker build -t jobveyra .`，然後 `docker run --rm -v "$PWD:/workspace" jobveyra discover` |

## 聚焦任何地區

在哪裡找工作屬於設定，而不是程式碼。地區依序排列並帶有權重；遠端工作可以設為允許、必要或排除；
每個職務方向（一個 *track*）都有自己的職稱關鍵字、有憑據的技能和履歷版本。

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

完整的附註解設定檔請見 [`examples/jobveyra.yml`](../../examples/jobveyra.yml)。

<a id="how-it-works"></a>

## 運作方式

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

每個職缺都存放在同一個持久化佇列中，任何時刻只有一個狀態，並附上進入該狀態的原因
（`discovered`、`excluded`、`eligible`、`ready_to_submit`、`in_progress`、`submitted`、
`needs_check`、`retry_wait`、`blocked_auth`、`blocked_human`、`blocked_technical`）。
不合法的狀態轉換會被拒絕，租約會安全地到期；若在按下「送出」之後發生當機，該職缺會變成 `needs_check`，
而不會產生重複應徵。

## 功能

**搜尋**
- 十一個資料來源轉接器，全部使用公開、免登入的端點，並具備重試、退避、依主機的速率限制和 robots.txt 檢查。
  搜尋階段不呼叫任何模型。
- 地區、遠端、年資（支援英文、法文、西班牙文、葡萄牙文、德文職稱）、僱用類型、職稱和雇主篩選；
  每次排除都會記錄原因。
- 先依雇主和職缺編號去除重複，再依職缺內容去除重複。

**評估**
- 八個面向：技能、方向、年資、地點、語言、薪酬、新鮮度、雇主。每個面向都附有依來源標記的證據：
  引自職缺說明、讀自結構化欄位，或屬於估計。只由估計支撐的面向會被設上限。
- 在比對技能之前，先把條件拆分為必要條件和加分條件。
- 硬性阻擋條件會直接終止評估：在你無法工作的市場不提供工作簽證擔保、要求你未達 B2 以上程度的語言、
  安全許可、僱用類型、你要避開的雇主、已關閉的職缺。
- 真實性訊號：已關閉的職缺、重複刊登、過期職缺、長期招募的人才庫、未標示薪資、模糊的職稱。
- 跨幣別和計薪週期解析薪資，換算為年薪後與你的底線比較。
- 選用模型（Anthropic、OpenAI、Ollama 或任何相容 OpenAI 的端點）可以補充語意層面的技能比對，
  但作用受限，並標記為估計。任何呼叫之前，你的姓名、電子郵件、電話和連結都會被遮蔽。

**應徵資料**
- 防捏造檢查：文件中的每個數字、日期、雇主、學位和證照都必須出現在你的事實庫中。
- 自我貶低用語檢查，支援英文、法文、西班牙文和葡萄牙文。
- ATS 文字檢查：關鍵字涵蓋率、聯絡資訊、擷取雜訊。
- 求職信的切入角度只取自職缺說明和你有憑據的技能。

**應徵之後**
- 結果帳冊、包含首次回覆時間的漏斗、依來源、求職平台、方向和管道統計的回覆模式（附信賴區間），
  以及評分校準（Brier 分數、AUC），在你的門檻設定不當時提醒你。
- 彙整你看過的職缺中的技能需求，以及與你的資料之間的差距。
- 到期的追蹤事項附帶草擬訊息；截止日期匯出為行事曆檔案。
- 面試準備表、STAR+R 故事庫（其中的指標必須註明出處），以及薪資談判話術。

**報告**
- 每日電子郵件摘要，附帶動畫圖表（在只顯示第一格畫面的郵件用戶端中同樣可讀），支援淺色和深色主題，並提供純文字版本。
- 透過一個 webhook 設定即可推送到 Telegram、Slack、Discord 或 Teams。
- 可嵌入任何 Markdown 檔案的狀態區塊，例如私有儲存庫的 README。

<a id="compared-with-other-tools"></a>

## 與其他工具的比較

依據各專案 2026 年 11 月的公開 README。歡迎指正。

| | JobVeyra | career-ops | LinkedIn AI Job Applier Ultimate | JobAppAgent |
|---|---|---|---|---|
| 送出方式 | 由你選擇：批次核准、自動或僅填寫 | 填寫表單；由你送出 | 自動送出 | 逐份或批次核准；代理停在送出之前 |
| 怎樣才算已應徵 | 僅以雇主確認為準 | 未說明 | 未說明 | 僅以可見的確認為準 |
| 狀態模型 | 單一持久化佇列，11 種狀態，租約，當機安全 | Markdown 追蹤表 | YAML 結果檔 | 帳冊 |
| 核准與職缺內容綁定 | 是（對內容雜湊簽章） | 不適用（由你送出） | 無核准步驟 | 核准涵蓋所顯示的內容，24 小時 |
| 資料來源 | Greenhouse, Lever, Ashby, Workable, SmartRecruiters, Recruitee, UN Careers, USAJOBS, Remotive, schema.org 頁面, LinkedIn 通知郵件 | Ashby, Greenhouse, Lever, Wellfound, LinkedIn 通知郵件 | LinkedIn, Indeed | 求職網站和徵才頁面目錄 |
| 地區 | 每位使用者自訂的有序、加權地區 | 搜尋查詢 | 搜尋篩選 | 搜尋篩選 |
| 評分 | 0–100，涵蓋 8 個面向，每個面向標記證據來源，估計值設上限 | 1–5，涵蓋 A–H 區塊，標記證據來源，估計值設上限 | 1–100 興趣分數 | 適配度分數 |
| 真實性檢查 | 已關閉、重複刊登、過期、長期招募、未標示薪資、職稱模糊 | 存活檢查、重複刊登、真實性區塊 | 未說明 | 有效職缺檢查 |
| 防捏造檢查 | 數字、日期、雇主、學位、證照 | 數字和事實 | 略過無法回答的問題 | 僅使用已查證的事實 |
| 評分校準 | Brier、AUC、門檻建議 | 建議性校準 | 未說明 | 未說明 |
| 結果分析 | 漏斗、附區間的模式、技能需求 | 漏斗、模式、技能落差 | 技能統計 | 結果帳冊 |
| 每日報告 | 電子郵件摘要、Telegram、webhook | 未說明 | Telegram | 未說明 |
| 是否需要模型 | 否（選用，且會遮蔽個資） | 需要 AI CLI 或評估器 | 是 | 需要程式設計代理 |
| 執行環境 | Claude Code 外掛、支援 AGENTS.md 的 CLI、Docker、一般 CLI | 多種 AI CLI、Docker | Python 應用程式、Docker | 代理技能加 CLI |

其他工具目前領先之處：career-ops 擁有龐大的社群、互動式終端機儀表板、公司研究和聯繫草稿功能，
以及 18 種語言的 README；LinkedIn applier 能直接自動化 LinkedIn 和 Indeed，並提供本機網頁控制面板；
JobAppAgent 透過選用的雲端後端支援多主機共用狀態。

## 隱私

你的資料保存在你的工作區中，絕不會進入本儲存庫。`jobveyra init` 會寫入一個排除整個工作區的 `.gitignore`。
沒有遙測，沒有後端。模型呼叫預設關閉，開啟時也會遮蔽個資。本引擎從不輸入密碼、不破解驗證碼、
不建立帳號、不接受法律聲明，除了你自己的摘要之外也不寄送任何電子郵件。

## 開發

```bash
pip install -e ".[dev]"
pytest -q
```

模組約定請見 [`docs/ARCHITECTURE.md`](../ARCHITECTURE.md)。測試離線執行，每個資料來源都有錄製好的測試資料。

## 授權

MIT。請見 [`LICENSE`](../../LICENSE) 和 [`NOTICE`](../../NOTICE)。

---

> 以[英文 README](../../README.md) 為準；各語言譯本可能落後於英文版本。
