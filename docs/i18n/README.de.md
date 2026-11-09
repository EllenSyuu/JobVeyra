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
  <b>Deutsch</b> ·
  <a href="README.it.md">Italiano</a> ·
  <a href="README.ru.md">Русский</a> ·
  <a href="README.ar.md">العربية</a> ·
  <a href="README.hi.md">हिन्दी</a>
</p>

<p align="center">
  Eine Open-Source-Jobsuchmaschine, die Stellen an den Orten findet, die du auswählst, jede einzelne mit Belegen
  bewertet, ehrliche Bewerbungen vorbereitet, nur das absendet, was du freigegeben hast, und dir jeden Morgen
  sagt, was funktioniert hat.
</p>

<p align="center">
  <a href="#quick-start">Schnellstart</a> ·
  <a href="#how-it-works">Funktionsweise</a> ·
  <a href="#compared-with-other-tools">Vergleich</a> ·
  <a href="../ARCHITECTURE.md">Architektur</a> ·
  <a href="../../AGENTS.md">Regeln für Agenten</a>
</p>

---

Die meisten Jobsuch-Agenten halten entweder vor „Absenden“ an und überlassen dir den Klick, oder sie klicken
überall auf „Absenden“ und hoffen das Beste. Bei JobVeyra entscheidest du, pro Workspace:

| `policy.submission` | Was passiert |
|---|---|
| `batch_approve` (Standard) | Du prüfst eine Seite mit einem Stapel von Bewerbungen und gibst ihn einmal frei. Jede Freigabe wird über den exakten Inhalt der Stellenanzeige signiert; ändert sich die Anzeige, kommt sie erneut zur Prüfung. |
| `auto` | Jede Stelle, die deine Filter, deine Score-Schwelle und dein Tageslimit passiert, wird abgeschickt. |
| `fill_only` | Formulare werden ausgefüllt und halten vor „Absenden“ an. Den Knopf drückst du. |

In jedem Modus gilt eine Bewerbung erst dann als abgeschickt, wenn die Bestätigung des Arbeitgebers erfasst
ist. Ein ausgefülltes Formular, ein geklickter Button oder ein hoher Score zählen nie als Fortschritt.

<a id="quick-start"></a>

## Schnellstart

```bash
pip install "jobveyra[charts]"     # Python 3.10+; charts need Pillow

jobveyra init ~/my-search && cd ~/my-search
# edit jobveyra.yml (who you are, where you want to work, policy, sources)
# write your fact base in cv/master.md
jobveyra doctor
jobveyra discover && jobveyra evaluate
jobveyra status
```

Dann lässt du einen Agenten die Warteschlange abarbeiten:

| Laufzeitumgebung | Einrichtung |
|---|---|
| Claude Code | `/plugin marketplace add EllenSyuu/JobVeyra`, dann `/plugin install jobveyra@jobveyra`; Befehle `/jobveyra:search`, `/jobveyra:review`, `/jobveyra:apply`, `/jobveyra:digest` |
| Codex, OpenCode, Cursor, Gemini CLI, Copilot | Workspace öffnen; sie lesen [`AGENTS.md`](../../AGENTS.md) (`GEMINI.md` verweist auf dieselbe Datei) |
| Ohne Agent | Jeder Schritt ist ein normaler Befehl; siehe `jobveyra --help` |
| Docker | `docker build -t jobveyra .`, dann `docker run --rm -v "$PWD:/workspace" jobveyra discover` |

## Überall fokussieren

Wo du suchst, ist Konfiguration, kein Code. Regionen sind geordnet und gewichtet, Remote-Arbeit kann erlaubt,
vorausgesetzt oder ausgeschlossen werden, und jede Berufsfamilie (ein *track*) hat eigene Titel-Schlüsselwörter,
belegte Fähigkeiten und eine eigene Lebenslauf-Variante.

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

Die vollständige, kommentierte Datei ist [`examples/jobveyra.yml`](../../examples/jobveyra.yml).

<a id="how-it-works"></a>

## Funktionsweise

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

Jede Stelle liegt in einer einzigen persistenten Warteschlange, mit genau einem Zustand und dem Grund dafür
(`discovered`, `excluded`, `eligible`, `ready_to_submit`, `in_progress`, `submitted`,
`needs_check`, `retry_wait`, `blocked_auth`, `blocked_human`, `blocked_technical`).
Unzulässige Übergänge werden abgelehnt, Leases laufen sicher ab, und ein Absturz nach dem Klick auf „Absenden“
wird zu `needs_check` statt zu einer doppelten Bewerbung.

## Was es kann

**Suche**
- Elf Quellen-Adapter, die öffentliche Endpunkte ohne Login nutzen, mit Wiederholungen, Backoff,
  Ratenbegrenzung pro Host und robots.txt-Prüfung. Die Suche kostet keine Modellaufrufe.
- Filter für Region, Remote, Seniorität (englische, französische, spanische, portugiesische und deutsche
  Jobtitel), Anstellungsart, Titel und Arbeitgeber, jeweils mit einem erfassten Grund, wenn sie etwas aussortieren.
- Deduplizierung nach Arbeitgeber und Stellen-ID, danach nach Inhalt der Anzeige.

**Bewertung**
- Acht Dimensionen: Fähigkeiten, Track, Seniorität, Standort, Sprache, Vergütung, Aktualität, Arbeitgeber.
  Jede trägt Belege, die nach Herkunft gekennzeichnet sind: aus der Anzeige zitiert, aus strukturierten Feldern
  gelesen oder geschätzt. Eine Dimension, die nur auf Schätzungen beruht, wird gedeckelt.
- Anforderungen werden in Muss- und Kann-Kriterien aufgeteilt, bevor Fähigkeiten abgeglichen werden.
- Harte Ausschlusskriterien beenden die Bewertung: kein Visa-Sponsoring für einen Markt, in dem du nicht
  arbeiten darfst, eine geforderte Sprache, die du nicht mindestens auf B2 sprichst, Sicherheitsüberprüfung,
  Anstellungsart, Arbeitgeber, die du meidest, eine geschlossene Anzeige.
- Seriositätssignale: geschlossene Anzeigen, Neuveröffentlichungen, veraltete Anzeigen, dauerhafte
  Talentpools, fehlende Gehaltsangabe, vage Titel.
- Gehaltsangaben in allen Währungen und Zeiträumen werden ausgewertet, aufs Jahr hochgerechnet und mit deiner
  Untergrenze verglichen.
- Ein optionales Modell (Anthropic, OpenAI, Ollama oder ein beliebiger OpenAI-kompatibler Endpunkt) kann einen
  semantischen Abgleich der Fähigkeiten ergänzen, begrenzt und als Schätzung gekennzeichnet. Name, E-Mail,
  Telefonnummer und Links werden vor jedem Aufruf maskiert.

**Unterlagen**
- Schutz vor Erfundenem: Jede Zahl, jedes Datum, jeder Arbeitgeber, Abschluss und jedes Zertifikat in einem
  Dokument muss in deiner Faktenbasis stehen.
- Schutz vor selbstabwertenden Formulierungen auf Englisch, Französisch, Spanisch und Portugiesisch.
- ATS-Textprüfung: Abdeckung der Schlüsselwörter, Kontaktdaten, Extraktionsrauschen.
- Ansatzpunkte für das Anschreiben, abgeleitet aus der Anzeige und ausschließlich aus deinen belegten Fähigkeiten.

**Nach der Bewerbung**
- Ergebnisprotokoll, Funnel mit Zeit bis zur ersten Antwort, Antwortmuster nach Quelle, Portal, Track und Spur mit
  Konfidenzintervallen sowie Score-Kalibrierung (Brier-Score, AUC), die dir sagt, wenn deine Schwelle falsch ist.
- Nachfrage nach Fähigkeiten in den gesichteten Anzeigen und die Lücken zu deinem Profil.
- Fällige Nachfassaktionen mit Nachrichtenentwurf; Fristen als Kalenderdateien.
- Vorbereitungsbögen für Vorstellungsgespräche, eine STAR+R-Story-Sammlung, deren Kennzahlen eine Quelle angeben
  müssen, und Leitfäden für Gehaltsverhandlungen.

**Berichte**
- Eine tägliche E-Mail-Zusammenfassung mit einem animierten Diagramm, das auch in Clients funktioniert, die nur
  das erste Bild zeigen, hellem und dunklem Design und einem Nur-Text-Teil.
- Benachrichtigungen über Telegram, Slack, Discord oder Teams mit einer einzigen Webhook-Einstellung.
- Ein Statusblock für jede beliebige Markdown-Datei, etwa die README eines privaten Repositorys.

<a id="compared-with-other-tools"></a>

## Vergleich mit anderen Tools

Basierend auf der öffentlichen README des jeweiligen Projekts im November 2026. Korrekturen sind willkommen.

| | JobVeyra | career-ops | LinkedIn AI Job Applier Ultimate | JobAppAgent |
|---|---|---|---|---|
| Absenden | Deine Wahl: Stapelfreigabe, automatisch oder nur ausfüllen | Füllt Formulare aus; du schickst ab | Schickt automatisch ab | Freigabe pro Bewerbung oder Stapel; Agent hält vor dem Absenden an |
| Was als beworben zählt | Nur die Bestätigung des Arbeitgebers | Nicht angegeben | Nicht angegeben | Nur eine sichtbare Bestätigung |
| Zustandsmodell | Eine persistente Warteschlange, 11 Zustände, Leases, absturzsicher | Markdown-Tracker | YAML-Ergebnisdateien | Protokolle |
| Freigabe an Anzeigeninhalt gebunden | Ja (über Inhalts-Hash signiert) | Entfällt (du schickst ab) | Kein Freigabeschritt | Freigabe gilt für das Angezeigte, 24 h |
| Quellen | Greenhouse, Lever, Ashby, Workable, SmartRecruiters, Recruitee, UN Careers, USAJOBS, Remotive, schema.org-Seiten, LinkedIn-Benachrichtigungen | Ashby, Greenhouse, Lever, Wellfound, LinkedIn-Benachrichtigungen | LinkedIn, Indeed | Katalog von Jobbörsen und Karriereseiten |
| Regionen | Geordnete, gewichtete Regionen pro Nutzer | Suchanfragen | Suchfilter | Suchfilter |
| Bewertung | 0–100 über 8 Dimensionen, Belegherkunft pro Dimension, Deckel für Schätzungen | 1–5 über Blöcke A–H, Belegherkunft, Deckel für Schätzungen | Interessen-Score 1–100 | Passungs-Score |
| Seriositätsprüfungen | Geschlossen, neu veröffentlicht, veraltet, dauerhaft, kein Gehalt, vager Titel | Verfügbarkeit, Neuveröffentlichung, Seriositätsblock | Nicht angegeben | Prüfung auf aktive Anzeige |
| Schutz vor Erfundenem | Zahlen, Daten, Arbeitgeber, Abschlüsse, Zertifikate | Zahlen und Fakten | Überspringt Fragen, die es nicht beantworten kann | Nur geprüfte Fakten |
| Score-Kalibrierung | Brier, AUC, Empfehlung zur Schwelle | Beratende Kalibrierung | Nicht angegeben | Nicht angegeben |
| Ergebnisanalyse | Funnel, Muster mit Intervallen, Nachfrage nach Fähigkeiten | Funnel, Muster, Kompetenzlücken | Fähigkeitsstatistiken | Ergebnisprotokolle |
| Täglicher Bericht | E-Mail-Zusammenfassung, Telegram, Webhooks | Nicht angegeben | Telegram | Nicht angegeben |
| Modell erforderlich | Nein (optional, maskiert) | Eine KI-CLI oder ein Evaluator | Ja | Ein Coding-Agent |
| Laufzeitumgebungen | Claude-Code-Plugin, AGENTS.md-CLIs, Docker, einfache CLI | Viele KI-CLIs, Docker | Python-App, Docker | Agenten-Skill plus CLI |

Wo die anderen heute vorne liegen: career-ops hat eine große Community, ein interaktives Terminal-Dashboard,
Unternehmensrecherche und Entwürfe für Kontaktanfragen sowie READMEs in 18 Sprachen; der LinkedIn Applier
automatisiert LinkedIn und Indeed direkt und hat ein lokales Web-Bedienfeld; JobAppAgent unterstützt über ein
optionales Cloud-Backend einen gemeinsamen Zustand auf mehreren Rechnern.

## Datenschutz

Deine Daten bleiben in deinem Workspace, niemals in diesem Repository. `jobveyra init` legt eine `.gitignore` an,
die den gesamten Workspace ausschließt. Keine Telemetrie, kein Backend. Modellaufrufe sind standardmäßig
deaktiviert und maskiert, wenn sie aktiv sind. Die Engine gibt nie Passwörter ein, löst keine CAPTCHAs, legt keine
Konten an, akzeptiert keine rechtlichen Erklärungen und verschickt keine E-Mails außer deiner eigenen
Zusammenfassung.

## Entwicklung

```bash
pip install -e ".[dev]"
pytest -q
```

Die Modulverträge stehen in [`docs/ARCHITECTURE.md`](../ARCHITECTURE.md). Die Tests laufen offline gegen
aufgezeichnete Fixtures für jede Quelle.

## Lizenz

MIT. Siehe [`LICENSE`](../../LICENSE) und [`NOTICE`](../../NOTICE).

---

> Maßgeblich ist die [englische README](../../README.md); Übersetzungen können hinterherhinken.
