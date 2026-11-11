let examples = {};

const form = document.querySelector("#query-form");
const message = document.querySelector("#message");
const status = document.querySelector("#status");
const submit = document.querySelector("#submit");
const history = document.querySelector("#history");
const clear = document.querySelector("#clear");
let sessionId = null;
let resultNumber = 0;
let busy = false;

function node(tag, text, className) {
  const el = document.createElement(tag);
  if (text) el.textContent = text;
  if (className) el.className = className;
  return el;
}

function renderReport(text, resultId) {
  const report = node("div", "", "report");
  let currentList = null;
  for (const line of text.split("\n")) {
    if (line.startsWith("## ")) {
      currentList = null;
      report.append(node("h2", line.slice(3)));
      continue;
    }
    if (!line.trim()) {
      currentList = null;
      continue;
    }
    const source = line.match(/^(\d+)\. \[([^\]]+)\]\((https:\/\/[^)\s]+)\)$/);
    if (source) {
      const [, number, title, href] = source;
      if (!currentList || currentList.tagName !== "OL") {
        currentList = node("ol");
        report.append(currentList);
      }
      const item = node("li");
      const link = node("a", title);
      link.href = href;
      link.id = `source-${resultId}-${number}`;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      item.append(link);
      currentList.append(item);
      continue;
    }
    if (line.startsWith("- ")) {
      if (!currentList || currentList.tagName !== "UL") {
        currentList = node("ul");
        report.append(currentList);
      }
      const item = node("li");
      for (const segment of line.slice(2).split(/(\[\d+\])/)) {
        if (/^\[\d+\]$/.test(segment)) {
          const link = node("a", segment, "citation");
          link.href = `#source-${resultId}-${segment.slice(1, -1)}`;
          item.append(link);
        } else {
          item.append(document.createTextNode(segment));
        }
      }
      currentList.append(item);
      continue;
    }
    currentList = null;
    report.append(node("p", line));
  }
  return report;
}

function renderTrace(calls) {
  const trace = node("details", "", "trace");
  trace.append(node("summary", `Research process · ${calls.length} events`));
  const list = node("ul", "", "trace-list");
  const first = Date.parse(calls[0]?.started_at);
  for (const event of calls) {
    const item = node("li");
    const title = event.args?.researcher ? `Lead → ${event.args.researcher}` :
      `${event.agent} · ${event.name.replaceAll("_", " ")}`;
    item.append(node("span", title, "trace-title"));
    const start = Date.parse(event.started_at);
    const end = Date.parse(event.ended_at);
    if (Number.isFinite(first) && Number.isFinite(start) && Number.isFinite(end)) {
      item.append(node("span", `Round ${event.round} · +${((start-first)/1000).toFixed(2)}s to +${((end-first)/1000).toFixed(2)}s`, "trace-time"));
    }
    const evidence = node("details");
    evidence.append(node("summary", "Arguments and result"));
    let result = event.result;
    try { result = JSON.parse(result); } catch { /* Keep plain text. */ }
    evidence.append(node("pre", JSON.stringify({ args: event.args, result }, null, 2)));
    item.append(evidence);
    list.append(item);
  }
  trace.append(list);
  return trace;
}

document.querySelectorAll("[data-example]").forEach((button) => button.addEventListener("click", () => {
  document.querySelectorAll("#version-fields select").forEach((select) => { select.value = ""; });
  if (!examples[button.dataset.example]) return;
  message.value = examples[button.dataset.example];
  message.focus();
}));

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (busy) return;
  const versions = [...document.querySelectorAll("#version-fields select")].filter((s) => s.value);
  let question = message.value.trim();
  if (versions.length) {
    question = `${question || "Check this pack and explain any documented conflicts."}\nMinecraft 1.21.1 Fabric selections: ${versions.map((s) => `${s.dataset.mod} ${s.selectedOptions[0].textContent} [${s.value}]`).join(", ")}.`;
  }
  if (!question) {
    status.textContent = "Enter a question or select a version.";
    message.focus();
    return;
  }
  busy = true;
  submit.disabled = true;
  clear.disabled = true;
  status.textContent = "Investigating version records and maintainer notes…";
  try {
    const response = await fetch("/chat", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: question, session_id: sessionId }),
    });
    if (!response.ok) throw Error("Request failed");
    const data = await response.json();
    sessionId = data.session_id;
    const result = node("article", "", "panel");
    result.tabIndex = -1;
    result.append(node("p", question, "result-question"), renderReport(data.response, ++resultNumber));
    if (data.tool_calls.length) result.append(renderTrace(data.tool_calls));
    history.append(result);
    result.focus({ preventScroll: true });
    result.scrollIntoView({ block: "start" });
    status.textContent = "Response ready.";
    message.value = "";
  } catch {
    status.textContent = "The request could not be completed. Try again.";
  } finally {
    busy = false;
    submit.disabled = false;
    clear.disabled = !sessionId;
  }
});

clear.addEventListener("click", async () => {
  if (!sessionId || busy) return;
  const previous = sessionId;
  sessionId = null;
  history.replaceChildren();
  message.value = "";
  clear.disabled = true;
  status.textContent = "New conversation.";
  try { await fetch(`/clear?session_id=${encodeURIComponent(previous)}`, { method: "POST" }); }
  catch { /* The new conversation uses a different session. */ }
  message.focus();
});

try {
  const response = await fetch("/catalog");
  if (!response.ok) throw Error("Catalog unavailable");
  const data = await response.json();
  examples = data.examples;
  const list = document.querySelector("#scope-list");
  list.replaceChildren();
  for (const mod of data.mods) {
    const item = node("li", mod.name);
    item.append(node("span", `${mod.count} ${mod.count === 1 ? "version" : "versions"}`));
    list.append(item);
    const field = node("div");
    const label = node("label", mod.name);
    label.htmlFor = `version-${mod.slug}`;
    const select = node("select");
    select.id = label.htmlFor;
    select.dataset.mod = mod.name;
    select.append(new Option("Not selected", ""));
    for (const version of mod.versions) {
      select.append(new Option(version.version_number, version.id));
    }
    field.append(label, select);
    document.querySelector("#version-fields").append(field);
  }
  document.querySelector("#snapshot").textContent = `Snapshot · ${data.retrieved_at.slice(0, 10)} UTC`;
} catch {
  document.querySelector("#scope-list").replaceChildren(node("li", "Version catalog unavailable."));
}
