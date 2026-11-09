<h1 align="center">JobVeyra</h1>

<p align="center">
  <a href="../../README.md">English</a> ·
  <a href="README.zh-CN.md">简体中文</a> ·
  <a href="README.zh-TW.md">繁體中文</a> ·
  <a href="README.ja.md">日本語</a> ·
  <a href="README.ko.md">한국어</a> ·
  <a href="README.fr.md">Français</a> ·
  <b>Español</b> ·
  <a href="README.pt-BR.md">Português</a> ·
  <a href="README.de.md">Deutsch</a> ·
  <a href="README.it.md">Italiano</a> ·
  <a href="README.ru.md">Русский</a> ·
  <a href="README.ar.md">العربية</a> ·
  <a href="README.hi.md">हिन्दी</a>
</p>

<p align="center">
  Un motor de búsqueda de empleo de código abierto que encuentra puestos en los lugares que tú eliges, puntúa
  cada uno con evidencias, prepara candidaturas honestas, envía solo lo que has aprobado y cada mañana te cuenta
  qué ha funcionado.
</p>

<p align="center">
  <a href="#quick-start">Inicio rápido</a> ·
  <a href="#how-it-works">Cómo funciona</a> ·
  <a href="#compared-with-other-tools">Comparativa</a> ·
  <a href="../ARCHITECTURE.md">Arquitectura</a> ·
  <a href="../../AGENTS.md">Reglas para agentes</a>
</p>

---

La mayoría de los agentes de búsqueda de empleo se detienen antes de «Enviar» y te dejan a ti el clic, o pulsan
«Enviar» en todo y cruzan los dedos. JobVeyra deja la decisión en tus manos, por espacio de trabajo:

| `policy.submission` | Qué ocurre |
|---|---|
| `batch_approve` (predeterminado) | Revisas una página con un lote de candidaturas y lo apruebas una sola vez. Cada aprobación se firma sobre el contenido exacto de la oferta; si la oferta cambia, vuelve a revisión. |
| `auto` | Se envía cada oferta que pasa tus filtros, tu umbral de puntuación y tu límite diario. |
| `fill_only` | Los formularios se rellenan y se detienen antes de «Enviar». El botón lo pulsas tú. |

En cualquier modo, una candidatura solo cuenta como enviada cuando queda registrada la confirmación del
empleador. Un formulario rellenado, un botón pulsado o una puntuación alta nunca cuentan como avance.

<a id="quick-start"></a>

## Inicio rápido

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

Después, deja que un agente trabaje la cola:

| Entorno | Configuración |
|---|---|
| Claude Code | `/plugin marketplace add EllenSyuu/JobVeyra` y luego `/plugin install jobveyra@jobveyra`; comandos `/jobveyra:search`, `/jobveyra:review`, `/jobveyra:apply`, `/jobveyra:digest` |
| Codex, OpenCode, Cursor, Gemini CLI, Copilot | Abre el espacio de trabajo; leen [`AGENTS.md`](../../AGENTS.md) (`GEMINI.md` apunta al mismo archivo) |
| Sin agente | Cada paso es un comando normal; consulta `jobveyra --help` |
| Docker | `docker build -t jobveyra .` y luego `docker run --rm -v "$PWD:/workspace" jobveyra discover` |

## Enfoca donde quieras

Dónde buscas es configuración, no código. Las regiones están ordenadas y ponderadas, el trabajo remoto puede
permitirse, exigirse o excluirse, y cada familia de puestos (un *track*) tiene sus propias palabras clave de
título, habilidades acreditadas y variante de CV.

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

El archivo completo y comentado está en [`examples/jobveyra.yml`](../../examples/jobveyra.yml).

<a id="how-it-works"></a>

## Cómo funciona

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

Cada oferta vive en una única cola persistente, con exactamente un estado y el motivo de ese estado
(`discovered`, `excluded`, `eligible`, `ready_to_submit`, `in_progress`, `submitted`,
`needs_check`, `retry_wait`, `blocked_auth`, `blocked_human`, `blocked_technical`).
Las transiciones no permitidas se rechazan, las concesiones caducan de forma segura y un fallo después del clic
en «Enviar» se convierte en `needs_check` en lugar de una candidatura duplicada.

## Qué hace

**Descubrimiento**
- Once adaptadores de fuentes que usan endpoints públicos sin inicio de sesión, con reintentos, espera
  exponencial, límite de peticiones por host y comprobación de robots.txt. El descubrimiento no consume llamadas
  a modelos.
- Filtros de región, remoto, nivel de experiencia (títulos en inglés, francés, español, portugués y alemán), tipo
  de contrato, título y empleador, cada uno con un motivo registrado cuando descarta una oferta.
- Deduplicación por empleador e identificador de vacante, y después por contenido de la oferta.

**Evaluación**
- Ocho dimensiones: habilidades, track, nivel de experiencia, ubicación, idioma, remuneración, actualidad y
  empleador. Cada una lleva evidencias etiquetadas según su origen: citadas de la oferta, leídas de campos
  estructurados o estimadas. Una dimensión respaldada solo por estimaciones tiene un tope.
- Los requisitos se separan en obligatorios y deseables antes de cruzar las habilidades.
- Los bloqueos duros terminan la evaluación: sin patrocinio de visado para un mercado en el que no puedes
  trabajar, un idioma obligatorio que no hablas a nivel B2 o superior, habilitación de seguridad, tipo de
  contrato, empleadores que evitas o una oferta cerrada.
- Señales de legitimidad: ofertas cerradas, republicadas, antiguas, bolsas de talento permanentes, sin salario,
  títulos imprecisos.
- Análisis de salarios en distintas monedas y periodos, anualizados y comparados con tu mínimo.
- Un modelo opcional (Anthropic, OpenAI, Ollama o cualquier endpoint compatible con OpenAI) puede añadir una
  coincidencia semántica de habilidades, limitada y etiquetada como estimación. Tu nombre, correo, teléfono y
  enlaces se enmascaran antes de cualquier llamada.

**Materiales**
- Control contra invenciones: cada número, fecha, empleador, título académico y certificación de un documento
  debe aparecer en tu base de datos de hechos.
- Control de expresiones autodespectivas en inglés, francés, español y portugués.
- Comprobación de texto para ATS: cobertura de palabras clave, datos de contacto, ruido de extracción.
- Enfoques para la carta de presentación sacados de la oferta y solo de tus habilidades acreditadas.

**Después de postularte**
- Registro de resultados, embudo con tiempo hasta la primera respuesta, patrones de respuesta por fuente, portal,
  track y carril con intervalos de confianza, y calibración de la puntuación (puntuación de Brier, AUC) que te
  avisa cuando tu umbral no es el adecuado.
- Demanda de habilidades en las ofertas que has visto, y las carencias respecto a tu perfil.
- Seguimientos pendientes con un borrador de mensaje; plazos como archivos de calendario.
- Fichas de preparación de entrevistas, un banco de historias STAR+R cuyas métricas deben citar una fuente, y
  guiones para negociar ofertas.

**Informes**
- Un resumen diario por correo con un gráfico animado que también funciona en clientes que solo muestran el
  primer fotograma, temas claro y oscuro, y una parte en texto plano.
- Notificaciones por Telegram, Slack, Discord o Teams con un solo ajuste de webhook.
- Un bloque de estado para cualquier archivo Markdown, como el README de un repositorio privado.

<a id="compared-with-other-tools"></a>

## Comparativa con otras herramientas

Basada en el README público de cada proyecto en noviembre de 2026. Se agradecen las correcciones.

| | JobVeyra | career-ops | LinkedIn AI Job Applier Ultimate | JobAppAgent |
|---|---|---|---|---|
| Envío | Tú eliges: aprobación por lotes, automático o solo rellenar | Rellena formularios; envías tú | Envía automáticamente | Aprobación por candidatura o por lote; el agente se detiene antes de enviar |
| Qué cuenta como postulación | Solo la confirmación del empleador | No se indica | No se indica | Solo una confirmación visible |
| Modelo de estados | Una cola persistente, 11 estados, concesiones, a prueba de fallos | Seguimiento en Markdown | Archivos de resultados YAML | Registros |
| Aprobación ligada al contenido de la oferta | Sí (firmada sobre el hash del contenido) | No aplica (envías tú) | Sin paso de aprobación | La aprobación cubre lo mostrado, 24 h |
| Fuentes | Greenhouse, Lever, Ashby, Workable, SmartRecruiters, Recruitee, UN Careers, USAJOBS, Remotive, páginas schema.org, alertas de LinkedIn | Ashby, Greenhouse, Lever, Wellfound, alertas de LinkedIn | LinkedIn, Indeed | Catálogo de portales y páginas de empleo |
| Regiones | Regiones ordenadas y ponderadas por usuario | Consultas de búsqueda | Filtros de búsqueda | Filtros de búsqueda |
| Puntuación | 0–100 en 8 dimensiones, origen de la evidencia por dimensión, tope para estimaciones | 1–5 en los bloques A–H, origen de la evidencia, tope para estimaciones | Puntuación de interés de 1 a 100 | Puntuación de encaje |
| Controles de legitimidad | Cerrada, republicada, antigua, permanente, sin salario, título impreciso | Vigencia, republicación, bloque de legitimidad | No se indica | Comprobación de oferta activa |
| Control contra invenciones | Números, fechas, empleadores, títulos académicos, certificaciones | Números y hechos | Omite las preguntas que no puede responder | Solo hechos verificados |
| Calibración de la puntuación | Brier, AUC, consejo sobre el umbral | Calibración orientativa | No se indica | No se indica |
| Analítica de resultados | Embudo, patrones con intervalos, demanda de habilidades | Embudo, patrones, carencias de habilidades | Estadísticas de habilidades | Registros de resultados |
| Informe diario | Resumen por correo, Telegram, webhooks | No se indica | Telegram | No se indica |
| Requiere modelo | No (opcional, enmascarado) | Una CLI de IA o un evaluador | Sí | Un agente de programación |
| Entornos | Plugin de Claude Code, CLI compatibles con AGENTS.md, Docker, CLI simple | Muchas CLI de IA, Docker | Aplicación Python, Docker | Skill de agente más CLI |

En qué van por delante las demás hoy: career-ops tiene una comunidad grande, un panel interactivo en la terminal,
investigación de empresas y redacción de mensajes de contacto, y README en 18 idiomas; el LinkedIn applier
automatiza LinkedIn e Indeed directamente y tiene un panel de control web local; JobAppAgent admite estado
compartido entre varios equipos mediante un backend opcional en la nube.

## Privacidad

Tus datos viven en tu espacio de trabajo, nunca en este repositorio. `jobveyra init` escribe un `.gitignore` que
excluye todo el espacio de trabajo. Sin telemetría, sin backend. Las llamadas a modelos están desactivadas por
defecto y, cuando se activan, se enmascaran. El motor nunca introduce contraseñas, resuelve CAPTCHA, crea cuentas,
acepta declaraciones legales ni envía más correo que tu propio resumen.

## Desarrollo

```bash
pip install -e ".[dev]"
pytest -q
```

Consulta [`docs/ARCHITECTURE.md`](../ARCHITECTURE.md) para ver los contratos de los módulos. Las pruebas se
ejecutan sin conexión con datos grabados de cada fuente.

## Licencia

MIT. Consulta [`LICENSE`](../../LICENSE) y [`NOTICE`](../../NOTICE).

---

> El [README en inglés](../../README.md) es la referencia; las traducciones pueden ir con retraso.
