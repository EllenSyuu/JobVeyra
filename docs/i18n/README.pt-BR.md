<h1 align="center">JobVeyra</h1>

<p align="center">
  <a href="../../README.md">English</a> ·
  <a href="README.zh-CN.md">简体中文</a> ·
  <a href="README.zh-TW.md">繁體中文</a> ·
  <a href="README.ja.md">日本語</a> ·
  <a href="README.ko.md">한국어</a> ·
  <a href="README.fr.md">Français</a> ·
  <a href="README.es.md">Español</a> ·
  <b>Português</b> ·
  <a href="README.de.md">Deutsch</a> ·
  <a href="README.it.md">Italiano</a> ·
  <a href="README.ru.md">Русский</a> ·
  <a href="README.ar.md">العربية</a> ·
  <a href="README.hi.md">हिन्दी</a>
</p>

<p align="center">
  Um mecanismo de busca de emprego de código aberto que encontra vagas nos lugares que você escolhe, dá uma nota
  a cada uma com base em evidências, prepara candidaturas honestas, envia apenas o que você aprovou e conta a
  você, toda manhã, o que funcionou.
</p>

<p align="center">
  <a href="#quick-start">Início rápido</a> ·
  <a href="#how-it-works">Como funciona</a> ·
  <a href="#compared-with-other-tools">Comparação</a> ·
  <a href="../ARCHITECTURE.md">Arquitetura</a> ·
  <a href="../../AGENTS.md">Regras para agentes</a>
</p>

---

A maioria dos agentes de busca de emprego para antes do botão "Enviar" e deixa o clique para você, ou clica em
"Enviar" em tudo e torce para dar certo. O JobVeyra deixa a escolha com você, por workspace:

| `policy.submission` | O que acontece |
|---|---|
| `batch_approve` (padrão) | Você revisa uma página com um lote de candidaturas e aprova tudo de uma vez. Cada aprovação é assinada sobre o conteúdo exato da vaga; se a vaga mudar, ela volta para revisão. |
| `auto` | Toda vaga que passa pelos seus filtros, pela nota mínima e pelo limite diário é enviada. |
| `fill_only` | Os formulários são preenchidos e param antes de "Enviar". Quem clica é você. |

Em qualquer modo, uma candidatura só conta como enviada quando a confirmação do empregador é registrada. Um
formulário preenchido, um botão clicado ou uma nota alta nunca contam como progresso.

<a id="quick-start"></a>

## Início rápido

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

Depois, deixe um agente trabalhar na fila:

| Ambiente | Configuração |
|---|---|
| Claude Code | `/plugin marketplace add EllenSyuu/JobVeyra` e depois `/plugin install jobveyra@jobveyra`; comandos `/jobveyra:search`, `/jobveyra:review`, `/jobveyra:apply`, `/jobveyra:digest` |
| Codex, OpenCode, Cursor, Gemini CLI, Copilot | Abra o workspace; eles leem o [`AGENTS.md`](../../AGENTS.md) (o `GEMINI.md` aponta para o mesmo arquivo) |
| Sem agente | Cada etapa é um comando comum; veja `jobveyra --help` |
| Docker | `docker build -t jobveyra .` e depois `docker run --rm -v "$PWD:/workspace" jobveyra discover` |

## Foco em qualquer lugar

Onde você procura é configuração, não código. As regiões são ordenadas e têm pesos, o trabalho remoto pode ser
permitido, exigido ou excluído, e cada família de cargos (um *track*) tem suas próprias palavras-chave de cargo,
habilidades comprovadas e variante de currículo.

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

O arquivo completo e comentado está em [`examples/jobveyra.yml`](../../examples/jobveyra.yml).

<a id="how-it-works"></a>

## Como funciona

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

Cada vaga fica em uma única fila persistente, com exatamente um estado e o motivo dele
(`discovered`, `excluded`, `eligible`, `ready_to_submit`, `in_progress`, `submitted`,
`needs_check`, `retry_wait`, `blocked_auth`, `blocked_human`, `blocked_technical`).
Transições inválidas são rejeitadas, as concessões (leases) expiram com segurança e uma falha depois do clique em
"Enviar" vira `needs_check` em vez de uma candidatura duplicada.

## O que ele faz

**Descoberta**
- Onze adaptadores de fontes que usam endpoints públicos, sem login, com novas tentativas, backoff, limite de
  requisições por host e verificação de robots.txt. A descoberta não gasta nenhuma chamada de modelo.
- Filtros de região, remoto, senioridade (cargos em inglês, francês, espanhol, português e alemão), tipo de
  contratação, cargo e empregador, cada um com um motivo registrado quando rejeita uma vaga.
- Remoção de duplicatas por empregador e ID da requisição e, depois, pelo conteúdo da vaga.

**Avaliação**
- Oito dimensões: habilidades, track, senioridade, localização, idioma, remuneração, atualidade e empregador.
  Cada uma traz evidências marcadas pela origem: citadas da vaga, lidas de campos estruturados ou estimadas. Uma
  dimensão sustentada apenas por estimativas tem um teto.
- Os requisitos são separados em obrigatórios e desejáveis antes da comparação de habilidades.
- Bloqueios definitivos encerram a avaliação: sem patrocínio de visto para um mercado em que você não pode
  trabalhar, um idioma obrigatório que você não fala em nível B2 ou superior, credencial de segurança, tipo de
  contratação, empregadores que você evita, uma vaga encerrada.
- Sinais de legitimidade: vagas encerradas, republicadas, antigas, bancos de talentos permanentes, sem salário,
  cargos vagos.
- Leitura de salários em várias moedas e períodos, anualizados e comparados com o seu piso.
- Um modelo opcional (Anthropic, OpenAI, Ollama ou qualquer endpoint compatível com a OpenAI) pode acrescentar uma
  correspondência semântica de habilidades, limitada e marcada como estimativa. Seu nome, e-mail, telefone e
  links são mascarados antes de qualquer chamada.

**Materiais**
- Proteção contra invenção: todo número, data, empregador, diploma e certificação em um documento precisa
  constar na sua base de fatos.
- Proteção contra linguagem autodepreciativa em inglês, francês, espanhol e português.
- Verificação de texto para ATS: cobertura de palavras-chave, dados de contato, ruído de extração.
- Abordagens para a carta de apresentação tiradas da vaga e somente das suas habilidades comprovadas.

**Depois da candidatura**
- Registro de resultados, funil com tempo até a primeira resposta, padrões de resposta por fonte, portal, track e
  trilha com intervalos de confiança, e calibração da nota (Brier score, AUC) que avisa quando o seu limite está
  errado.
- Demanda por habilidades nas vagas que você viu e as lacunas em relação ao seu perfil.
- Follow-ups pendentes com rascunho de mensagem; prazos como arquivos de calendário.
- Fichas de preparação para entrevistas, um banco de histórias STAR+R cujas métricas precisam citar uma fonte e
  roteiros de negociação de proposta.

**Relatórios**
- Um resumo diário por e-mail com um gráfico animado que também funciona em clientes que mostram só o primeiro
  quadro, temas claro e escuro, e uma versão em texto simples.
- Notificações no Telegram, Slack, Discord ou Teams com uma única configuração de webhook.
- Um bloco de status para qualquer arquivo Markdown, como o README de um repositório privado.

<a id="compared-with-other-tools"></a>

## Comparação com outras ferramentas

Com base no README público de cada projeto em novembro de 2026. Correções são bem-vindas.

| | JobVeyra | career-ops | LinkedIn AI Job Applier Ultimate | JobAppAgent |
|---|---|---|---|---|
| Envio | Você escolhe: aprovação em lote, automático ou só preenchimento | Preenche formulários; você envia | Envia automaticamente | Aprovação por candidatura ou em lote; o agente para antes de enviar |
| O que conta como candidatura | Somente a confirmação do empregador | Não informado | Não informado | Somente confirmação visível |
| Modelo de estados | Uma fila persistente, 11 estados, leases, resistente a falhas | Planilha em Markdown | Arquivos de resultado em YAML | Registros |
| Aprovação vinculada ao conteúdo da vaga | Sim (assinada sobre o hash do conteúdo) | Não se aplica (você envia) | Sem etapa de aprovação | A aprovação cobre o que foi exibido, 24 h |
| Fontes | Greenhouse, Lever, Ashby, Workable, SmartRecruiters, Recruitee, UN Careers, USAJOBS, Remotive, páginas schema.org, alertas do LinkedIn | Ashby, Greenhouse, Lever, Wellfound, alertas do LinkedIn | LinkedIn, Indeed | Catálogo de sites de vagas e páginas de carreira |
| Regiões | Regiões ordenadas e com pesos por usuário | Consultas de busca | Filtros de busca | Filtros de busca |
| Pontuação | 0–100 em 8 dimensões, origem da evidência por dimensão, teto para estimativas | 1–5 nos blocos A–H, origem da evidência, teto para estimativas | Nota de interesse de 1 a 100 | Nota de aderência |
| Verificações de legitimidade | Encerrada, republicada, antiga, permanente, sem salário, cargo vago | Vigência, republicação, bloco de legitimidade | Não informado | Verificação de vaga ativa |
| Proteção contra invenção | Números, datas, empregadores, diplomas, certificações | Números e fatos | Pula perguntas que não consegue responder | Somente fatos verificados |
| Calibração da nota | Brier, AUC, sugestão de limite | Calibração indicativa | Não informado | Não informado |
| Análise de resultados | Funil, padrões com intervalos, demanda por habilidades | Funil, padrões, lacunas de habilidades | Estatísticas de habilidades | Registros de resultados |
| Relatório diário | Resumo por e-mail, Telegram, webhooks | Não informado | Telegram | Não informado |
| Exige modelo | Não (opcional, mascarado) | Uma CLI de IA ou um avaliador | Sim | Um agente de programação |
| Ambientes | Plugin do Claude Code, CLIs compatíveis com AGENTS.md, Docker, CLI simples | Várias CLIs de IA, Docker | Aplicativo Python, Docker | Skill de agente mais CLI |

Onde as outras estão à frente hoje: o career-ops tem uma comunidade grande, um painel interativo no terminal,
pesquisa de empresas e redação de mensagens de contato, além de READMEs em 18 idiomas; o LinkedIn applier
automatiza o LinkedIn e o Indeed diretamente e tem um painel de controle web local; o JobAppAgent oferece estado
compartilhado entre várias máquinas por meio de um backend opcional na nuvem.

## Privacidade

Seus dados ficam no seu workspace, nunca neste repositório. O `jobveyra init` cria um `.gitignore` que exclui o
workspace inteiro. Sem telemetria, sem backend. As chamadas de modelo vêm desativadas por padrão e, quando ativadas,
são mascaradas. O mecanismo nunca digita senhas, resolve CAPTCHAs, cria contas, aceita declarações legais ou envia
e-mails além do seu próprio resumo.

## Desenvolvimento

```bash
pip install -e ".[dev]"
pytest -q
```

Veja [`docs/ARCHITECTURE.md`](../ARCHITECTURE.md) para os contratos dos módulos. Os testes rodam offline com dados
gravados para cada fonte.

## Licença

MIT. Veja [`LICENSE`](../../LICENSE) e [`NOTICE`](../../NOTICE).

---

> O [README em inglês](../../README.md) é a referência; as traduções podem estar desatualizadas.
