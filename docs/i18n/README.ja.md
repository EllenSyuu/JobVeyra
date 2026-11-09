<h1 align="center">JobVeyra</h1>

<p align="center">
  <a href="../../README.md">English</a> ·
  <a href="README.zh-CN.md">简体中文</a> ·
  <a href="README.zh-TW.md">繁體中文</a> ·
  <b>日本語</b> ·
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
  オープンソースの求職エンジンです。あなたが選んだ地域で求人を探し、根拠に基づいて一件ずつ評価し、
  誠実な応募書類を準備し、あなたが承認したものだけを提出し、何がうまくいったかを毎朝お知らせします。
</p>

<p align="center">
  <a href="#quick-start">クイックスタート</a> ·
  <a href="#how-it-works">仕組み</a> ·
  <a href="#compared-with-other-tools">比較</a> ·
  <a href="../ARCHITECTURE.md">アーキテクチャ</a> ·
  <a href="../../AGENTS.md">エージェントのルール</a>
</p>

---

ほとんどの求職エージェントは、「送信」の手前で止まってクリックをあなたに任せるか、すべての求人で「送信」を
押して運任せにするかのどちらかです。JobVeyra では、ワークスペースごとにあなたが選べます。

| `policy.submission` | 動作 |
|---|---|
| `batch_approve`（デフォルト） | 応募のバッチを一覧にした 1 ページを確認し、一度で承認します。各承認は求人の内容そのものに対して署名されるため、求人内容が変わると再び確認待ちに戻ります。 |
| `auto` | フィルター、スコアのしきい値、1 日の上限をすべて満たした求人はすべて提出されます。 |
| `fill_only` | フォームを入力し、「送信」の手前で止まります。送信ボタンはあなたが押します。 |

どのモードでも、応募が送信済みとみなされるのは、雇用主からの確認が記録されたときだけです。入力済みのフォーム、
クリックされたボタン、高いスコアが進捗として数えられることはありません。

<a id="quick-start"></a>

## クイックスタート

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

あとはエージェントにキューを処理させます。

| ランタイム | セットアップ |
|---|---|
| Claude Code | `/plugin marketplace add EllenSyuu/JobVeyra` の後に `/plugin install jobveyra@jobveyra`。コマンドは `/jobveyra:search`、`/jobveyra:review`、`/jobveyra:apply`、`/jobveyra:digest` |
| Codex, OpenCode, Cursor, Gemini CLI, Copilot | ワークスペースを開くだけです。各ツールが [`AGENTS.md`](../../AGENTS.md) を読み込みます（`GEMINI.md` も同じファイルを指しています） |
| エージェントなし | すべてのステップが通常のコマンドです。`jobveyra --help` を参照してください |
| Docker | `docker build -t jobveyra .` の後に `docker run --rm -v "$PWD:/workspace" jobveyra discover` |

## どこにでもフォーカス

どこで探すかはコードではなく設定で決まります。地域には順序と重みを付けられ、リモートワークは許可・必須・除外を
選べます。また、職種ファミリー（*track*）ごとに、独自の職名キーワード、裏付けのあるスキル、CV のバリエーションを
持たせられます。

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

注釈付きの完全な設定ファイルは [`examples/jobveyra.yml`](../../examples/jobveyra.yml) です。

<a id="how-it-works"></a>

## 仕組み

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

すべての求人は 1 つの永続キューに格納され、常にちょうど 1 つの状態とその理由を持ちます
（`discovered`、`excluded`、`eligible`、`ready_to_submit`、`in_progress`、`submitted`、
`needs_check`、`retry_wait`、`blocked_auth`、`blocked_human`、`blocked_technical`）。
不正な状態遷移は拒否され、リースは安全に期限切れになります。「送信」クリック後にクラッシュしても、重複応募には
ならず `needs_check` になります。

## できること

**求人の発見**
- 11 種類のソースアダプター。いずれもログイン不要の公開エンドポイントを使い、リトライ、バックオフ、ホストごとの
  レート制限、robots.txt のチェックを備えています。発見段階ではモデル呼び出しは発生しません。
- 地域、リモート、シニアリティ（英語・フランス語・スペイン語・ポルトガル語・ドイツ語の職名に対応）、雇用形態、
  職名、雇用主のフィルター。除外するたびにその理由が記録されます。
- 雇用主と求人 ID による重複排除の後、求人内容による重複排除を行います。

**評価**
- 8 つの評価軸：スキル、トラック、シニアリティ、勤務地、言語、報酬、鮮度、雇用主。各評価軸には、根拠の種別
  （求人票からの引用、構造化フィールドからの読み取り、推定）が付いた証拠が添えられます。推定だけに基づく評価軸には
  上限が設けられます。
- スキルを照合する前に、要件を必須と歓迎に分けます。
- ハードブロッカーに該当すると評価はその場で終了します：働く資格のない市場でビザスポンサーがない、B2 以上で
  話せない言語が必須、セキュリティクリアランス、雇用形態、避けたい雇用主、募集終了の求人。
- 信頼性シグナル：募集終了、再掲載、古い求人、常時募集のタレントプール、給与の記載なし、曖昧な職名。
- 通貨や支払い周期をまたいで給与を解析し、年額に換算してあなたの下限と比較します。
- オプションのモデル（Anthropic、OpenAI、Ollama、または OpenAI 互換の任意のエンドポイント）で意味的なスキル照合を
  追加できますが、影響は限定され、推定として明示されます。呼び出しの前に、氏名、メールアドレス、電話番号、リンクは
  マスクされます。

**応募書類**
- 捏造ガード：書類に含まれるすべての数値、日付、雇用主、学位、資格は、あなたのファクトベースに存在しなければ
  なりません。
- 自己否定的な表現のガード（英語・フランス語・スペイン語・ポルトガル語）。
- ATS テキストチェック：キーワードの網羅率、連絡先、抽出ノイズ。
- カバーレターの切り口は、求人票と、裏付けのあるあなたのスキルだけから導きます。

**応募した後**
- 結果台帳、初回返信までの時間を含むファネル、ソース・応募ポータル・トラック・レーン別の反応パターン（信頼区間付き）、
  そしてしきい値が適切でないときに教えてくれるスコア較正（Brier スコア、AUC）。
- 閲覧した求人全体のスキル需要と、あなたのプロフィールとのギャップ。
- 期限が来たフォローアップとその下書きメッセージ。締め切りはカレンダーファイルとして出力。
- 面接準備シート、指標に必ず出典を求める STAR+R ストーリーバンク、そして条件交渉のスクリプト。

**レポート**
- 毎日のメールダイジェスト。最初のフレームしか表示しないメールクライアントでも読めるアニメーションチャート、
  ライト／ダークテーマ、プレーンテキスト版付き。
- 1 つの webhook 設定で Telegram、Slack、Discord、Teams に通知。
- 非公開リポジトリの README など、任意の Markdown ファイルに埋め込めるステータスブロック。

<a id="compared-with-other-tools"></a>

## 他のツールとの比較

2026 年 11 月時点の各プロジェクトの公開 README に基づいています。訂正を歓迎します。

| | JobVeyra | career-ops | LinkedIn AI Job Applier Ultimate | JobAppAgent |
|---|---|---|---|---|
| 提出方法 | 選択式：バッチ承認、自動、入力のみ | フォーム入力のみ。提出はユーザー | 自動提出 | 応募ごとまたはバッチで承認。エージェントは提出前で停止 |
| 「応募済み」の基準 | 雇用主の確認のみ | 記載なし | 記載なし | 目に見える確認のみ |
| 状態モデル | 単一の永続キュー、11 状態、リース、クラッシュセーフ | Markdown トラッカー | YAML の結果ファイル | 台帳 |
| 求人内容に紐づく承認 | あり（内容ハッシュに署名） | 該当なし（ユーザーが提出） | 承認ステップなし | 表示された内容に対する承認、24 時間 |
| ソース | Greenhouse, Lever, Ashby, Workable, SmartRecruiters, Recruitee, UN Careers, USAJOBS, Remotive, schema.org ページ, LinkedIn アラートメール | Ashby, Greenhouse, Lever, Wellfound, LinkedIn アラートメール | LinkedIn, Indeed | 求人サイトと採用ページのカタログ |
| 地域 | ユーザーごとの順序付き・重み付き地域 | 検索クエリ | 検索フィルター | 検索フィルター |
| スコアリング | 8 軸で 0–100、評価軸ごとの根拠種別、推定の上限 | ブロック A–H で 1–5、根拠種別、推定の上限 | 1–100 の関心スコア | 適合スコア |
| 信頼性チェック | 募集終了、再掲載、古い求人、常時募集、給与なし、曖昧な職名 | 掲載確認、再掲載、信頼性ブロック | 記載なし | 掲載中かのチェック |
| 捏造ガード | 数値、日付、雇用主、学位、資格 | 数値と事実 | 答えられない質問はスキップ | 検証済みの事実のみ |
| スコア較正 | Brier、AUC、しきい値の助言 | 助言的な較正 | 記載なし | 記載なし |
| 結果分析 | ファネル、区間付きパターン、スキル需要 | ファネル、パターン、スキルギャップ | スキル統計 | 結果台帳 |
| 日次レポート | メールダイジェスト、Telegram、webhook | 記載なし | Telegram | 記載なし |
| モデルの要否 | 不要（オプション、マスク処理あり） | AI CLI または評価器 | 必要 | コーディングエージェント |
| ランタイム | Claude Code プラグイン、AGENTS.md 対応 CLI、Docker、通常の CLI | 多数の AI CLI、Docker | Python アプリ、Docker | エージェントスキルと CLI |

現時点で他のツールが先行している点：career-ops には大きなコミュニティ、対話型のターミナルダッシュボード、
企業リサーチとアウトリーチ文面の作成機能、そして 18 言語の README があります。LinkedIn applier は LinkedIn と
Indeed を直接自動化し、ローカルの Web コントロールパネルを備えています。JobAppAgent はオプションのクラウド
バックエンドを通じて複数ホスト間での状態共有に対応しています。

## プライバシー

あなたのデータはワークスペースに保存され、このリポジトリに入ることはありません。`jobveyra init` はワークスペース
全体を除外する `.gitignore` を書き出します。テレメトリもバックエンドもありません。モデル呼び出しはデフォルトで
オフで、オンにした場合もマスク処理されます。このエンジンは、パスワードの入力、CAPTCHA の突破、アカウントの作成、
法的な宣誓への同意を一切行わず、あなた自身のダイジェスト以外のメールも送信しません。

## 開発

```bash
pip install -e ".[dev]"
pytest -q
```

モジュールの契約については [`docs/ARCHITECTURE.md`](../ARCHITECTURE.md) を参照してください。テストはすべての
ソースについて記録済みのフィクスチャを使い、オフラインで実行されます。

## ライセンス

MIT。[`LICENSE`](../../LICENSE) と [`NOTICE`](../../NOTICE) を参照してください。

---

> [英語版 README](../../README.md) が正本です。翻訳は更新が遅れる場合があります。
