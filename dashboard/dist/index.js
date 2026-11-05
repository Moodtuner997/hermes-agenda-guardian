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
      why: "Why here", tasks: "Open tasks", add: "Add a task", name: "Task", minutes: "Your estimate (min)",
      priority: "Priority", realTime: "Real minutes", done: "Done", empty: "Nothing planned for this day.",
      pick: "Click a block to see why it is there.", meeting: "Meeting", noTasks: "No open task.",
      learn: "Log the real time: the plan learns your pace from it.",
    },
    fr: {
      title: "Aujourd'hui", today: "Aujourd'hui", planned: "planifié", free: "libre", notToday: "Pas aujourd'hui",
      rules: "Règles appliquées", why: "Pourquoi ici", tasks: "Tâches ouvertes", add: "Ajouter une tâche", name: "Tâche",
      minutes: "Ton estimation (min)", priority: "Priorité", realTime: "Minutes réelles", done: "Fait",
      empty: "Rien de planifié ce jour-là.", pick: "Clique un bloc pour voir pourquoi il est là.", meeting: "Réunion",
      noTasks: "Aucune tâche ouverte.", learn: "Note le temps réel : le plan apprend ton rythme.",
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

  function Page() {
    const a = useState(""), day = a[0], setDay = a[1];
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

  window.__HERMES_PLUGINS__.register("agenda-guardian", Page);
})();
