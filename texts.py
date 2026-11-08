"""Every sentence the plugin says to a person, in English and French. English is the reference: a key missing
from FR falls back to it, so a new message never crashes a French session."""

from __future__ import annotations

EN = {
    # --- parsing ---------------------------------------------------------------------------------------------
    "bad_duration": "'{text}' is not a duration (examples: 45, 45m, 1h, 1h30)",
    "bad_day": "'{text}' is not a day (use today, tomorrow, +3, fri or 2026-11-12)",
    # --- rule validation -------------------------------------------------------------------------------------
    "bad_time": "'{text}' is not a time (use HH:MM, 24 hour clock)",
    "bad_range": "'{text}' is not a time range (use HH:MM-HH:MM)",
    "range_backwards": "'{text}' ends before it starts",
    "workdays_empty": "workdays needs at least one day (for example 1-5 or mon-fri)",
    "bad_weekday": "'{text}' is not a weekday (1 = Monday ... 7 = Sunday, or mon..sun)",
    "protected_form": "protected looks like lunch@12:30-13:30,gym@18:00-19:00 (or none)",
    "language_values": "language must be en or fr",
    "unknown_tz": "unknown timezone '{text}' (example: Europe/Paris; on Windows the tzdata package must be "
                  "installed). Leave it empty to use this computer's clock.",
    "int_needed": "{key} must be a whole number between {low} and {high}",
    "int_range": "{key} must be between {low} and {high}",
    "bad_calendar": "calendar must be none, google, ics:<file or https URL>, file:<json file> or "
                    "cmd:<program that prints event JSON; {{start}} and {{end}} are filled in>",
    "cmd_needs": "cmd: needs a program to run",
    "category_form": "category looks like admin:20 (typical minutes) or admin:none to remove it",
    "category_whole": "category minutes must be a whole number",
    "category_range": "category minutes must be between 5 and 480",
    "unknown_setting": "unknown setting '{key}'. Known: {known}",
    "set_by_you": "you set it on {when}",
    "set_auto": "detected in your Hermes profile on {when}",
    "set_default": "default, not set by you yet",
    # --- rules and tasks -------------------------------------------------------------------------------------
    "set_nothing": "Nothing to set. Example: /day set work_hours=09:00-17:30",
    "set_ok": "ok  {line}",
    "set_refused": "refused  {key}: {why}",
    "calendar_user_only": "the calendar source is yours to choose, an assistant cannot set it: type /day set "
                          "calendar=<google, ics:<https URL or file>, file:<json file>, cmd:<program>, or none> "
                          "yourself",
    "agent_calendar_user": "For the agent: the calendar source decides which program or address is run or read on "
                           "every plan, so no tool ever sets it, whatever the value (google, ics:, file:, cmd:, "
                           "none). Tell the user, in their language and plain words, to type it themselves: "
                           "/day set calendar=<source> in the chat; to take the Google calendar this profile "
                           "already has, /day setup auto. Do not retry with another spelling or another tool, and "
                           "do not run a command to set it yourself.",
    "guard_cron": "refused: the calendar source and the storage of the agenda planner are the user's to change, and "
                  "nobody is here to confirm it (this is a scheduled run). Do not look for another way.",
    "guard_ask": "agenda-guardian: this {tool} call would {what}. Allow it only if you asked for it. Call: {shown}",
    "guard_calendar": "set the calendar source (the program or address it names is run or read at every plan)",
    "guard_code": "change the planner's rules from code, which could set the calendar source",
    "guard_storage": "touch the planner's own folder or its database, where the calendar source is kept",
    "no_rules_warning": "None of your planning rules are set yet, so defaults are used. Run /day setup.",
    "cal_unreadable": "Calendar unreadable ({why}): the plan ignores your meetings.",
    "add_name": 'Give the task a name: /day add "Write the quote" 45m',
    "add_estimate": "How long do you think it will take? Add an estimate, e.g. /day add \"{name}\" 45m "
                    "(the planner learns from the gap between this and the real time).",
    "add_range": "An estimate must be between 5 minutes and 8 hours; split bigger tasks.",
    "add_priority": "Priority is 1 (most important), 2 or 3.",
    "added": "Added #{id}: {name} ({minutes} min, {category}, priority {priority}{tail})",
    "due_tail": ", due {day}",
    "tasks_none": 'No open task. Add one: /day add "Write the quote" 45m',
    "task_due": " due {day}",
    "done_need": "How long did '{name}' really take? /day done {id} <minutes> - that measurement is what makes "
                 "the next plan honest.",
    "done_range": "The real time must be between 1 minute and 16 hours.",
    "done_start": "{count} finished '{category}' task(s); calibration starts at {min}.",
    "done_now": "'{category}' estimates are now multiplied by {factor:g} ({count} measurements).",
    "done_msg": "Done #{id} {name}: {actual} min for an estimate of {est}. {calib}",
    "dropped": "Dropped #{id} {name}",
    # --- scheduling ------------------------------------------------------------------------------------------
    "need_session": "Scheduling needs a running Hermes session: send /day cron {action} from a chat.",
    "cron_refused": "Scheduling is refused inside a cron run: a scheduled job may not create or remove scheduled jobs "
                    "unless cron.allow_agent_scheduling is true in the Hermes config (it is not, or the config could "
                    "not be read). From a chat, /day cron on and /day cron off work.",
    "jobs_failed": "Hermes did not list its cron jobs, so nothing was changed ({why}).",
    "job_refused": "Hermes refused the {what} job: {why}",
    "scheduled": "Scheduled: a morning brief at {time} on your workdays, and a reminder check every 5 minutes "
                 "during work hours (it speaks only when a block is about to start or ended). Both run a small "
                 "script, no model call, no token cost. Scripts: {scripts}. Turn off: /day cron off",
    "unscheduled": "Removed {n} scheduled job(s).",
    "unscheduled_none": "Nothing was scheduled.",
    "sched_status": "Scheduled: {names}",
    "sched_status_none": "Nothing scheduled. Turn on: /day cron on 07:30",
    # --- commands --------------------------------------------------------------------------------------------
    "quote": "unbalanced quote in the command ({why})",
    "p_value": "p= must be 1, 2 or 3",
    "key_value": "'{token}' is not key=value. Example: /day set buffer_min=10",
    "done_usage": "/day done <# or name> <real minutes>",
    "drop_usage": "/day drop <# or name>",
    "cron_usage": "/day cron on [HH:MM] [deliver=telegram] | off | status",
    "unknown_cmd": "I do not know the command '{command}'. To ask in plain words, write it without /day (for example: "
                   "fit 3 sport sessions in my week). /day help lists the commands.",
    "nothing_now": "(nothing to say right now)",
    "help": """Just tell me what you want, in your own words, with or without /day: "put 3 sport sessions, 2 client calls in the morning and 2 hours of course a day in my week", "what is my day tomorrow?", "the walk took me 1h30". I show the plan with my reasons and write nothing to your calendar before your yes.
Two commands you type yourself:
/day write on|off   allow or forbid writing to your calendar
/day undo           take back what I wrote, nothing else
(/day help all lists every command.)""",
    "help_full": """Every command (you never need them: say it in words instead):
/day setup [auto]                  the rules to answer (work hours, focus, durations, calendar); auto adopts what Hermes already knows
/day set key=value ...             answer them, e.g. /day set work_hours=09:00-17:30 calendar=google
/day add "name" 45m [cat=admin] [p=1] [due=fri]   a task with YOUR estimate
/day list                          open tasks
/day plan [today|tomorrow|2026-11-12]   the plan, each block with its reason
/day now                           what to do right now
/day done <# or name> <real minutes>    log the real time (this calibrates the plan)
/day drop <# or name>              forget a task
/day brief                         the morning brief (today, or tomorrow after work hours)
/day cron on [HH:MM] [deliver=..]  send the brief every workday morning and remind you when a block starts
/day cron off | status             stop / check those two scheduled jobs (no model call, no token cost)
/day kind <name> real=2h before=15 after=30 window=18:00-22:00 days=mon,thu   what an activity really takes and when it fits (alone: the list)
/day habit <day> <HH:MM-HH:MM> <label>   something you do that is not in the calendar (alone: the list; rm <#>)
/day propose <activity> [count] [days=mon,thu]   where it could go, with the reasons; writes nothing
/day ok <proposal> [days=mon]      write a proposal to your Google calendar (needs /day write on, typed by you)
/day undo [last|all|<#>]           remove what this plugin wrote; never anything else
/day took <session # or activity> <minutes>   how long it really took (this corrects the next proposal)
/day write on|off|status           allow or forbid writing to your calendar""",
    # --- planner ---------------------------------------------------------------------------------------------
    "why_factor": "{planned} min = your estimate {est} x {value:g} (median of {count} finished '{category}' tasks)",
    "why_count": "{planned} min = your estimate ({count} finished '{category}' task{s}; calibration starts at 3)",
    "why_none": "{planned} min = your estimate (no finished '{category}' task yet)",
    "why_overdue": "overdue since {day}",
    "why_due": "due {day}",
    "why_priority": "priority {n}",
    "why_focus": "in your focus window",
    "rule_hours": "work hours {start}-{end} ({source})",
    "rule_protected": "{name} {start}-{end} kept free ({source})",
    "rule_focus": "focus window {spans} for priority 1 ({source})",
    "rule_buffer": "{n} min around meetings ({source})",
    "rule_blocks": "blocks of at most {max} min, {brk} min break ({source})",
    "rule_cap": "at most {n} tasks a day ({source})",
    "drop_nonworkday": "{day} is not one of your workdays (rule workdays, {source})",
    "drop_cap": "not among the {cap} tasks of the day (rule max_tasks_per_day, {source})",
    "drop_noroom": "needs {planned} min in blocks of at most {max}; only {fit} min fit before {end} "
                   "(short by {short} min)",
    "day_full": "The day is full: {names} does not fit. Move it, shorten it, or free time.",
    # --- calendar sources ------------------------------------------------------------------------------------
    "no_calendar": "No calendar connected: the plan ignores your meetings. Connect one with "
                   "/day set calendar=google (or ics:<file or URL>), or run /day setup.",
    "ics_https_only": "The calendar URL must start with https:// (plain http is refused: anyone on the network could read or alter it)",
    "ics_too_big": "The calendar answered with more than {mb} MB: it is ignored, check the address",
    "ics_cut": "The calendar answer was cut short on the way: it is ignored, try again",
    "recurring": "{n} recurring event(s) repeat monthly or yearly; only their first date is read, so later "
                 "repeats are missing from the plan",
    # --- setup -----------------------------------------------------------------------------------------------
    "setup_title": "Agenda guardian setup - about 3 minutes, refine anything later",
    "setup_count": "({n} rule(s) set by you so far; the rest are defaults)",
    "found_head": "Found in your Hermes profile",
    "found_tz": "[ok] Time zone: {tz}",
    "found_cal_ok": "[ok] Calendar ({kind}): readable, {n} event(s) today",
    "found_cal_bad": "[!!] Calendar ({kind}): {why}",
    "found_google": "[ok] Google Calendar: the google-workspace skill is connected, {n} event(s) today",
    "found_google_bad": "[!!] Google Calendar: skill found but not readable yet ({why})",
    "found_google_off": "[..] Google Calendar: the google-workspace skill is not installed; use "
                        "calendar=ics:<URL or file> or calendar=file:<json>",
    "found_jobs": "[..] Reminders already scheduled ({n}): {jobs} (left untouched)",
    "found_no_jobs": "[..] No reminder scheduled yet (the plugin can add two: /day cron on)",
    "found_lang": "[ok] Language: {lang}",
    "adopt": "Adopt what was found in one go: /day setup auto",
    "rules_head": "Your rules (answer with one line, keep the defaults that suit you)",
    "rule_line_hours": "work_hours=09:00-17:30   now {value} [{source}]",
    "rule_line_protected": "protected=lunch@12:30-13:30   now {value} [{source}]",
    "rule_line_focus": "focus=09:00-11:30   now {value} [{source}]   (kept for priority 1 tasks)",
    "rule_line_calendar": "calendar=google | ics:<file or https URL> | file:<json> | none   now {value}",
    "rule_line_language": "language=en | fr   now {value}",
    "fine_tune": "Fine tuning, whenever: workdays={days} max_block_min={block} break_min={brk} buffer_min={buf} "
                 "max_tasks_per_day={cap}. Typical minutes per kind of task: {cats}   category=admin:20 category=writing:60",
    "next_steps": 'Then: /day add "Write the quote" 45m, then /day plan. After each task, tell me the real time: '
                  "/day done <task> <minutes>. From the third finished task of a kind, the plan multiplies your "
                  "estimate by your median error and says so. Reminders: /day cron on.",
    "none": "none",
    "none_yet": "none yet",
    "auto_done": "Adopted from your Hermes profile:",
    "auto_nothing": "Nothing more to adopt: everything found is already set.",
    "auto_skip_cal": "Calendar not adopted: {why}",
    "auto_cal_user": "Calendar left to you: type /day setup auto yourself to adopt it (an assistant cannot set the "
                     "calendar source).",
    "agent_hint": "For the agent: before asking the user anything, use what you already know of them (memory, "
                  "profile notes, existing reminders, connected calendar) to propose each answer, then ask only to "
                  "confirm or complete. Speak the user's language, in plain sentences: never show the key=value "
                  "names or any command syntax, and turn loose answers (9h30, from 9 to 7, lunch around 1) into the "
                  "settings yourself. Save answers with the 'settings' argument. The calendar source is the one "
                  "setting you never save: when the profile shows a ready Google calendar, tell the user to type "
                  "/day setup auto; for any other source, /day set calendar=<source> (they type it themselves).",
    "unnamed": "(unnamed)",
    "found_google_nosignin": "[!!] Google Calendar: the google-workspace skill is installed but not signed in yet "
                             "(run its own setup first)",
    "ref_number": "no open task number {ref}",
    "ref_none": "no open task matches '{ref}'",
    "ref_several": "'{ref}' matches several tasks ({names}); use the number",
}

FR = {
    "bad_duration": "« {text} » n'est pas une durée (exemples : 45, 45m, 1h, 1h30)",
    "bad_day": "« {text} » n'est pas un jour (utilise aujourd'hui, demain, +3, ven ou 2026-11-12)",
    "bad_time": "« {text} » n'est pas une heure (format HH:MM, 24 h)",
    "bad_range": "« {text} » n'est pas une plage horaire (format HH:MM-HH:MM)",
    "range_backwards": "« {text} » finit avant de commencer",
    "workdays_empty": "workdays demande au moins un jour (par exemple 1-5 ou lun-ven)",
    "bad_weekday": "« {text} » n'est pas un jour de la semaine (1 = lundi ... 7 = dimanche, ou lun..dim)",
    "protected_form": "protected s'écrit déjeuner@12:30-13:30,sport@18:00-19:00 (ou none)",
    "language_values": "language doit valoir en ou fr",
    "unknown_tz": "fuseau horaire inconnu « {text} » (exemple : Europe/Paris ; sous Windows, le paquet tzdata doit "
                  "être installé). Laisse vide pour utiliser l'horloge de cet ordinateur.",
    "int_needed": "{key} doit être un nombre entier entre {low} et {high}",
    "int_range": "{key} doit être compris entre {low} et {high}",
    "bad_calendar": "calendar vaut none, google, ics:<fichier ou URL https>, file:<fichier json> ou "
                    "cmd:<programme qui affiche des événements en JSON ; {{start}} et {{end}} sont remplis>",
    "cmd_needs": "cmd: demande un programme à lancer",
    "category_form": "category s'écrit admin:20 (minutes habituelles) ou admin:none pour la retirer",
    "category_whole": "les minutes d'une catégorie sont un nombre entier",
    "category_range": "les minutes d'une catégorie sont comprises entre 5 et 480",
    "unknown_setting": "réglage inconnu « {key} ». Connus : {known}",
    "set_by_you": "tu l'as réglé le {when}",
    "set_auto": "détecté dans ton profil Hermes le {when}",
    "set_default": "valeur par défaut, pas encore réglée par toi",
    "set_nothing": "Rien à régler. Exemple : /day set work_hours=09:00-17:30",
    "set_ok": "ok  {line}",
    "set_refused": "refusé  {key} : {why}",
    "calendar_user_only": "la source d'agenda, c'est toi qui la choisis, un assistant ne peut pas la régler : tape "
                          "toi-même /day set calendar=<google, ics:<URL https ou fichier>, file:<fichier json>, "
                          "cmd:<programme>, ou none>",
    "guard_cron": "refusé : la source d'agenda et le stockage du planificateur, c'est l'utilisateur qui les change, et "
                  "personne n'est là pour confirmer (c'est une exécution programmée). Ne cherche pas un autre chemin.",
    "guard_ask": "agenda-guardian : cet appel {tool} va {what}. Autorise seulement si tu l'as demandé. Appel : {shown}",
    "guard_calendar": "fixer la source d'agenda (le programme ou l'adresse nommé est lancé ou lu à chaque plan)",
    "guard_code": "changer les règles du planificateur par du code, ce qui pourrait fixer la source d'agenda",
    "guard_storage": "toucher au dossier du planificateur ou à sa base, où la source d'agenda est gardée",
    "no_rules_warning": "Aucune de tes règles n'est encore réglée : les valeurs par défaut servent. "
                        "Lance /day setup.",
    "cal_unreadable": "Agenda illisible ({why}) : le plan ignore tes réunions.",
    "add_name": 'Donne un nom à la tâche : /day add "Rédiger le devis" 45m',
    "add_estimate": "Combien de temps penses-tu y passer ? Ajoute une estimation, par exemple /day add \"{name}\" "
                    "45m (le plan apprend de l'écart entre elle et le temps réel).",
    "add_range": "Une estimation va de 5 minutes à 8 heures ; découpe les tâches plus grosses.",
    "add_priority": "La priorité vaut 1 (la plus importante), 2 ou 3.",
    "added": "Ajouté n°{id} : {name} ({minutes} min, {category}, priorité {priority}{tail})",
    "due_tail": ", pour le {day}",
    "tasks_none": 'Aucune tâche ouverte. Ajoutes-en une : /day add "Rédiger le devis" 45m',
    "task_due": " pour le {day}",
    "done_need": "Combien de temps « {name} » a-t-il vraiment pris ? /day done {id} <minutes> : cette mesure rend "
                 "le prochain plan honnête.",
    "done_range": "Le temps réel va de 1 minute à 16 heures.",
    "done_start": "{count} tâche(s) « {category} » terminée(s) ; le calibrage démarre à {min}.",
    "done_now": "Les estimations « {category} » sont maintenant multipliées par {factor:g} ({count} mesures).",
    "done_msg": "Terminé n°{id} {name} : {actual} min pour une estimation de {est}. {calib}",
    "dropped": "Oublié n°{id} {name}",
    "cron_refused": "La planification est refusée dans une exécution de cron : une tâche planifiée ne crée ni ne "
                    "supprime de tâches planifiées, sauf si cron.allow_agent_scheduling vaut true dans la config "
                    "Hermes (ce n'est pas le cas, ou la config est illisible). Depuis un chat, /day cron on et "
                    "/day cron off fonctionnent.",
    "need_session": "La planification demande une session Hermes en marche : envoie /day cron {action} depuis une "
                    "conversation.",
    "jobs_failed": "Hermes n'a pas listé ses tâches planifiées, rien n'a été changé ({why}).",
    "job_refused": "Hermes a refusé la tâche {what} : {why}",
    "scheduled": "Planifié : un brief le matin à {time} les jours travaillés, et un contrôle des rappels toutes les "
                 "5 minutes pendant les heures de travail (il ne parle que lorsqu'un bloc va commencer ou vient de "
                 "finir). Les deux lancent un petit script, sans modèle, sans coût en jetons. Scripts : {scripts}. "
                 "Pour arrêter : /day cron off",
    "unscheduled": "{n} tâche(s) planifiée(s) retirée(s).",
    "unscheduled_none": "Rien n'était planifié.",
    "sched_status": "Planifié : {names}",
    "sched_status_none": "Rien de planifié. Pour activer : /day cron on 07:30",
    "quote": "guillemet non fermé dans la commande ({why})",
    "p_value": "p= vaut 1, 2 ou 3",
    "key_value": "« {token} » n'est pas de la forme clé=valeur. Exemple : /day set buffer_min=10",
    "done_usage": "/day done <n° ou nom> <minutes réelles>",
    "drop_usage": "/day drop <n° ou nom>",
    "cron_usage": "/day cron on [HH:MM] [deliver=telegram] | off | status",
    "unknown_cmd": "Je ne connais pas la commande « {command} ». Pour demander en mots simples, écris ta demande sans /day "
                   "(par exemple : place 3 séances de sport dans ma semaine). /day help liste les commandes.",
    "nothing_now": "(rien à dire pour l'instant)",
    "help": """Dis-moi simplement ce que tu veux, avec tes mots, avec ou sans /day : « mets 3 séances de sport, 2 appels clients le matin et 2 h de cours par jour dans ma semaine », « c'est quoi ma journée demain ? », « la promenade m'a pris 1h30 ». Je te montre le plan avec mes raisons et je n'écris rien dans ton agenda avant ton oui.
Deux commandes que tu tapes toi-même :
/day write on|off   autoriser ou interdire l'écriture dans ton agenda
/day undo           retirer ce que j'ai écrit, jamais autre chose
(/day help all liste toutes les commandes.)""",
    "help_full": """Toutes les commandes (tu n'en as jamais besoin : dis-le plutôt avec des mots) :
/day setup [auto]                  les réglages à faire (horaires, concentration, durées, agenda) ; auto reprend ce que Hermes sait déjà
/day set clé=valeur ...            les régler, ex. /day set work_hours=09:00-17:30 calendar=google
/day add "nom" 45m [cat=admin] [p=1] [due=ven]   une tâche avec TON estimation
/day list                          les tâches ouvertes
/day plan [today|demain|2026-11-12]     le plan, chaque bloc avec sa raison
/day now                           quoi faire maintenant
/day done <n° ou nom> <minutes réelles>     noter le temps réel (c'est ce qui calibre le plan)
/day drop <n° ou nom>              oublier une tâche
/day brief                         le brief du matin (aujourd'hui, ou demain après les heures de travail)
/day cron on [HH:MM] [deliver=..]  envoyer le brief chaque matin travaillé et te prévenir quand un bloc commence
/day cron off | status             arrêter / vérifier ces deux tâches planifiées (sans modèle, sans coût en jetons)
/day kind <nom> real=2h before=15 after=30 window=18:00-22:00 days=lun,jeu   ce qu'une activité prend vraiment et quand elle tient (seul : la liste)
/day habit <jour> <HH:MM-HH:MM> <nom>    ce que tu fais hors agenda (seul : la liste ; rm <n°>)
/day propose <activité> [nombre] [days=lun,jeu]   où la mettre, avec les raisons ; n'écrit rien
/day ok <proposition> [days=lun]   écrire une proposition dans ton agenda Google (demande /day write on, tapé par toi)
/day undo [last|all|<n°>]          retirer ce que ce plugin a écrit ; jamais autre chose
/day took <n° de séance ou activité> <minutes>   le temps réel (corrige la prochaine proposition)
/day write on|off|status           autoriser ou interdire l'écriture dans ton agenda""",
    "why_factor": "{planned} min = ton estimation {est} x {value:g} (médiane de {count} tâches « {category} » "
                  "terminées)",
    "why_count": "{planned} min = ton estimation ({count} tâche{s} « {category} » terminée{s} ; le calibrage "
                 "démarre à 3)",
    "why_none": "{planned} min = ton estimation (aucune tâche « {category} » terminée pour l'instant)",
    "why_overdue": "en retard depuis le {day}",
    "why_due": "pour le {day}",
    "why_priority": "priorité {n}",
    "why_focus": "dans ta plage de concentration",
    "rule_hours": "heures de travail {start}-{end} ({source})",
    "rule_protected": "{name} {start}-{end} laissé libre ({source})",
    "rule_focus": "plage de concentration {spans} pour la priorité 1 ({source})",
    "rule_buffer": "{n} min autour des réunions ({source})",
    "rule_blocks": "blocs de {max} min au plus, pause de {brk} min ({source})",
    "rule_cap": "{n} tâches par jour au plus ({source})",
    "drop_nonworkday": "le {day} n'est pas un de tes jours travaillés (règle workdays, {source})",
    "drop_cap": "ne fait pas partie des {cap} tâches du jour (règle max_tasks_per_day, {source})",
    "drop_noroom": "demande {planned} min en blocs de {max} au plus ; seulement {fit} min tiennent avant {end} "
                   "(il en manque {short})",
    "day_full": "La journée est pleine : {names} ne tient pas. Déplace-la, raccourcis-la ou libère du temps.",
    "no_calendar": "Aucun agenda connecté : le plan ignore tes réunions. Connectes-en un avec "
                   "/day set calendar=google (ou ics:<fichier ou URL>), ou lance /day setup.",
    "ics_https_only": "L'URL de l'agenda doit commencer par https:// (le http simple est refusé : quiconque est sur le réseau pourrait la lire ou la modifier)",
    "ics_too_big": "L'agenda a répondu plus de {mb} Mo : il est ignoré, vérifie l'adresse",
    "ics_cut": "La réponse de l'agenda a été coupée en route : elle est ignorée, réessaie",
    "recurring": "{n} événement(s) récurrent(s) se répètent chaque mois ou chaque année ; seule leur première date "
                 "est lue, les répétitions suivantes manquent donc au plan",
    "setup_title": "Réglage de l'agenda guardian - environ 3 minutes, tu pourras tout affiner plus tard",
    "setup_count": "({n} règle(s) réglée(s) par toi pour l'instant ; les autres sont des valeurs par défaut)",
    "found_head": "Ce que j'ai trouvé dans ton profil Hermes",
    "found_tz": "[ok] Fuseau horaire : {tz}",
    "found_cal_ok": "[ok] Agenda ({kind}) : lisible, {n} événement(s) aujourd'hui",
    "found_cal_bad": "[!!] Agenda ({kind}) : {why}",
    "found_google": "[ok] Google Agenda : la compétence google-workspace est connectée, {n} événement(s) aujourd'hui",
    "found_google_bad": "[!!] Google Agenda : compétence trouvée mais pas encore lisible ({why})",
    "found_google_off": "[..] Google Agenda : la compétence google-workspace n'est pas installée ; utilise "
                       "calendar=ics:<URL ou fichier> ou calendar=file:<json>",
    "found_jobs": "[..] Rappels déjà planifiés ({n}) : {jobs} (je n'y touche pas)",
    "found_no_jobs": "[..] Aucun rappel planifié pour l'instant (le plugin peut en ajouter deux : /day cron on)",
    "found_lang": "[ok] Langue : {lang}",
    "adopt": "Tout adopter d'un coup : /day setup auto",
    "rules_head": "Tes règles (réponds en une ligne, garde les valeurs par défaut qui te conviennent)",
    "rule_line_hours": "work_hours=09:00-17:30   actuellement {value} [{source}]",
    "rule_line_protected": "protected=déjeuner@12:30-13:30   actuellement {value} [{source}]",
    "rule_line_focus": "focus=09:00-11:30   actuellement {value} [{source}]   (gardée pour les tâches de priorité 1)",
    "rule_line_calendar": "calendar=google | ics:<fichier ou URL https> | file:<json> | none   actuellement {value}",
    "rule_line_language": "language=en | fr   actuellement {value}",
    "fine_tune": "Pour affiner, quand tu veux : workdays={days} max_block_min={block} break_min={brk} "
                 "buffer_min={buf} max_tasks_per_day={cap}. Minutes habituelles par type de tâche : {cats}   "
                 "category=admin:20 category=ecriture:60",
    "next_steps": 'Ensuite : /day add "Rédiger le devis" 45m, puis /day plan. Après chaque tâche, donne le temps '
                  "réel : /day done <tâche> <minutes>. Dès la troisième tâche terminée d'un type, le plan multiplie "
                  "ton estimation par ton erreur médiane et le dit. Rappels : /day cron on.",
    "none": "aucun",
    "none_yet": "aucune pour l'instant",
    "auto_done": "Repris de ton profil Hermes :",
    "auto_nothing": "Rien de plus à reprendre : tout ce qui a été trouvé est déjà réglé.",
    "auto_skip_cal": "Agenda non repris : {why}",
    "auto_cal_user": "Agenda laissé à toi : tape toi-même /day setup auto pour le reprendre (un assistant ne peut "
                     "pas régler la source d'agenda).",
    "unnamed": "(sans nom)",
    "found_google_nosignin": "[!!] Google Agenda : la compétence google-workspace est installée mais pas encore "
                             "connectée (lance d'abord son propre réglage)",
    "ref_number": "aucune tâche ouverte n°{ref}",
    "ref_none": "aucune tâche ouverte ne correspond à « {ref} »",
    "ref_several": "« {ref} » correspond à plusieurs tâches ({names}) ; utilise le numéro",
}


from .texts_agenda import DAYS as _DAYS  # noqa: E402
from .texts_agenda import EN as _EN  # noqa: E402
from .texts_agenda import FR as _FR  # noqa: E402

EN.update(_EN)
FR.update(_FR)


def day_name(lang: str, weekday: int) -> str:
    """Full weekday name, 1 = Monday."""
    return _DAYS["fr" if lang == "fr" else "en"][weekday - 1]


def join_and(lang: str, items: list[str]) -> str:
    """'a, b et c' (fr) / 'a, b and c' (en)."""
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + (" et " if lang == "fr" else " and ") + items[-1]


def hm(minutes: int) -> str:
    return f"{minutes // 60}h{minutes % 60:02d}" if minutes >= 60 else f"{minutes} min"


def tr(lang: str, key: str, /, **kw) -> str:
    text = (FR if lang == "fr" and key in FR else EN)[key]
    return text.format(**kw) if kw else text.replace("{{", "{").replace("}}", "}")
