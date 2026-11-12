<h1 align="center">JobVeyra</h1>

<p align="center">
  <a href="../../README.md">English</a> ·
  <a href="README.zh-CN.md">简体中文</a> ·
  <a href="README.zh-TW.md">繁體中文</a> ·
  <a href="README.ja.md">日本語</a> ·
  <a href="README.ko.md">한국어</a> ·
  <b>Français</b> ·
  <a href="README.es.md">Español</a> ·
  <a href="README.pt-BR.md">Português</a> ·
  <a href="README.de.md">Deutsch</a> ·
  <a href="README.it.md">Italiano</a> ·
  <a href="README.ru.md">Русский</a> ·
  <a href="README.ar.md">العربية</a> ·
  <a href="README.hi.md">हिन्दी</a>
</p>

<p align="center">
  Un moteur de recherche d'emploi open source qui trouve des postes là où vous le souhaitez, note chacun
  avec des preuves, prépare des candidatures honnêtes, n'envoie que ce que vous avez approuvé et vous dit
  chaque matin ce qui a marché.
</p>

<p align="center">
  <a href="#quick-start">Démarrage rapide</a> ·
  <a href="#how-it-works">Fonctionnement</a> ·
  <a href="#compared-with-other-tools">Comparaison</a> ·
  <a href="../ARCHITECTURE.md">Architecture</a> ·
  <a href="../../AGENTS.md">Règles des agents</a>
</p>

---

La plupart des agents de recherche d'emploi s'arrêtent avant « Envoyer » et vous laissent cliquer, ou bien
cliquent sur « Envoyer » partout en espérant que ça passe. Avec JobVeyra, c'est vous qui choisissez, pour
chaque espace de travail :

| `policy.submission` | Ce qui se passe |
|---|---|
| `batch_approve` (par défaut) | Vous relisez une page qui liste un lot de candidatures et vous l'approuvez une seule fois. Chaque approbation est signée sur le contenu exact de l'offre ; si l'offre change, elle revient en relecture. |
| `auto` | Chaque offre qui passe vos filtres, votre seuil de score et votre plafond quotidien est envoyée. |
| `fill_only` | Les formulaires sont remplis et s'arrêtent avant « Envoyer ». C'est vous qui cliquez. |

Quel que soit le mode, une candidature n'est comptée comme envoyée que lorsque la confirmation de l'employeur
est enregistrée. Un formulaire rempli, un bouton cliqué ou un score élevé ne comptent jamais comme un progrès.

<a id="quick-start"></a>

## Démarrage rapide

```bash
pip install "jobveyra[charts]"     # Python 3.10+; charts need Pillow

jobveyra init ~/my-search && cd ~/my-search
# edit jobveyra.yml (who you are, where you want to work, policy, sources)
# write your fact base in cv/master.md
jobveyra doctor
jobveyra discover && jobveyra evaluate
jobveyra status
```

Laissez ensuite un agent traiter la file d'attente :

| Environnement | Mise en place |
|---|---|
| Claude Code | `/plugin marketplace add EllenSyuu/JobVeyra` puis `/plugin install jobveyra@jobveyra` ; commandes `/jobveyra:search`, `/jobveyra:review`, `/jobveyra:apply`, `/jobveyra:digest` |
| Codex, OpenCode, Cursor, Gemini CLI, Copilot | Ouvrez l'espace de travail ; ils lisent [`AGENTS.md`](../../AGENTS.md) (`GEMINI.md` renvoie au même fichier) |
| Sans agent | Chaque étape est une simple commande ; voir `jobveyra --help` |
| Docker | `docker build -t jobveyra .` puis `docker run --rm -v "$PWD:/workspace" jobveyra discover` |

## Ciblez n'importe où

L'endroit où vous cherchez relève de la configuration, pas du code. Les régions sont ordonnées et pondérées,
le télétravail peut être autorisé, exigé ou exclu, et chaque famille de postes (un *track*) a ses propres
mots-clés de titre, ses compétences démontrées et sa variante de CV.

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

Le fichier complet et commenté se trouve dans [`examples/jobveyra.yml`](../../examples/jobveyra.yml).

<a id="how-it-works"></a>

## Fonctionnement

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

Chaque offre vit dans une seule file persistante, avec exactement un état et la raison de cet état
(`discovered`, `excluded`, `eligible`, `ready_to_submit`, `in_progress`, `submitted`,
`needs_check`, `retry_wait`, `blocked_auth`, `blocked_human`, `blocked_technical`).
Les transitions interdites sont rejetées, les baux expirent sans risque, et un plantage après le clic sur
« Envoyer » donne `needs_check` au lieu d'une candidature en double.

## Ce que fait JobVeyra

**Découverte**
- Onze adaptateurs de sources qui utilisent des points d'accès publics sans connexion, avec nouvelles tentatives,
  temporisation exponentielle, limite de débit par hôte et respect de robots.txt. La découverte ne coûte aucun
  appel de modèle.
- Filtres par région, télétravail, niveau d'expérience (titres en anglais, français, espagnol, portugais et
  allemand), type de contrat, titre et employeur, chacun avec une raison enregistrée lorsqu'il rejette une offre.
- Dédoublonnage par employeur et numéro de réquisition, puis par contenu de l'offre.

**Évaluation**
- Huit dimensions : compétences, track, niveau d'expérience, lieu, langue, rémunération, fraîcheur, employeur.
  Chacune s'appuie sur des preuves étiquetées selon leur origine : citées de l'offre, lues dans des champs
  structurés, ou estimées. Une dimension qui ne repose que sur des estimations est plafonnée.
- Les exigences sont séparées en obligatoires et souhaitées avant la mise en correspondance des compétences.
- Les critères bloquants mettent fin à l'évaluation : pas de parrainage de visa pour un marché où vous ne pouvez
  pas travailler, une langue exigée que vous ne parlez pas au niveau B2 ou plus, une habilitation de sécurité,
  le type de contrat, des employeurs que vous évitez, une offre close.
- Signaux de fiabilité : offres closes, republications, offres anciennes, viviers de talents permanents,
  salaire absent, titres vagues.
- Analyse des salaires dans toutes les devises et périodicités, ramenés à l'année et comparés à votre plancher.
- Un modèle facultatif (Anthropic, OpenAI, Ollama ou tout point d'accès compatible OpenAI) peut ajouter une
  correspondance sémantique des compétences, limitée et étiquetée comme estimation. Vos nom, courriel, téléphone
  et liens sont masqués avant tout appel.

**Documents**
- Garde-fou contre l'invention : chaque chiffre, date, employeur, diplôme et certification d'un document doit
  figurer dans votre base de faits.
- Garde-fou contre les formulations dévalorisantes, en anglais, français, espagnol et portugais.
- Vérification du texte pour les ATS : couverture des mots-clés, coordonnées, bruit d'extraction.
- Angles de lettre de motivation tirés de l'offre et uniquement de vos compétences démontrées.

**Après la candidature**
- Registre des résultats, entonnoir avec délai avant la première réponse, tendances de réponse par source,
  portail, track et voie avec intervalles de confiance, et calibration du score (score de Brier, AUC) qui vous
  signale quand votre seuil est mal réglé.
- Demande de compétences dans les offres consultées, et écarts par rapport à votre profil.
- Relances à faire avec un brouillon de message ; échéances sous forme de fichiers de calendrier.
- Fiches de préparation aux entretiens, une banque d'histoires STAR+R dont chaque indicateur doit citer une
  source, et des scripts de négociation d'offre.

**Rapports**
- Un résumé quotidien par courriel avec un graphique animé qui reste lisible dans les clients n'affichant que la
  première image, thèmes clair et sombre, et une version texte brut.
- Notifications Telegram, Slack, Discord ou Teams via un seul paramètre de webhook.
- Un bloc d'état à insérer dans n'importe quel fichier Markdown, par exemple le README d'un dépôt privé.

<a id="compared-with-other-tools"></a>

## Comparaison avec d'autres outils

D'après le README public de chaque projet en novembre 2026. Les corrections sont les bienvenues.

| | JobVeyra | career-ops | LinkedIn AI Job Applier Ultimate | JobAppAgent |
|---|---|---|---|---|
| Envoi | Au choix : approbation par lot, automatique ou remplissage seul | Remplit les formulaires ; vous envoyez | Envoi automatique | Approbation par candidature ou par lot ; l'agent s'arrête avant l'envoi |
| Ce qui compte comme candidature | Confirmation de l'employeur uniquement | Non précisé | Non précisé | Confirmation visible uniquement |
| Modèle d'état | Une file persistante, 11 états, baux, résistant aux plantages | Suivi en Markdown | Fichiers de résultats YAML | Registres |
| Approbation liée au contenu de l'offre | Oui (signée sur le hachage du contenu) | Sans objet (vous envoyez) | Pas d'étape d'approbation | L'approbation couvre ce qui a été affiché, 24 h |
| Sources | Greenhouse, Lever, Ashby, Workable, SmartRecruiters, Recruitee, UN Careers, USAJOBS, Remotive, pages schema.org, alertes LinkedIn | Ashby, Greenhouse, Lever, Wellfound, alertes LinkedIn | LinkedIn, Indeed | Catalogue de sites d'emploi et de pages carrières |
| Régions | Régions ordonnées et pondérées par utilisateur | Requêtes de recherche | Filtres de recherche | Filtres de recherche |
| Notation | 0–100 sur 8 dimensions, origine des preuves par dimension, plafond des estimations | 1–5 sur les blocs A–H, origine des preuves, plafond des estimations | Score d'intérêt de 1 à 100 | Score d'adéquation |
| Contrôles de fiabilité | Close, republiée, ancienne, permanente, sans salaire, titre vague | Disponibilité, republication, bloc de fiabilité | Non précisé | Vérification que l'offre est active |
| Garde-fou contre l'invention | Chiffres, dates, employeurs, diplômes, certifications | Chiffres et faits | Ignore les questions auxquelles il ne peut pas répondre | Faits vérifiés uniquement |
| Calibration du score | Brier, AUC, conseil sur le seuil | Calibration indicative | Non précisé | Non précisé |
| Analyse des résultats | Entonnoir, tendances avec intervalles, demande de compétences | Entonnoir, tendances, lacunes de compétences | Statistiques de compétences | Registres des résultats |
| Rapport quotidien | Résumé par courriel, Telegram, webhooks | Non précisé | Telegram | Non précisé |
| Modèle requis | Non (facultatif, masqué) | Une CLI d'IA ou un évaluateur | Oui | Un agent de programmation |
| Environnements | Plugin Claude Code, CLI compatibles AGENTS.md, Docker, CLI simple | Nombreuses CLI d'IA, Docker | Application Python, Docker | Compétence d'agent plus CLI |

Là où les autres ont de l'avance aujourd'hui : career-ops a une grande communauté, un tableau de bord interactif
dans le terminal, de la recherche d'entreprises et la rédaction de messages de prise de contact, ainsi que des
README en 18 langues ; le LinkedIn applier automatise directement LinkedIn et Indeed et dispose d'un panneau de
contrôle web local ; JobAppAgent gère un état partagé entre plusieurs machines grâce à un backend cloud facultatif.

## Confidentialité

Vos données restent dans votre espace de travail, jamais dans ce dépôt. `jobveyra init` écrit un `.gitignore`
qui exclut tout l'espace de travail. Pas de télémétrie, pas de backend. Les appels de modèle sont désactivés par
défaut et masqués lorsqu'ils sont activés. Le moteur ne saisit jamais de mot de passe, ne résout pas de CAPTCHA,
ne crée pas de compte, n'accepte aucune attestation juridique et n'envoie aucun courriel autre que votre propre
résumé.

Seule exception, qui dépend de vous : si vous enregistrez un consentement permanent avec vos propres mots (`jobveyra authorize --consent ...`), la déclaration générale d'exactitude et les conditions obligatoires de la dernière page sont cochées pour vous, uniquement si toutes les réponses du formulaire sont vérifiées ; une déclaration contredite par vos faits connus n'est jamais cochée.

## Développement

```bash
pip install -e ".[dev]"
pytest -q
```

Voir [`docs/ARCHITECTURE.md`](../ARCHITECTURE.md) pour les contrats des modules. Les tests s'exécutent hors ligne
sur des données enregistrées pour chaque source.

## Licence

MIT. Voir [`LICENSE`](../../LICENSE) et [`NOTICE`](../../NOTICE).

---

> Le [README en anglais](../../README.md) fait foi ; les traductions peuvent avoir du retard.
