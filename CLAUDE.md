# CLAUDE.md (agenda-guardian)

Plugin Hermes Agent (troisième plugin de la candidature au hackathon, date limite 11/11/2026 13 h PST = 22 h Paris).
Né d'un besoin réel : un agenda très structuré pour un TDAH, un assistant proactif, sans supposer un second cerveau
ni un agenda particulier.

## Règles
- Déterministe : aucun appel de modèle, nulle part (planificateur, brief, rappels). Les deux crons sont `no_agent`.
- Écriture dans un agenda externe : désactivée par défaut, activée seulement par `/day write on` tapé par Théo
  (aucun outil d'agent ne l'active), jamais sans un oui à une proposition qui donne ses raisons, uniquement des
  événements ajoutés (jamais modifiés) et marqués `[agenda-guardian:<séance>:<partie>]`. Toute suppression passe par
  `writer.remove` : id présent dans le registre `written` ET marqueur encore présent sur l'événement, sinon refus
  (`ForeignEvent`) ou laissé tel quel. Un événement créé par Théo n'est jamais touché. Les autres écritures :
  `HERMES_HOME/plugin-data/agenda-guardian/`, et après `/day cron on` deux scripts dans `HERMES_HOME/scripts/` et
  deux crons `agenda-guardian-*`.
- Tout texte affiché existe en anglais et en français dans `texts.py` (l'anglais est la référence, le français
  se tutoie) ; la langue vient de la config Hermes, du système, puis du réglage de l'utilisateur.
- Tout texte affiché reste explicable : un bloc dit d'où il vient (estimation, facteur de calibrage, échéance,
  règle) ; une règle non posée par l'utilisateur est marquée « default ».
- Un calendrier illisible ou absent donne un avertissement visible, jamais un jour vide silencieux.
- Un seul chemin d'écriture : tout ce qui s'écrit passe par une proposition (`day_propose`, `day_week_plan` ou
  `day_stage`, un plan composé par l'agent) puis `day_confirm`. La consigne système interdit tout autre outil
  d'agenda ; le plugin ne bloque pas les écritures Google des autres outils (le garde `pre_tool_call` ne couvre que les voies vers la
  source d'agenda, voir Pièges).
- Seul l'utilisateur fixe la source d'agenda (`calendar`) : aucun outil ne la pose, `google` et `none` compris
  (`apply_setting(..., from_tool=True)` refuse, `setup_auto(from_tool=True)` laisse l'agenda). `/day set … calendar=…` et
  `/day setup auto` tapés sont traités par le répartiteur (`commands.sets_calendar`), jamais réécrits pour l'agent.
- `guard.py` (hook `pre_tool_call`, 0.5.2) : pour `terminal`, `execute_code`, `write_file` et `patch`, la commande
  `hermes … guardian` qui pose `calendar` (`commands.sets_calendar`), les fonctions du paquet (`apply_setting`,
  `set_rules`, `save_profile` avec `calendar` dans le texte ; `setup_auto` et `agenda_guardian` seuls) et le dossier du
  plugin (`plugins/`, `plugin-data/`, `scripts/` + `agenda-guardian`) ou sa base passent par l'approbation de Hermes
  (`approve`, une `rule_key` = hachage de l'appel entier contenu compris, jamais une clé du plugin) ; en session de cron :
  `block`. L'invite montre l'appel entier s'il est court, sinon son début et chaque partie qui a déclenché, plus le
  contenu d'un `write_file` ou d'un `patch`. Ce n'est pas une frontière de sécurité (commande masquée, script écrit puis
  lancé : non vus, dit dans le README) ; une erreur du filtre laisse passer l'appel. Les motifs sont bornés et
  `{0,40}+` est possessif (Python 3.11+, comme Hermes) : sans cela la regex est quadratique voire cubique et gèle tous les
  outils (relecture du 8/11 : 67 s à 260 Ko ; maintenant 0,6 s au pire, test `LONG` de `test_guard.py`).
- Le programme d'agenda (script Google ou `cmd:`) démarre avec `sources._child_env` (PATH, HOME, locale, TZ,
  HERMES_HOME, plus le minimum Windows) : jamais une clé de fournisseur ni une variable de proxy.
- ICS par URL : `https` seul, toute adresse résolue publique, connexion à l'adresse vérifiée, redirection vers le même
  hôte seulement, ni proxy ni http (`sources.safe_urlopen`, défaut de `fetch_*` et de `Guardian`).
- `day_schedule` on/off est refusé dans une session de cron tant que `cron.allow_agent_scheduling` n'est pas vrai
  (config illisible = refus ; `status` reste permis).
- Chaque modification passe `python -m pytest tests -q` (359 tests), `hermes plugins validate .`, puis, si le cron,
  le tableau de bord, un outil ou le hook bougent, `tests/e2e_hermes.py` avec l'interpréteur de Hermes (dans un
  `HERMES_HOME` jetable : un dossier avec `config.yaml` qui active le plugin et une copie du plugin).
- README, PR et textes publics en anglais ; commits en français, format conventionnel.
- Jamais de données réelles dans le dépôt : la démo vient de `tests/make_demo_profile.py` (noms inventés).
- `platforms:` du catalogue = ce qui est réellement testé : Windows 11, Linux arm64 et, depuis le 8/11, la CI GitHub
  (`.github/workflows/ci.yml` : pytest, `hermes plugins validate` et `tests/e2e_hermes.py` sur ubuntu, windows et
  macos-latest, Hermes v0.22.7 installé par `uv sync --locked`) ; une version ne s'annonce macOS que si ce job est vert.

## Pièges
- Le dossier du dépôt n'est pas importable (tiret) : les tests chargent le paquet sous `agenda_guardian` ; les scripts
  de cron et `dashboard/plugin_api.py` font de même (`importlib`, `submodule_search_locations`).
- Un gitignore global qui ignore `dist/` est fréquent : `dashboard/dist/` s'ajoute avec `git add -f` (fichier par fichier,
  le hook refuse `git add -A`).
- `cronjob_manage list` renvoie `job_id`, pas `id` (constaté sur Hermes 0.22.7) ; `no_agent` + `script` : la sortie vide
  n'envoie rien, c'est ce qui rend le rappel silencieux.
- Un script de cron doit vivre sous `HERMES_HOME/scripts/` ; il porte en dur le dossier du plugin, le dossier de données
  et le home (`SCRIPT_TEMPLATE`), car le sous-processus du planificateur ne garantit ni `HERMES_HOME` ni `hermes_constants`.
- Un plan « à partir de maintenant » est mémorisé (table `plan_cache`) : les rappels suivent le plan mémorisé, sinon un
  replanning ferait annoncer deux fois un bloc. Les vues du tableau de bord ne mémorisent rien (`remember=False`).
- L'interpréteur de Hermes sous Windows (test) : `%LOCALAPPDATA%\hermes-hackathon\installs\…\venv\Scripts\python.exe`
  avec `HERMES_HOME=%LOCALAPPDATA%\hermes-hackathon`, `HERMES_INTERACTIVE=1` et `PYTHONPATH=…\hermes-agent` ;
  le serveur du tableau de bord de test s'arrête avec `hermes dashboard --stop`.
- Linux : testé dans un dossier `HERMES_HOME` isolé sur une machine arm64 (venv séparé pour pytest). Avec le fournisseur
  d'abonnement Claude, lancer `hermes` avec `env -u ANTHROPIC_BASE_URL` et sans passerelle de test restée vivante, sinon il refuse.
- Le script Google n'a ni `update` ni champ privé : le marqueur vit dans la description de l'événement, et déplacer une
  séance = `undo` puis nouvelle proposition. Aucun outil d'agent n'active l'écriture (test
  `test_no_tool_can_switch_calendar_writing_on`) : ne jamais en ajouter un.
- Prouvé sur un compte Google réel (A1, 2026-11-06) : lecture de huit semaines, puis écriture de trois événements
  marqués, relecture et suppression par `undo` ; agenda identique avant et après (empreinte des identifiants),
  interrupteur remis sur off. Les tests unitaires restent sur `tests/fakegoogle.py`, qui enregistre chaque appel.
- Vu en vrai (Telegram, A1, 2026-11-06, 0.3.0) : `/day <phrase>` renvoyait « commande inconnue » et toute l'aide ;
  l'agent, sans fiche pour les appels et la formation, a composé le planning à la main puis a écrit 19 événements
  par le skill Google, sans marque : `/day undo` ne les voit pas. D'où 0.4.0 : le hook `pre_gateway_dispatch`
  (`_plain_words` dans `__init__.py`) réécrit `/day <phrase>` en message normal ; `commands.KNOWN` liste les
  commandes du dispatcher (un test vérifie que chacune y est, à tenir à jour) ; `day_week_plan` place plusieurs
  activités d'un coup (`proposer.fill_days` pour « N par jour ») ; `day_stage` enregistre les blocs que l'agent
  compose ; une habitude absente depuis 3 semaines est jugée finie (`DayStat.over`).
- Vu en vrai (Telegram, A1, 2026-11-06, 0.3.0 puis 0.4.0, journaux et base de sessions de Hermes lus) : (1) l'historique
  écartait un jour libre cette semaine (« d'habitude pris, 5 des 8 dernières semaines ») : `propose` ne rendait presque
  rien, l'agent a refait le plan à la main (`gapi` par le terminal) ; (2) Théo a copié les formats de l'aide
  (`work_hours=09:00-19:00 protected=dejeuner@13H30-15h`, `real=90`) et a reçu l'aide complète (1717 caractères) au
  moins quatre fois ; (3) `day_kind` exigeait une plage horaire : l'agent a interrogé Théo ; (4) un `/day write`
  tapé pendant que l'agent répondait est arrivé à l'agent comme du texte (Hermes met la suite en file) ; (5) le crochet
  n'avait réécrit aucune phrase depuis la 0.4 (Théo n'avait tapé que des commandes). D'où 0.5.0 : l'historique ordonne
  les jours sans jamais écarter un jour libre (`Session.spare`, `rej_usual` ne sert plus que pour les jours non
  retenus), plage absente = heures de travail dites dans la réponse (`_default_window`), plus de séances que de jours
  = « N par jour », `day_took` sans séance retrouve la dernière question, `/day` + tout sauf `commands.DIRECT` va à
  l'agent, aide de 5 lignes sans format (`/day help all` pour la liste), consigne système réécrite (parler sans
  syntaxe, proposer un chiffre manquant et le dire, déplacer = `day_undo` puis replanifier).
- Les textes que l'agent relaie ne portent plus de syntaxe (`/day ok N`, `real=2h`, `/day kind ...`) : un test
  vérifie l'aide courte ; en ajouter un si un nouveau texte affiché cite une commande.
- Revue de Teknium (PR 149965, 8/11) : les quatre correctifs de la 0.5.1 sont codés, chacun avec un cas mauvais et un
  cas bon. Mesuré sur Windows : sans `SYSTEMROOT` un Python enfant n'obtient plus de résolution de noms
  (`getaddrinfo failed`), d'où la liste Windows de `_child_env` ; `is_public` donne le même verdict sur Python 3.13.5 et
  sur celui de Hermes (3.14.9) pour 39 adresses refusées et 12 acceptées ; l'ouvreur durci lit `https://www.python.org/`
  et refuse localhost, 127.0.0.1, http et une redirection vers un autre hôte (`https://www.github.com/`). `example.com`
  échoue sur ce poste (« unable to get local issuer certificate », même avec `urlopen` simple) : sonde réelle sur
  python.org.
- `pre_tool_call` (`guard.py`, 0.5.2), mesuré le 8/11 : `approve` et `request_tool_approval` existent aux étiquettes
  Hermes v0.22.7 et v0.23.0 (`gh api …/contents/hermes_cli/plugins.py?ref=…`), l'A1 est en 0.23.0. Hermes bloque (fail
  closed) un `pre_tool_call` qui dépasse `plugins.hook_callback_timeout` (30 s) : le garde ne lit ni config ni base.
  `block` l'emporte sur `approve` ; en cron `approvals.cron_mode` pourrait auto-approuver, d'où un `block` direct. Noms
  d'outils et arguments relevés dans Hermes : `terminal` (`command`, `workdir`), `execute_code` (`code`), `write_file`
  (`path`, `content`), `patch` (`path`, `old_string`, `new_string`, `patch` en V4A). Le test e2e remplace
  `tools.approval.request_tool_approval` par un enregistreur : l'invite interactive elle-même n'est pas exercée (avec
  `HERMES_INTERACTIVE=1` et sans terminal elle attendrait sur stdin). Le garde ne couvre pas les écritures Google des
  autres outils : décision de Théo si on veut l'étendre.
- Prouvé le 8/11 : le crochet `pre_gateway_dispatch` dans une vraie passerelle (Hermes 0.22.7, adaptateur IRC local, même
  entrée que Telegram dans `run_inbound.py`, vue dans la source, pas essayée sur Telegram) : `/day place deux séances…`
  réécrit puis `day_week_plan` appelé, `/day plan demain` et `/day set calendar=cmd:…` répondus par le répartiteur sans
  agent, écriture jamais activée. Un webhook ne peut pas porter un texte commençant par `/` (refus d'admission avant le
  crochet). La question de durée du job de rappel passe par `cron.scheduler.run_job` (e2e). macOS : CI verte (34 contrôles
  de l'e2e depuis le garde, validate, pytest) sur macos-latest arm64.
- Non prouvé : le crochet sur Telegram même, la 0.5.x sur le téléphone de Théo, l'invite d'approbation interactive du garde
  vue par un humain, la livraison Telegram/WhatsApp du rappel. Défaut vu : `/day set calendar="cmd:programme arg"` tapé dans
  le chat est refusé (« is not key=value ») car le découpage coupe au premier espace ; la forme `/day set
  "calendar=cmd:programme arg"` ou la CLI passe (ticket, pas corrigé : hors des quatre demandes).
- QA du 8/11 (clone neuf à `93d46b7`, Hermes 0.22.7, Windows 11 ; sondes écrites hors dépôt, rejouables) : 359 tests,
  `validate` et l'e2e (34 contrôles) verts ; sur Hermes v0.23.0 (venv par `uv sync --locked --python 3.14`) `validate` et
  l'e2e aussi. Tenu pour le README : environnement d'un programme enfant mesuré dans un vrai processus (liste exacte,
  aucune clé, aucun proxy), `is_public` (30 adresses refusées, 6 acceptées), connexion à l'adresse vérifiée sans seconde
  résolution, `localhost`/`127.0.0.1`/`[::1]`/`169.254.169.254` refusés, `day_setup` refuse `calendar` sous 8 écritures et
  5 formes d'arguments, `day_schedule on` refusé en cron (réglage absent, faux, YAML illisible) et accepté avec
  `cron.allow_agent_scheduling: true`, 52 appels du garde sur 260 Ko : 0,23 s au pire. Sans `SYSTEMROOT`, un Python
  enfant ne résout plus aucun nom (`getaddrinfo failed`, Errno 11003).
- Écarts mesurés le 8/11 : le garde laisse passer `calendar\=cmd:x` (bash) et `calendar^=cmd:x` (cmd.exe), ticket #8 ; la
  lecture ICS lit toute la réponse sans borne et une redirection avec `\@` est lue de deux façons, ticket #9 ; même sans
  espace, `/day set calendar="file:C:\…"` est refusé, commentaire du ticket #7 ; la section de consigne système fait 1 582
  caractères en anglais et 1 760 en français (le README disait « environ 1 700 »).
