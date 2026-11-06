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
  d'agenda ; le plugin ne peut pas le bloquer (voir Pièges).
- Chaque modification passe `python -m pytest tests -q` (103 tests), `hermes plugins validate .`, puis, si le cron,
  le tableau de bord, un outil ou le hook bougent, `tests/e2e_hermes.py` avec l'interpréteur de Hermes (dans un
  `HERMES_HOME` jetable : un dossier avec `config.yaml` qui active le plugin et une copie du plugin).
- README, PR et textes publics en anglais ; commits en français, format conventionnel.
- Jamais de données réelles dans le dépôt : la démo vient de `tests/make_demo_profile.py` (noms inventés).
- `platforms:` du catalogue = ce qui est réellement testé (Windows 11 et Linux arm64 ; macOS non testé).

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
- Non prouvé : la 0.4.0 sur Telegram (hook de réécriture sur une vraie passerelle, agent qui appelle
  `day_week_plan` au lieu d'écrire à la main), question de durée envoyée par le cron, livraison
  Telegram/WhatsApp, macOS.
