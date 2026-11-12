<h1 align="center">JobVeyra</h1>

<p align="center">
  <a href="../../README.md">English</a> ·
  <a href="README.zh-CN.md">简体中文</a> ·
  <a href="README.zh-TW.md">繁體中文</a> ·
  <a href="README.ja.md">日本語</a> ·
  <b>한국어</b> ·
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
  오픈소스 구직 엔진입니다. 원하는 지역에서 채용 공고를 찾고, 근거를 바탕으로 하나하나 점수를 매기고,
  정직한 지원서를 준비하고, 승인한 지원서만 제출하며, 무엇이 효과가 있었는지 매일 아침 알려 줍니다.
</p>

<p align="center">
  <a href="#quick-start">빠른 시작</a> ·
  <a href="#how-it-works">작동 방식</a> ·
  <a href="#compared-with-other-tools">비교</a> ·
  <a href="../ARCHITECTURE.md">아키텍처</a> ·
  <a href="../../AGENTS.md">에이전트 규칙</a>
</p>

---

대부분의 구직 에이전트는 '제출' 버튼 앞에서 멈춰 클릭을 사용자에게 맡기거나, 모든 공고에 '제출'을 누르고
운에 맡깁니다. JobVeyra는 워크스페이스마다 그 선택을 사용자에게 맡깁니다.

| `policy.submission` | 동작 |
|---|---|
| `batch_approve` (기본값) | 지원서 묶음을 나열한 한 페이지를 검토하고 한 번에 승인합니다. 각 승인은 공고의 정확한 내용에 대해 서명되므로, 공고 내용이 바뀌면 다시 검토 대상으로 돌아옵니다. |
| `auto` | 필터, 점수 기준치, 일일 한도를 통과한 모든 공고가 제출됩니다. |
| `fill_only` | 양식을 채운 뒤 '제출' 직전에 멈춥니다. 버튼은 직접 누릅니다. |

어떤 모드에서든, 고용주의 확인이 기록되어야만 지원서가 발송된 것으로 집계됩니다. 채워진 양식, 클릭된 버튼,
높은 점수는 결코 진척으로 집계되지 않습니다.

<a id="quick-start"></a>

## 빠른 시작

```bash
pip install "jobveyra[charts]"     # Python 3.10+; charts need Pillow

jobveyra init ~/my-search && cd ~/my-search
# edit jobveyra.yml (who you are, where you want to work, policy, sources)
# write your fact base in cv/master.md
jobveyra doctor
jobveyra discover && jobveyra evaluate
jobveyra status
```

그다음 에이전트가 대기열을 처리하게 합니다.

| 런타임 | 설정 |
|---|---|
| Claude Code | `/plugin marketplace add EllenSyuu/JobVeyra` 다음 `/plugin install jobveyra@jobveyra`; 명령어는 `/jobveyra:search`, `/jobveyra:review`, `/jobveyra:apply`, `/jobveyra:digest` |
| Codex, OpenCode, Cursor, Gemini CLI, Copilot | 워크스페이스를 열면 됩니다. 각 도구가 [`AGENTS.md`](../../AGENTS.md)를 읽습니다 (`GEMINI.md`도 같은 파일을 가리킵니다) |
| 에이전트 없음 | 모든 단계가 일반 명령어입니다. `jobveyra --help`를 참고하세요 |
| Docker | `docker build -t jobveyra .` 다음 `docker run --rm -v "$PWD:/workspace" jobveyra discover` |

## 어디든 집중

어디에서 찾을지는 코드가 아니라 설정입니다. 지역에는 순서와 가중치를 줄 수 있고, 원격 근무는 허용·필수·제외 중에서
고를 수 있으며, 각 직무군(*track*)은 고유한 직함 키워드, 근거가 있는 기술, 이력서 버전을 가집니다.

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

주석이 달린 전체 설정 파일은 [`examples/jobveyra.yml`](../../examples/jobveyra.yml)입니다.

<a id="how-it-works"></a>

## 작동 방식

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

모든 공고는 하나의 영구 대기열에 저장되며, 항상 정확히 하나의 상태와 그 이유를 가집니다
(`discovered`, `excluded`, `eligible`, `ready_to_submit`, `in_progress`, `submitted`,
`needs_check`, `retry_wait`, `blocked_auth`, `blocked_human`, `blocked_technical`).
허용되지 않은 상태 전환은 거부되고, 임대(lease)는 안전하게 만료되며, '제출' 클릭 후 충돌이 발생하면 중복 지원이
아니라 `needs_check` 상태가 됩니다.

## 주요 기능

**공고 탐색**
- 로그인이 필요 없는 공개 엔드포인트를 사용하는 11개의 소스 어댑터. 재시도, 백오프, 호스트별 속도 제한,
  robots.txt 확인을 갖추고 있습니다. 탐색 단계에서는 모델 호출 비용이 들지 않습니다.
- 지역, 원격, 경력 수준(영어·프랑스어·스페인어·포르투갈어·독일어 직함 지원), 고용 형태, 직함, 고용주 필터.
  제외할 때마다 이유가 기록됩니다.
- 고용주와 채용 번호로 중복을 제거한 다음, 공고 내용으로 다시 중복을 제거합니다.

**평가**
- 8개 차원: 기술, 트랙, 경력 수준, 근무지, 언어, 보상, 최신성, 고용주. 각 차원에는 근거 유형(공고에서 인용,
  구조화된 필드에서 읽음, 추정)이 표시된 증거가 붙습니다. 추정만으로 뒷받침되는 차원은 상한이 적용됩니다.
- 기술을 대조하기 전에 요구 사항을 필수와 우대로 나눕니다.
- 절대 차단 조건에 걸리면 평가가 즉시 종료됩니다: 근무 자격이 없는 시장에서 비자 후원이 없음, B2 이상으로
  구사하지 못하는 언어가 필수, 보안 인가, 고용 형태, 피하고 싶은 고용주, 마감된 공고.
- 신뢰성 신호: 마감된 공고, 재게시, 오래된 공고, 상시 인재풀, 급여 미기재, 모호한 직함.
- 여러 통화와 지급 주기에 걸쳐 급여를 파싱하고, 연봉으로 환산해 최저 기준과 비교합니다.
- 선택형 모델(Anthropic, OpenAI, Ollama 또는 OpenAI 호환 엔드포인트)로 의미 기반 기술 매칭을 추가할 수 있으며,
  그 영향은 제한되고 추정으로 표시됩니다. 호출 전에 이름, 이메일, 전화번호, 링크는 마스킹됩니다.

**지원 자료**
- 허위 기재 방지: 문서에 있는 모든 숫자, 날짜, 고용주, 학위, 자격증은 사실 기반 자료(fact base)에 있어야 합니다.
- 자기 비하 표현 검사(영어·프랑스어·스페인어·포르투갈어).
- ATS 텍스트 검사: 키워드 포함률, 연락처, 추출 노이즈.
- 자기소개서의 방향은 공고와 근거가 있는 본인 기술에서만 가져옵니다.

**지원 이후**
- 결과 원장, 첫 회신까지의 시간을 포함한 퍼널, 소스·채용 포털·트랙·레인별 응답 패턴(신뢰 구간 포함), 그리고
  기준치가 잘못되었을 때 알려 주는 점수 보정(Brier 점수, AUC).
- 확인한 공고 전반의 기술 수요와 내 프로필과의 격차.
- 기한이 된 후속 연락과 초안 메시지, 마감일은 캘린더 파일로 제공.
- 면접 준비 시트, 지표마다 출처를 요구하는 STAR+R 스토리 뱅크, 연봉 협상 스크립트.

**리포트**
- 첫 프레임만 보여 주는 메일 클라이언트에서도 읽히는 애니메이션 차트, 라이트·다크 테마, 일반 텍스트 버전을 갖춘
  일일 이메일 다이제스트.
- 하나의 webhook 설정으로 Telegram, Slack, Discord, Teams 알림.
- 비공개 저장소의 README 같은 아무 Markdown 파일에나 넣을 수 있는 상태 블록.

<a id="compared-with-other-tools"></a>

## 다른 도구와 비교

2026년 11월 기준 각 프로젝트의 공개 README를 바탕으로 작성했습니다. 정정 제안을 환영합니다.

| | JobVeyra | career-ops | LinkedIn AI Job Applier Ultimate | JobAppAgent |
|---|---|---|---|---|
| 제출 방식 | 선택 가능: 일괄 승인, 자동, 입력만 | 양식 입력, 제출은 사용자 | 자동 제출 | 지원서별 또는 일괄 승인, 에이전트는 제출 전에 멈춤 |
| 지원 완료 기준 | 고용주 확인만 | 명시되지 않음 | 명시되지 않음 | 눈에 보이는 확인만 |
| 상태 모델 | 단일 영구 대기열, 11개 상태, 임대, 충돌 안전 | Markdown 트래커 | YAML 결과 파일 | 원장 |
| 공고 내용에 묶인 승인 | 예 (내용 해시에 서명) | 해당 없음 (사용자가 제출) | 승인 단계 없음 | 표시된 내용에 대한 승인, 24시간 |
| 소스 | Greenhouse, Lever, Ashby, Workable, SmartRecruiters, Recruitee, UN Careers, USAJOBS, Remotive, schema.org 페이지, LinkedIn 알림 메일 | Ashby, Greenhouse, Lever, Wellfound, LinkedIn 알림 메일 | LinkedIn, Indeed | 구인 게시판과 채용 페이지 목록 |
| 지역 | 사용자별 순서·가중치 지역 | 검색어 | 검색 필터 | 검색 필터 |
| 점수 | 8개 차원 0–100, 차원별 근거 유형, 추정치 상한 | 블록 A–H 1–5, 근거 유형, 추정치 상한 | 1–100 관심 점수 | 적합도 점수 |
| 신뢰성 검사 | 마감, 재게시, 오래됨, 상시 채용, 급여 없음, 모호한 직함 | 게시 여부, 재게시, 신뢰성 블록 | 명시되지 않음 | 게시 중 여부 확인 |
| 허위 기재 방지 | 숫자, 날짜, 고용주, 학위, 자격증 | 숫자와 사실 | 답할 수 없는 질문은 건너뜀 | 검증된 사실만 |
| 점수 보정 | Brier, AUC, 기준치 조언 | 권고 수준의 보정 | 명시되지 않음 | 명시되지 않음 |
| 결과 분석 | 퍼널, 구간이 있는 패턴, 기술 수요 | 퍼널, 패턴, 기술 격차 | 기술 통계 | 결과 원장 |
| 일일 리포트 | 이메일 다이제스트, Telegram, webhook | 명시되지 않음 | Telegram | 명시되지 않음 |
| 모델 필요 여부 | 아니요 (선택, 마스킹) | AI CLI 또는 평가기 | 예 | 코딩 에이전트 |
| 런타임 | Claude Code 플러그인, AGENTS.md 지원 CLI, Docker, 일반 CLI | 여러 AI CLI, Docker | Python 앱, Docker | 에이전트 스킬과 CLI |

현재 다른 도구가 앞서 있는 부분: career-ops는 큰 커뮤니티, 대화형 터미널 대시보드, 기업 조사와 연락 메시지 초안
작성 기능, 18개 언어의 README를 갖추고 있습니다. LinkedIn applier는 LinkedIn과 Indeed를 직접 자동화하며 로컬 웹
제어판을 제공합니다. JobAppAgent는 선택형 클라우드 백엔드를 통해 여러 호스트 간 상태 공유를 지원합니다.

## 개인정보

데이터는 사용자의 워크스페이스에 저장되며, 이 저장소에는 절대 들어가지 않습니다. `jobveyra init`은 워크스페이스
전체를 제외하는 `.gitignore`를 생성합니다. 텔레메트리도, 백엔드도 없습니다. 모델 호출은 기본적으로 꺼져 있고,
켜더라도 마스킹됩니다. 이 엔진은 비밀번호를 입력하거나, CAPTCHA를 풀거나, 계정을 만들거나, 법적 서약에
동의하지 않으며, 본인의 다이제스트 외에는 어떤 이메일도 보내지 않습니다.

예외는 당신이 정하는 것 하나뿐입니다. 본인의 말로 상시 동의를 기록하면(`jobveyra authorize --consent ...`) 마지막 페이지의 일반적인 정확성 서약과 필수 약관에 체크합니다. 단, 양식의 모든 답변이 확인된 경우에만 해당하며, 알려진 사실과 모순되는 서약에는 절대 체크하지 않습니다.

## 개발

```bash
pip install -e ".[dev]"
pytest -q
```

모듈 계약은 [`docs/ARCHITECTURE.md`](../ARCHITECTURE.md)를 참고하세요. 테스트는 모든 소스에 대해 녹화된 픽스처를
사용해 오프라인으로 실행됩니다.

## 라이선스

MIT. [`LICENSE`](../../LICENSE)와 [`NOTICE`](../../NOTICE)를 참고하세요.

---

> [영어 README](../../README.md)가 기준 문서이며, 번역본은 최신 내용을 반영하지 못할 수 있습니다.
