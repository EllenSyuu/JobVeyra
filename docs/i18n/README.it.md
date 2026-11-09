<h1 align="center">JobVeyra</h1>

<p align="center">
  <a href="../../README.md">English</a> ·
  <a href="README.zh-CN.md">简体中文</a> ·
  <a href="README.zh-TW.md">繁體中文</a> ·
  <a href="README.ja.md">日本語</a> ·
  <a href="README.ko.md">한국어</a> ·
  <a href="README.fr.md">Français</a> ·
  <a href="README.es.md">Español</a> ·
  <a href="README.pt-BR.md">Português</a> ·
  <a href="README.de.md">Deutsch</a> ·
  <b>Italiano</b> ·
  <a href="README.ru.md">Русский</a> ·
  <a href="README.ar.md">العربية</a> ·
  <a href="README.hi.md">हिन्दी</a>
</p>

<p align="center">
  Un motore di ricerca di lavoro open source che trova posizioni nei luoghi che scegli tu, assegna a ciascuna un
  punteggio motivato da prove, prepara candidature oneste, invia solo ciò che hai approvato e ogni mattina ti dice
  che cosa ha funzionato.
</p>

<p align="center">
  <a href="#quick-start">Avvio rapido</a> ·
  <a href="#how-it-works">Come funziona</a> ·
  <a href="#compared-with-other-tools">Confronto</a> ·
  <a href="../ARCHITECTURE.md">Architettura</a> ·
  <a href="../../AGENTS.md">Regole per gli agenti</a>
</p>

---

La maggior parte degli agenti per la ricerca di lavoro si ferma prima di «Invia» e lascia a te il clic, oppure
clicca «Invia» su tutto e spera per il meglio. JobVeyra lascia a te la scelta, per ogni workspace:

| `policy.submission` | Cosa succede |
|---|---|
| `batch_approve` (predefinito) | Esamini una pagina con un lotto di candidature e la approvi una sola volta. Ogni approvazione è firmata sul contenuto esatto dell'annuncio; se l'annuncio cambia, torna in revisione. |
| `auto` | Viene inviata ogni offerta che supera i tuoi filtri, la soglia di punteggio e il limite giornaliero. |
| `fill_only` | I moduli vengono compilati e si fermano prima di «Invia». Il pulsante lo premi tu. |

In ogni modalità, una candidatura conta come inviata solo quando viene registrata la conferma del datore di
lavoro. Un modulo compilato, un pulsante cliccato o un punteggio alto non contano mai come progresso.

<a id="quick-start"></a>

## Avvio rapido

```bash
pip install "jobveyra[charts]"     # Python 3.10+; charts need Pillow

jobveyra init ~/my-search && cd ~/my-search
# edit jobveyra.yml (who you are, where you want to work, policy, sources)
# write your fact base in cv/master.md
jobveyra doctor
jobveyra discover && jobveyra evaluate
jobveyra status
```

Poi lascia che un agente lavori sulla coda:

| Ambiente | Configurazione |
|---|---|
| Claude Code | `/plugin marketplace add EllenSyuu/JobVeyra` e poi `/plugin install jobveyra@jobveyra`; comandi `/jobveyra:search`, `/jobveyra:review`, `/jobveyra:apply`, `/jobveyra:digest` |
| Codex, OpenCode, Cursor, Gemini CLI, Copilot | Apri il workspace; leggono [`AGENTS.md`](../../AGENTS.md) (`GEMINI.md` rimanda allo stesso file) |
| Senza agente | Ogni passaggio è un normale comando; vedi `jobveyra --help` |
| Docker | `docker build -t jobveyra .` e poi `docker run --rm -v "$PWD:/workspace" jobveyra discover` |

## Concentrati dove vuoi

Dove cerchi è una questione di configurazione, non di codice. Le regioni sono ordinate e pesate, il lavoro da
remoto può essere consentito, richiesto o escluso, e ogni famiglia di ruoli (un *track*) ha le proprie parole
chiave per i titoli, competenze documentate e variante di CV.

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

Il file completo e commentato è [`examples/jobveyra.yml`](../../examples/jobveyra.yml).

<a id="how-it-works"></a>

## Come funziona

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

Ogni offerta vive in un'unica coda persistente, con esattamente uno stato e il relativo motivo
(`discovered`, `excluded`, `eligible`, `ready_to_submit`, `in_progress`, `submitted`,
`needs_check`, `retry_wait`, `blocked_auth`, `blocked_human`, `blocked_technical`).
Le transizioni non consentite vengono rifiutate, i lease scadono in modo sicuro e un crash dopo il clic su «Invia»
diventa `needs_check` invece di una candidatura duplicata.

## Cosa fa

**Ricerca**
- Undici adattatori di fonti che usano endpoint pubblici senza login, con nuovi tentativi, backoff, limite di
  richieste per host e controllo di robots.txt. La ricerca non costa alcuna chiamata al modello.
- Filtri per regione, remoto, seniority (titoli in inglese, francese, spagnolo, portoghese e tedesco), tipo di
  contratto, titolo e datore di lavoro, ciascuno con un motivo registrato quando scarta un'offerta.
- Deduplicazione per datore di lavoro e ID della posizione, poi per contenuto dell'annuncio.

**Valutazione**
- Otto dimensioni: competenze, track, seniority, sede, lingua, retribuzione, freschezza, datore di lavoro.
  Ognuna porta prove etichettate in base all'origine: citate dall'annuncio, lette da campi strutturati o stimate.
  Una dimensione sostenuta solo da stime ha un tetto massimo.
- I requisiti vengono separati in obbligatori e preferenziali prima del confronto delle competenze.
- I blocchi rigidi chiudono la valutazione: nessuna sponsorizzazione del visto per un mercato in cui non puoi
  lavorare, una lingua richiesta che non parli almeno a livello B2, nulla osta di sicurezza, tipo di contratto,
  datori di lavoro che eviti, un annuncio chiuso.
- Segnali di affidabilità: annunci chiusi, ripubblicati, datati, bacini di talenti sempre aperti, retribuzione
  assente, titoli vaghi.
- Lettura degli stipendi in diverse valute e periodi, rapportati all'anno e confrontati con la tua soglia minima.
- Un modello opzionale (Anthropic, OpenAI, Ollama o qualsiasi endpoint compatibile con OpenAI) può aggiungere un
  confronto semantico delle competenze, limitato ed etichettato come stima. Nome, email, telefono e link vengono
  mascherati prima di ogni chiamata.

**Materiali**
- Protezione contro le invenzioni: ogni numero, data, datore di lavoro, titolo di studio e certificazione in un
  documento deve comparire nella tua base di fatti.
- Protezione contro le formulazioni autosvalutative in inglese, francese, spagnolo e portoghese.
- Controllo del testo per ATS: copertura delle parole chiave, recapiti, rumore di estrazione.
- Spunti per la lettera di presentazione ricavati dall'annuncio e solo dalle tue competenze documentate.

**Dopo la candidatura**
- Registro degli esiti, funnel con tempo alla prima risposta, andamenti delle risposte per fonte, portale, track e
  corsia con intervalli di confidenza, e calibrazione del punteggio (Brier score, AUC) che ti avvisa quando la tua
  soglia è sbagliata.
- Domanda di competenze negli annunci che hai visto e le lacune rispetto al tuo profilo.
- Follow-up in scadenza con una bozza di messaggio; scadenze come file di calendario.
- Schede di preparazione ai colloqui, una raccolta di storie STAR+R le cui metriche devono citare una fonte, e
  copioni per negoziare l'offerta.

**Report**
- Un riepilogo giornaliero via email con un grafico animato che funziona anche nei client che mostrano solo il
  primo fotogramma, temi chiaro e scuro, e una parte in testo semplice.
- Notifiche su Telegram, Slack, Discord o Teams tramite un'unica impostazione webhook.
- Un blocco di stato per qualsiasi file Markdown, come il README di un repository privato.

<a id="compared-with-other-tools"></a>

## Confronto con altri strumenti

Basato sul README pubblico di ciascun progetto a novembre 2026. Le correzioni sono benvenute.

| | JobVeyra | career-ops | LinkedIn AI Job Applier Ultimate | JobAppAgent |
|---|---|---|---|---|
| Invio | A tua scelta: approvazione a lotti, automatico o solo compilazione | Compila i moduli; invii tu | Invia automaticamente | Approvazione per candidatura o a lotti; l'agente si ferma prima dell'invio |
| Cosa conta come candidatura | Solo la conferma del datore di lavoro | Non indicato | Non indicato | Solo una conferma visibile |
| Modello di stato | Un'unica coda persistente, 11 stati, lease, resistente ai crash | Tracker in Markdown | File di risultati YAML | Registri |
| Approvazione legata al contenuto dell'annuncio | Sì (firmata sull'hash del contenuto) | Non applicabile (invii tu) | Nessun passaggio di approvazione | L'approvazione copre ciò che è stato mostrato, 24 h |
| Fonti | Greenhouse, Lever, Ashby, Workable, SmartRecruiters, Recruitee, UN Careers, USAJOBS, Remotive, pagine schema.org, avvisi LinkedIn | Ashby, Greenhouse, Lever, Wellfound, avvisi LinkedIn | LinkedIn, Indeed | Catalogo di bacheche e pagine carriere |
| Regioni | Regioni ordinate e pesate per utente | Query di ricerca | Filtri di ricerca | Filtri di ricerca |
| Punteggio | 0–100 su 8 dimensioni, origine delle prove per dimensione, tetto per le stime | 1–5 sui blocchi A–H, origine delle prove, tetto per le stime | Punteggio di interesse da 1 a 100 | Punteggio di affinità |
| Controlli di affidabilità | Chiuso, ripubblicato, datato, sempre aperto, senza retribuzione, titolo vago | Disponibilità, ripubblicazione, blocco di affidabilità | Non indicato | Verifica che l'annuncio sia attivo |
| Protezione contro le invenzioni | Numeri, date, datori di lavoro, titoli di studio, certificazioni | Numeri e fatti | Salta le domande a cui non sa rispondere | Solo fatti verificati |
| Calibrazione del punteggio | Brier, AUC, consigli sulla soglia | Calibrazione indicativa | Non indicato | Non indicato |
| Analisi degli esiti | Funnel, andamenti con intervalli, domanda di competenze | Funnel, andamenti, lacune di competenze | Statistiche sulle competenze | Registri degli esiti |
| Report giornaliero | Riepilogo via email, Telegram, webhook | Non indicato | Telegram | Non indicato |
| Modello richiesto | No (opzionale, mascherato) | Una CLI di IA o un valutatore | Sì | Un agente di programmazione |
| Ambienti | Plugin per Claude Code, CLI compatibili con AGENTS.md, Docker, CLI semplice | Molte CLI di IA, Docker | App Python, Docker | Skill per agenti più CLI |

Dove gli altri sono avanti oggi: career-ops ha una grande community, una dashboard interattiva nel terminale,
ricerca sulle aziende e stesura di messaggi di contatto, e README in 18 lingue; il LinkedIn applier automatizza
direttamente LinkedIn e Indeed e ha un pannello di controllo web locale; JobAppAgent supporta uno stato condiviso
tra più macchine grazie a un backend cloud opzionale.

## Privacy

I tuoi dati restano nel tuo workspace, mai in questo repository. `jobveyra init` scrive un `.gitignore` che esclude
l'intero workspace. Nessuna telemetria, nessun backend. Le chiamate al modello sono disattivate per impostazione
predefinita e mascherate quando attive. Il motore non inserisce mai password, non risolve CAPTCHA, non crea account,
non accetta dichiarazioni legali e non invia email diverse dal tuo riepilogo personale.

## Sviluppo

```bash
pip install -e ".[dev]"
pytest -q
```

Vedi [`docs/ARCHITECTURE.md`](../ARCHITECTURE.md) per i contratti dei moduli. I test girano offline su fixture
registrate per ogni fonte.

## Licenza

MIT. Vedi [`LICENSE`](../../LICENSE) e [`NOTICE`](../../NOTICE).

---

> Il [README in inglese](../../README.md) è il riferimento; le traduzioni potrebbero non essere aggiornate.
