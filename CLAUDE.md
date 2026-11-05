# CLAUDE.md (agenda-guardian)

Plugin Hermes Agent (troisième plugin de la candidature au hackathon, date limite 11/11/2026 13 h PST = 22 h Paris).
Reprise du chantier : `.work/HANDOFF-hackathon-hermes.md` à la racine du parc. Né de la douleur de Théo : agenda
très structuré pour son TDAH, assistant proactif façon Instinct, sans supposer un second cerveau.

## Règles
- Déterministe : aucun appel de modèle, nulle part (planificateur, brief, rappels). Les deux crons sont `no_agent`.
- Aucune écriture dans un agenda externe, jamais. Les seules écritures : `HERMES_HOME/plugin-data/agenda-guardian/`,
  et après `/day cron on` deux scripts dans `HERMES_HOME/scripts/` et deux crons `agenda-guardian-*`.
- Tout texte affiché reste explicable : un bloc dit d'où il vient (estimation, facteur de calibrage, échéance,
  règle) ; une règle non posée par l'utilisateur est marquée « default ».
- Un calendrier illisible ou absent donne un avertissement visible, jamais un jour vide silencieux.
- Chaque modification passe `python -m pytest tests -q` (56 tests), `hermes plugins validate .`, puis, si le cron ou
  le tableau de bord bougent, `tests/e2e_hermes.py` avec l'interpréteur de Hermes.
- README, PR et textes publics en anglais ; commits en français, format conventionnel.
- Jamais de données réelles dans le dépôt : la démo vient de `tests/make_demo_profile.py` (noms inventés).
- `platforms:` du catalogue = ce qui est réellement testé (Windows 11 et Linux arm64 sur l'A1 ; macOS non testé).

## Pièges
- Le dossier du dépôt n'est pas importable (tiret) : les tests chargent le paquet sous `agenda_guardian` ; les scripts
  de cron et `dashboard/plugin_api.py` font de même (`importlib`, `submodule_search_locations`).
- `.gitignore_global` de Théo ignore `dist/` : `dashboard/dist/` s'ajoute avec `git add -f` (fichier par fichier,
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
- Linux : dossier de test isolé `/home/hermes/hk-test` de l'A1 (venv `pt` pour pytest, annulation : la ligne `rm -rf /home/hermes/hk-test` de `~/infra-undo.md`) ; un `hermes` lancé depuis ce shell
  doit être `env -u ANTHROPIC_BASE_URL` et sans passerelle de test restée vivante, sinon le fournisseur d'abonnement refuse.
- Non prouvé : compte Google réel (la source `google` est testée sur le format de sortie du script et un processus
  simulé), livraison Telegram/WhatsApp, macOS.
