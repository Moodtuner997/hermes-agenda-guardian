/**
 * Agenda Guardian: the "Today" tab of the Hermes dashboard.
 * A day timeline (meetings, protected time, focus window, planned blocks, a now line), the reason behind each
 * block, what does not fit, and the rules the plan used. Plain IIFE, no build step, React from the host SDK.
 */
(function () {
  "use strict";

  const SDK = window.__HERMES_PLUGIN_SDK__;
  if (!SDK || !window.__HERMES_PLUGINS__) return;

  const React = SDK.React;
  const h = React.createElement;
  const { useState, useEffect, useCallback } = SDK.hooks;
  const { Card, CardContent, Badge, Button, Input } = SDK.components;
  const API = "/api/plugins/agenda-guardian";
  const PX = 1.15; // pixels per minute

  const TEXT = {
    en: {
      title: "Today", today: "Today", planned: "planned", free: "free", notToday: "Not today", rules: "Rules used",
      why: "Why here", tasks: "Open tasks", add: "Add a task", name: "Task", minutes: "Minutes",
      priority: "Priority", realTime: "Real minutes", done: "Done", empty: "Nothing planned for this day.",
      pick: "Click a block to see why it is there.", meeting: "Meeting", noTasks: "No open task.",
      learn: "Log the real time: the plan learns your pace from it.",
      dayMode: "Day", weekMode: "Week", weekOf: "Week of", legendYours: "Your events", legendWritten: "Written by the plugin",
      legendProposed: "Proposed, waiting for you", pending: "Waiting for your answer", okBtn: "Write it", refuse: "Not this one",
      undo: "Take it back", reasons: "Why here", writeOff: "Writing is off: type /day write on yourself to allow it.",
      writeOn: "Writing is on, only after your click.", nothingWeek: "Nothing proposed. Ask your agent to fit an activity in.",
      pickWeek: "Click a written or proposed block to see it.",
    },
    fr: {
      title: "Aujourd'hui", today: "Aujourd'hui", planned: "planifié", free: "libre", notToday: "Pas aujourd'hui",
      rules: "Règles appliquées", why: "Pourquoi ici", tasks: "Tâches ouvertes", add: "Ajouter une tâche", name: "Tâche",
      minutes: "Minutes", priority: "Priorité", realTime: "Minutes réelles", done: "Fait",
      empty: "Rien de planifié ce jour-là.", pick: "Clique un bloc pour voir pourquoi il est là.", meeting: "Réunion",
      noTasks: "Aucune tâche ouverte.", learn: "Note le temps réel : le plan apprend ton rythme.",
      dayMode: "Jour", weekMode: "Semaine", weekOf: "Semaine du", legendYours: "Tes événements",
      legendWritten: "Écrit par le plugin", legendProposed: "Proposé, en attente de ton avis",
      pending: "En attente de ta réponse", okBtn: "L'écrire", refuse: "Pas celle-là", undo: "Le retirer",
      reasons: "Pourquoi ici", writeOff: "L'écriture est désactivée : tape /day write on toi-même pour l'autoriser.",
      writeOn: "L'écriture est activée, seulement après ton clic.",
      nothingWeek: "Rien de proposé. Demande à ton agent de caser une activité.",
      pickWeek: "Clique un bloc écrit ou proposé pour le voir.",
    },
  };

  function mins(hhmm) {
    const p = hhmm.split(":");
    return parseInt(p[0], 10) * 60 + parseInt(p[1], 10);
  }

  function shift(day, delta) {
    const d = new Date(day + "T12:00:00");
    d.setDate(d.getDate() + delta);
    return d.toISOString().slice(0, 10);
  }

  function hm(total) {
    return total >= 60 ? Math.floor(total / 60) + "h" + String(total % 60).padStart(2, "0") : total + " min";
  }

  function detail(error) {
    const text = String(error && error.message ? error.message : error);
    const at = text.indexOf("{");
    if (at >= 0) {
      try { return JSON.parse(text.slice(at)).detail || text; } catch (e) { /* not JSON */ }
    }
    return text;
  }

  function post(url, body) {
    return SDK.fetchJSON(url, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
  }

  // ---- timeline ---------------------------------------------------------------------------------------

  function Timeline(props) {
    const d = props.data, t = props.t;
    if (!d.work_hours) return h("p", { className: "ag-muted" }, t.empty);
    const top = Math.floor((mins(d.work_hours[0]) - 30) / 60) * 60;
    const bottom = Math.ceil((mins(d.work_hours[1]) + 30) / 60) * 60;
    const at = function (m) { return (m - top) * PX; };
    const box = function (start, end, cls, label, extra) {
      const s = mins(start), e = mins(end);
      return h("div", Object.assign({
        className: "ag-box " + cls,
        style: { top: at(s) + "px", height: Math.max(14, (e - s) * PX - 2) + "px" },
      }, extra || {}), label);
    };
    const lines = [];
    for (let m = top; m <= bottom; m += 60) {
      lines.push(h("div", { key: "l" + m, className: "ag-hour", style: { top: at(m) + "px" } },
        h("span", null, String(Math.floor(m / 60)).padStart(2, "0") + ":00")));
    }
    const layers = [];
    d.focus.forEach(function (f, i) { layers.push(box(f.start, f.end, "ag-focus", "", { key: "f" + i })); });
    d.protected.forEach(function (p, i) {
      layers.push(box(p.start, p.end, "ag-protected", p.name, { key: "p" + i }));
    });
    d.events.forEach(function (e, i) {
      if (!e.all_day) layers.push(box(e.start, e.end, "ag-event", e.start + " " + e.title, { key: "e" + i }));
    });
    d.blocks.forEach(function (b, i) {
      const part = b.parts > 1 ? " (" + b.part + "/" + b.parts + ")" : "";
      layers.push(box(b.start, b.end, "ag-task" + (props.selected === i ? " ag-selected" : ""),
        b.start + " " + b.task + part, { key: "b" + i, onClick: function () { props.onPick(i); }, title: b.why.join("; ") }));
    });
    if (d.now && mins(d.now) >= top && mins(d.now) <= bottom) {
      layers.push(h("div", { key: "now", className: "ag-now", style: { top: at(mins(d.now)) + "px" } }));
    }
    return h("div", { className: "ag-timeline", style: { height: (bottom - top) * PX + "px" } },
      lines, h("div", { className: "ag-layer" }, layers));
  }

  // ---- side panels ------------------------------------------------------------------------------------

  function TaskRow(props) {
    const task = props.task, t = props.t;
    const state = useState("");
    const value = state[0], setValue = state[1];
    return h("li", { className: "ag-task-row" },
      h("div", { className: "ag-task-main" },
        h("strong", null, "#" + task.id + " " + task.name),
        h("span", { className: "ag-muted" }, " " + task.est_min + " min · " + task.category + " · p" + task.priority +
          (task.due ? " · " + task.due : ""))),
      h("div", { className: "ag-inline" },
        h(Input, { type: "number", min: 1, placeholder: t.realTime, value: value, className: "ag-small",
                   onChange: function (e) { setValue(e.target.value); } }),
        h(Button, { size: "sm", disabled: !value, onClick: function () { props.onDone(task.id, parseInt(value, 10)); } }, t.done)));
  }

  function AddForm(props) {
    const t = props.t;
    const a = useState(""), name = a[0], setName = a[1];
    const b = useState(""), minutes = b[0], setMinutes = b[1];
    const c = useState("2"), priority = c[0], setPriority = c[1];
    return h("div", { className: "ag-form" },
      h(Input, { placeholder: t.name, value: name, onChange: function (e) { setName(e.target.value); } }),
      h("div", { className: "ag-inline" },
        h(Input, { type: "number", min: 5, placeholder: t.minutes, value: minutes, className: "ag-small",
                   onChange: function (e) { setMinutes(e.target.value); } }),
        h("select", { className: "ag-select", value: priority, onChange: function (e) { setPriority(e.target.value); } },
          ["1", "2", "3"].map(function (p) { return h("option", { key: p, value: p }, t.priority + " " + p); })),
        h(Button, { size: "sm", disabled: !name || !minutes, onClick: function () {
          props.onAdd({ name: name, minutes: parseInt(minutes, 10), priority: parseInt(priority, 10) });
          setName(""); setMinutes("");
        } }, t.add)));
  }

  // ---- page -------------------------------------------------------------------------------------------

  function Modes(props) {
    return h("div", { className: "ag-modes" },
      h(Button, { size: "sm", variant: props.mode === "day" ? "default" : "outline",
                  onClick: function () { props.onMode("day"); } }, props.t.dayMode),
      h(Button, { size: "sm", variant: props.mode === "week" ? "default" : "outline",
                  onClick: function () { props.onMode("week"); } }, props.t.weekMode));
  }

  function DayPage(props) {
    const a = useState(function () { return new URLSearchParams(window.location.search).get("day") || ""; }),
      day = a[0], setDay = a[1];
    const b = useState(null), data = b[0], setData = b[1];
    const c = useState(null), error = c[0], setError = c[1];
    const e = useState(-1), selected = e[0], setSelected = e[1];

    const load = useCallback(function () {
      SDK.fetchJSON(API + "/plan" + (day ? "?day=" + encodeURIComponent(day) : ""))
        .then(function (d) { setData(d); setError(null); })
        .catch(function (err) { setError(detail(err)); });
    }, [day]);
    useEffect(function () { load(); const timer = setInterval(load, 60000); return function () { clearInterval(timer); }; }, [load]);

    const act = function (promise) {
      promise.then(function () { setError(null); load(); }).catch(function (err) { setError(detail(err)); });
    };

    if (!data) return h("div", { className: "ag-page" }, error ? h("p", { className: "ag-error" }, error) : "…");
    const t = TEXT[data.language] || TEXT.en;
    const shown = data.day;
    const block = data.blocks[selected];

    return h("div", { className: "ag-page" },
      h("div", { className: "ag-head" },
        h("h1", null, (shown === data.today ? t.title + " · " : "") + shown),
        h("div", { className: "ag-inline" },
          h(Modes, { t: t, mode: "day", onMode: props.onMode }),
          h(Button, { size: "sm", variant: "outline", onClick: function () { setDay(shift(shown, -1)); setSelected(-1); } }, "‹"),
          h(Button, { size: "sm", variant: "outline", onClick: function () { setDay(""); setSelected(-1); } }, t.today),
          h(Button, { size: "sm", variant: "outline", onClick: function () { setDay(shift(shown, 1)); setSelected(-1); } }, "›"),
          h(Badge, null, hm(data.planned_min) + " " + t.planned + " · " + hm(data.free_min) + " " + t.free))),
      error ? h("p", { className: "ag-error" }, error) : null,
      data.warnings.map(function (w, i) { return h("p", { key: "w" + i, className: "ag-warn" }, "! " + w); }),
      h("div", { className: "ag-grid" },
        h(Card, null, h(CardContent, { className: "ag-card" },
          h(Timeline, { data: data, t: t, selected: selected, onPick: setSelected }),
          h("div", { className: "ag-detail" },
            block ? h("div", null, h("strong", null, t.why + " · " + block.task),
              h("ul", null, block.why.map(function (w, i) { return h("li", { key: i }, w); })))
              : h("p", { className: "ag-muted" }, t.pick)))),
        h("div", { className: "ag-side" },
          data.not_today.length ? h(Card, null, h(CardContent, { className: "ag-card" },
            h("h2", null, t.notToday),
            h("ul", null, data.not_today.map(function (n) {
              return h("li", { key: n.task_id }, h("strong", null, "#" + n.task_id + " " + n.task + ": "), n.detail);
            })))) : null,
          h(Card, null, h(CardContent, { className: "ag-card" },
            h("h2", null, t.tasks),
            data.tasks.length ? h("ul", { className: "ag-tasks" }, data.tasks.map(function (task) {
              return h(TaskRow, { key: task.id, task: task, t: t, onDone: function (id, m) {
                act(post(API + "/tasks/" + id + "/done", { minutes: m }));
              } });
            })) : h("p", { className: "ag-muted" }, t.noTasks),
            h("p", { className: "ag-muted" }, t.learn),
            h(AddForm, { t: t, onAdd: function (body) { act(post(API + "/tasks", body)); } }))),
          h(Card, null, h(CardContent, { className: "ag-card" },
            h("h2", null, t.rules),
            h("ul", { className: "ag-rules" }, data.rules.map(function (r, i) { return h("li", { key: i }, r); })))))));
  }

  // ---- the week: your events, what the plugin wrote, what it proposes -------------------------------------------

  const WPX = 0.62; // pixels per minute in the week grid

  function minutesOf(iso) {
    const d = new Date(iso);
    return d.getHours() * 60 + d.getMinutes();
  }

  function WeekPage(props) {
    const a = useState(""), weekOf = a[0], setWeekOf = a[1];
    const b = useState(null), data = b[0], setData = b[1];
    const c = useState(null), error = c[0], setError = c[1];
    const e = useState(null), picked = e[0], setPicked = e[1];

    const load = useCallback(function () {
      SDK.fetchJSON(API + "/week" + (weekOf ? "?week_of=" + encodeURIComponent(weekOf) : ""))
        .then(function (d) { setData(d); setError(null); })
        .catch(function (err) { setError(detail(err)); });
    }, [weekOf]);
    useEffect(function () { load(); const timer = setInterval(load, 60000); return function () { clearInterval(timer); }; }, [load]);

    const act = function (promise) {
      promise.then(function () { setError(null); setPicked(null); load(); }).catch(function (err) { setError(detail(err)); });
    };

    if (!data) return h("div", { className: "ag-page" }, error ? h("p", { className: "ag-error" }, error) : "…");
    const t = TEXT[data.language] || TEXT.en;
    const days = [];
    for (let i = 0; i < 7; i++) days.push(shift(data.week_start, i));

    let top = 8 * 60, bottom = 23 * 60;
    const all = [].concat(
      data.events.filter(function (x) { return !x.all_day; }).map(function (x) { return [x.start, x.end]; }),
      data.written.map(function (x) { return [x.start, x.end]; }),
      data.proposed.map(function (x) { return [x.block_start, x.block_end]; }));
    all.forEach(function (p) {
      top = Math.min(top, Math.floor(minutesOf(p[0]) / 60) * 60);
      bottom = Math.max(bottom, Math.ceil(minutesOf(p[1]) / 60) * 60);
    });
    bottom = Math.min(Math.max(bottom, top + 60), 24 * 60);
    const at = function (m) { return (m - top) * WPX; };
    const place = function (start, end, cls, label, key, extra) {
      const s = minutesOf(start), en = Math.max(minutesOf(end), s + 15);
      return h("div", Object.assign({ key: key, className: "ag-box " + cls,
        style: { top: at(s) + "px", height: Math.max(12, (en - s) * WPX - 2) + "px" } }, extra || {}), label);
    };
    const hourLines = [], hourLabels = [];
    for (let m = top; m <= bottom; m += 60) {
      hourLines.push(h("div", { key: "h" + m, className: "ag-hour", style: { top: at(m) + "px" } }));
      hourLabels.push(h("span", { key: "t" + m, style: { top: at(m) + "px" } }, String(Math.floor(m / 60)).padStart(2, "0") + ":00"));
    }
    const heightPx = (bottom - top) * WPX + "px";

    const columns = days.map(function (day) {
      const layers = [];
      data.events.forEach(function (x, i) {
        if (!x.all_day && x.start.slice(0, 10) === day) layers.push(place(x.start, x.end, "ag-event", x.title, "e" + i));
      });
      data.written.forEach(function (x, i) {
        if (x.start.slice(0, 10) !== day) return;
        const sel = picked && picked.kind === "written" && picked.row.event_id === x.event_id;
        layers.push(place(x.start, x.end, "ag-written" + (sel ? " ag-selected" : ""), x.summary, "w" + i,
          { onClick: function () { setPicked({ kind: "written", row: x }); } }));
      });
      data.proposed.forEach(function (x, i) {
        if (x.day !== day) return;
        const sel = picked && picked.kind === "proposed" && picked.row.proposal === x.proposal && picked.row.day === x.day;
        layers.push(place(x.block_start, x.block_end, "ag-proposed" + (sel ? " ag-selected" : ""),
          "? " + x.kind + " " + x.start.slice(11, 16), "p" + i,
          { onClick: function () { setPicked({ kind: "proposed", row: x }); } }));
      });
      return h("div", { key: day, className: "ag-week-col", style: { height: heightPx } }, hourLines, h("div", { className: "ag-layer" }, layers));
    });

    const proposals = {};
    data.proposed.forEach(function (x) { (proposals[x.proposal] = proposals[x.proposal] || []).push(x); });
    const pendingCards = Object.keys(proposals).map(function (id) {
      const rows = proposals[id];
      return h("div", { key: "pp" + id, className: "ag-pending" },
        h("strong", null, "#" + id + " · " + rows[0].kind + " × " + rows.length),
        h("ul", null, rows.map(function (x, i) { return h("li", { key: i }, x.weekday + " " + x.start.slice(11, 16) + "-" + x.end.slice(11, 16)); })),
        h("div", { className: "ag-inline" },
          h(Button, { size: "sm", disabled: !data.write_enabled, title: data.write_enabled ? "" : t.writeOff,
                      onClick: function () { act(post(API + "/proposals/" + id + "/ok", { days: "" })); } }, t.okBtn),
          h(Button, { size: "sm", variant: "outline", onClick: function () { act(post(API + "/proposals/" + id + "/refuse", {})); } }, t.refuse)));
    });

    let detailPanel = h("p", { className: "ag-muted" }, t.pickWeek);
    if (picked && picked.kind === "proposed") {
      detailPanel = h("div", null, h("strong", null, t.reasons + " · " + picked.row.kind + " " + picked.row.weekday),
        h("ul", null, picked.row.reasons.concat(picked.row.notes.map(function (n) { return "! " + n; }))
          .map(function (r, i) { return h("li", { key: i }, r); })));
    } else if (picked && picked.kind === "written") {
      detailPanel = h("div", null, h("strong", null, picked.row.summary + " · " + picked.row.start.slice(0, 16).replace("T", " ")),
        picked.row.link ? h("p", null, h("a", { href: picked.row.link, target: "_blank", rel: "noreferrer" }, picked.row.link)) : null,
        h(Button, { size: "sm", variant: "outline", onClick: function () { act(post(API + "/groups/" + picked.row.group_id + "/undo", {})); } }, t.undo));
    }

    return h("div", { className: "ag-page" },
      h("div", { className: "ag-head" },
        h("h1", null, t.weekOf + " " + data.week_start),
        h("div", { className: "ag-inline" },
          h(Modes, { t: t, mode: "week", onMode: props.onMode }),
          h(Button, { size: "sm", variant: "outline", onClick: function () { setWeekOf(shift(data.week_start, -7)); setPicked(null); } }, "‹"),
          h(Button, { size: "sm", variant: "outline", onClick: function () { setWeekOf(""); setPicked(null); } }, t.today),
          h(Button, { size: "sm", variant: "outline", onClick: function () { setWeekOf(shift(data.week_start, 7)); setPicked(null); } }, "›"),
          h(Badge, null, data.write_enabled ? t.writeOn : t.writeOff))),
      error ? h("p", { className: "ag-error" }, error) : null,
      data.warnings.map(function (w, i) { return h("p", { key: "w" + i, className: "ag-warn" }, "! " + w); }),
      h("div", { className: "ag-legend" },
        h("span", null, h("i", { className: "ag-event" }), t.legendYours),
        h("span", null, h("i", { className: "ag-written" }), t.legendWritten),
        h("span", null, h("i", { className: "ag-proposed" }), t.legendProposed)),
      h("div", { className: "ag-grid" },
        h(Card, null, h(CardContent, { className: "ag-card" },
          h("div", { className: "ag-week" },
            h("div", null),
            days.map(function (day) {
              return h("div", { key: "hd" + day, className: "ag-week-head" + (day === data.today ? " ag-today" : "") },
                new Date(day + "T12:00:00").toLocaleDateString(data.language, { weekday: "short", day: "2-digit" }));
            }),
            h("div", { className: "ag-week-hours", style: { height: heightPx } }, hourLabels),
            columns))),
        h("div", { className: "ag-side" },
          h(Card, null, h(CardContent, { className: "ag-card" },
            h("h2", null, t.pending),
            pendingCards.length ? pendingCards : h("p", { className: "ag-muted" }, t.nothingWeek))),
          h(Card, null, h(CardContent, { className: "ag-card" }, detailPanel)))));
  }

  function Page() {
    const a = useState("day"), mode = a[0], setMode = a[1];
    return mode === "week" ? h(WeekPage, { onMode: setMode }) : h(DayPage, { onMode: setMode });
  }

  window.__HERMES_PLUGINS__.register("agenda-guardian", Page);
})();
