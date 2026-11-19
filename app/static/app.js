"use strict";

const $ = (sel) => document.querySelector(sel);
const el = (tag, attrs = {}, ...kids) => {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else if (v !== false && v != null) node.setAttribute(k, v);
  }
  for (const kid of kids.flat()) if (kid != null && kid !== false) node.append(kid.nodeType ? kid : String(kid));
  return node;
};
const api = async (path, opts = {}) => {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.detail || `${res.status} ${res.statusText}`);
  return body;
};
const fmtDate = (iso) => new Date(iso + "T12:00:00").toLocaleDateString("en-CA", { weekday: "short", month: "short", day: "numeric" });
const sources = (list = [], verified = null) =>
  list.map((s) => el("span", { class: "src" + (verified && !verified.includes(s) ? " bad" : ""), title: "Source record" }, s));

let overview = null;

// ---- tabs ------------------------------------------------------------------
document.querySelectorAll(".tabs button").forEach((btn) =>
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tabs button").forEach((b) => b.setAttribute("aria-selected", b === btn));
    document.querySelectorAll(".panel").forEach((p) => (p.hidden = p.id !== `tab-${btn.dataset.tab}`));
  })
);

// ---- today -----------------------------------------------------------------
async function loadBriefing(day) {
  document.querySelectorAll(".day").forEach((d) => d.classList.toggle("selected", d.dataset.date === day));
  $("#brief-title").textContent = `Briefing: ${fmtDate(day)}`;
  $("#brief").textContent = "Writing the briefing...";
  try {
    const b = await api(`/api/briefing?day=${day}`);
    $("#brief").replaceChildren(renderBullets(b.text));
    $("#brief-tag").textContent = b.ai ? `Written by Gemini${b.cached ? " (cached)" : ""} from the facts below` :
      (b.note || "AI off: plain summary of the facts below");
    $("#brief-facts").textContent = JSON.stringify(b.facts, null, 1);
  } catch (e) {
    $("#brief").replaceChildren(el("span", { class: "error" }, e.message));
  }
}

function renderBullets(text) {
  // Model output is treated as plain text: citations become chips, nothing is parsed as HTML.
  const ul = el("ul");
  for (const line of text.split("\n").map((l) => l.replace(/^\s*[-*•]\s*/, "").trim()).filter(Boolean)) {
    const parts = line.split(/(\[[^\]]+\])/g).map((p) => (/^\[.+\]$/.test(p) ? el("span", { class: "src" }, p.slice(1, -1)) : p.replace(/\*\*/g, "")));
    ul.append(el("li", {}, parts));
  }
  return ul;
}

function renderDays() {
  const today = overview.today;
  $("#days").replaceChildren(
    ...overview.days.map((d) =>
      el("button", { class: "day" + (d.date < today ? " past" : ""), "data-date": d.date, onclick: () => loadBriefing(d.date) },
        el("div", { class: "d" }, `Day ${d.day} · ${fmtDate(d.date)}`),
        el("div", { class: "loc", title: d.locations.join(", ") }, d.locations.join(" → ")),
        el("div", { class: "loc" }, `${d.crew_call}-${d.est_wrap} · ${d.pages} pgs`),
        d.issues ? el("div", { class: "flag" }, `${d.issues} issue${d.issues > 1 ? "s" : ""}`) : el("div", { class: "ok" }, "No issues"))
    )
  );
}

// ---- issues ------------------------------------------------------------------
async function loadIssues() {
  const issues = await api("/api/issues");
  $("#issues").replaceChildren(
    ...issues.map((i) =>
      el("div", { class: `issue ${i.severity}` },
        el("div", { class: "sev" }, `${i.severity}${i.date ? " · " + fmtDate(i.date) : ""} · ${i.code}`),
        el("div", {}, el("strong", {}, i.title)),
        el("div", { class: "muted" }, i.detail),
        el("div", { class: "fix" }, "→ ", i.fix),
        el("div", {}, sources(i.sources)))
    )
  );
}

// ---- checklist ---------------------------------------------------------------
let items = [];
async function loadChecklist() {
  items = await api("/api/checklist");
  renderChecklist();
}
function renderChecklist() {
  const phase = $("#f-phase").value, status = $("#f-status").value, today = overview.today;
  const rows = items.filter((i) => (!phase || i.phase === phase) &&
    (status === "all" || (status === "done" ? i.status === "done" : i.status !== "done")));
  $("#checklist").replaceChildren(
    el("tr", {}, ["ID", "Task", "Dept", "Owner", "Due", "Status"].map((h) => el("th", {}, h))),
    ...rows.map((i) => {
      const select = el("select", { "aria-label": `Status of ${i.id}`, onchange: async (e) => {
        await api(`/api/checklist/${i.id}`, { method: "PATCH", body: JSON.stringify({ status: e.target.value }) });
        await Promise.all([loadChecklist(), loadIssues(), refreshOverview()]);
      } }, ["open", "in_progress", "done"].map((s) => el("option", { value: s, selected: s === i.status }, s.replace("_", " "))));
      const late = i.status !== "done" && i.due < today;
      return el("tr", {},
        el("td", {}, i.id),
        el("td", {}, i.task, i.depends_on.length ? el("div", { class: "muted" }, `after ${i.depends_on.join(", ")}`) : null,
          i.notes ? el("div", { class: "muted" }, i.notes) : null),
        el("td", {}, i.department), el("td", {}, i.owner || el("span", { class: "late" }, "unassigned")),
        el("td", { class: late ? "late" : "" }, fmtDate(i.due)), el("td", {}, select));
    })
  );
}
$("#f-phase").addEventListener("change", renderChecklist);
$("#f-status").addEventListener("change", renderChecklist);

// ---- ask -----------------------------------------------------------------------
const EXAMPLES = [
  "Is the warehouse ready for Thursday?",
  "Who has turnaround problems this week?",
  "What's Lily Chen working on and is her permit done?",
  "Which checklist items are overdue or have no owner?",
  "What scenes are at Kane House?",
];
$("#examples").replaceChildren(...EXAMPLES.map((q) => el("button", { type: "button", onclick: () => { $("#question").value = q; ask(q); } }, q)));
$("#ask-form").addEventListener("submit", (e) => { e.preventDefault(); ask($("#question").value); });

async function ask(question) {
  if (!question.trim()) return;
  const btn = $("#ask-form button");
  btn.disabled = true;
  const card = el("div", { class: "answer" }, el("div", { class: "q" }, question), el("div", { class: "muted" }, "Looking it up..."));
  $("#answers").prepend(card);
  try {
    const a = await api("/api/ask", { method: "POST", body: JSON.stringify({ question }) });
    card.replaceChildren(
      el("div", { class: "q" }, question),
      renderBullets(a.text),
      el("div", { class: "meta" },
        `Looked up: ${[...new Set(a.tools_used)].join(", ") || "nothing"}${a.cached ? " · cached" : ""}`,
        a.unverified_citations.length ? el("span", { class: "error" }, ` · ${a.unverified_citations.length} citation(s) not found in the lookups: check them`) : ""));
  } catch (e) {
    card.replaceChildren(el("div", { class: "q" }, question), el("div", { class: "error" }, e.message));
  } finally {
    btn.disabled = false;
  }
}

// ---- documents -------------------------------------------------------------------
function renderDocs() {
  $("#sheet-links").replaceChildren(
    ...overview.days.map((d) =>
      el("a", { href: `/documents/call-sheet/${d.date}`, target: "_blank", rel: "noopener" },
        `Day ${d.day} · ${fmtDate(d.date)} `, el("small", {}, d.has_call_sheet ? "issued" : "draft")))
  );
}
$("#upload-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const file = $("#pdf").files[0];
  if (!file) return;
  const out = $("#upload-result");
  out.hidden = false;
  out.textContent = "Reading with Gemini...";
  const form = new FormData();
  form.append("file", file);
  try {
    const res = await fetch("/api/call-sheets/upload", { method: "POST", body: form });
    const body = await res.json();
    if (!res.ok) throw new Error(body.detail);
    out.textContent = JSON.stringify(body, null, 1);
    await Promise.all([refreshOverview(), loadIssues()]);
  } catch (err) {
    out.textContent = "Error: " + err.message;
  }
});

// ---- start -----------------------------------------------------------------------
async function refreshOverview() {
  overview = await api("/api/overview");
  $("#title").textContent = overview.title;
  $("#subtitle").textContent = `${overview.company} · Today ${fmtDate(overview.today)} · ${overview.checklist.done}/${
    overview.checklist.open + overview.checklist.in_progress + overview.checklist.done} checklist items done`;
  const ai = $("#ai-pill");
  ai.textContent = overview.ai_enabled ? `AI on · ${overview.model}` : "AI off (no key)";
  ai.classList.toggle("on", overview.ai_enabled);
  $("#crit-pill").textContent = `${overview.counts.critical} critical`;
  $("#warn-pill").textContent = `${overview.counts.warning} warnings`;
  renderDays();
  renderDocs();
}

(async () => {
  await refreshOverview();
  await Promise.all([loadIssues(), loadChecklist()]);
  loadBriefing(overview.next_day || overview.today);
})();
