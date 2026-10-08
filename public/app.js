/* Praxis front end. Plain JavaScript, no build step.
 *
 * Everything that comes from the agent or the server is untrusted text, so it is only ever
 * put on the page with textContent (never innerHTML).
 */
"use strict";

const $ = (id) => document.getElementById(id);
const PLAN_ICON = { done: "✓", doing: "●", todo: "○" };
const CHECK_SHORT = {
  report: "Report opens", plain: "Plain totals right", euro: "Euro converted", dup_total: "Duplicate counted once",
  policy: "Big meals flagged", dup_flag: "Duplicate flagged", untouched: "Originals untouched",
};
const LEVER_NAME = { context: "Company facts", workspace: "A new ability", instructions: "Clear instructions", other: "Other" };
const LEVER_SWITCH = { context: "lv-context", workspace: "lv-tool", instructions: "lv-instr" };

let config = null;
let examples = [];
let running = false;
let lastScore = null;
const sessionRuns = []; /* real-AI runs made in this browser tab. Kept in memory only, never saved. */

/* ---------- tiny DOM helper ---------- */
function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else node.setAttribute(key, value);
  }
  for (const child of children) node.append(child);
  return node;
}
const clear = (node) => { while (node.firstChild) node.removeChild(node.firstChild); };

async function getJSON(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`Could not load ${url}`);
  return response.json();
}

/* ---------- tabs ---------- */
function setupTabs() {
  const tabs = [...document.querySelectorAll(".tab")];
  const select = (tab) => {
    for (const t of tabs) {
      const on = t === tab;
      t.setAttribute("aria-selected", String(on));
      $(t.getAttribute("aria-controls")).hidden = !on;
    }
    if (tab.id === "t-compare") loadCompare();
    if (tab.id === "t-receipts") loadReceipts();
  };
  tabs.forEach((tab, i) => {
    tab.addEventListener("click", () => select(tab));
    tab.addEventListener("keydown", (event) => {
      const move = { ArrowRight: 1, ArrowLeft: -1 }[event.key];
      if (!move) return;
      const next = tabs[(i + move + tabs.length) % tabs.length];
      next.focus();
      select(next);
    });
  });
}

/* ---------- scrolling ---------- */
function scrollToEl(node) {
  const header = document.querySelector("header.topbar");
  const top = node.getBoundingClientRect().top + window.scrollY - (header ? header.offsetHeight : 60) - 12;
  window.scrollTo({ top: Math.max(0, top), behavior: "smooth" });
}

/* ---------- notices ---------- */
function showNotice(kind, text, title) {
  const box = $("notice");
  clear(box);
  if (text) box.append(el("div", { class: `notice ${kind}`, role: "note" }, ...(title ? [el("b", { text: title })] : []), document.createTextNode(text)));
}
const DEMO_TITLE = "Practice run: a script is playing the AI's part";
const DEMO_NOTICE = "Nothing here is a real AI, so this score is for illustration, not a measurement. " +
  "To test a real AI, choose one in the \"The AI\" menu at the top and paste a free key.";

/* ---------- scoreboard (the 7 checks) ---------- */
const SB_IDS = ["report", "plain", "euro", "dup_total", "policy", "dup_flag", "untouched"];
function drawScoreboard(check) {
  const grid = $("sb-grid");
  clear(grid);
  const byId = {};
  if (check) for (const c of check.checks) byId[c.id] = c;
  const ids = check ? check.checks.map((c) => c.id) : SB_IDS;
  for (const id of ids) {
    const c = byId[id];
    const state = c ? (c.passed ? "pass" : "fail") : "";
    grid.append(el("li", { class: state, "data-id": id, style: `--i:${ids.indexOf(id)}` },
      el("span", { class: "sb-mark", "aria-hidden": "true", text: c ? (c.passed ? "✓" : "✗") : "–" }),
      el("span", { text: CHECK_SHORT[id] || (c && c.title) || id }),
      el("span", { class: "sr-only", text: c ? (c.passed ? " passed" : " failed") : " not run yet" })));
  }
  const score = $("sb-score");
  score.textContent = check ? `${check.score} of ${check.total} passed` : "Not run yet";
  score.className = check ? "sb-score has" : "sb-score";
}

/* ---------- the 4 rounds ---------- */
const ROUNDS = {
  baseline: {
    name: "No help",
    what: "Just the goal and 24 receipts. It has to guess the rest. This is the score to beat.",
    adds: null,
  },
  context: {
    name: "Add company facts",
    what: "Same job. Now it also knows facts only your company knows.",
    adds: ["Company facts", "The euro rate and the $75 meal limit."],
  },
  workspace: {
    name: "Add a new ability",
    what: "Same job. Now it is also allowed to do one more thing.",
    adds: ["A new ability", "Add a new sheet, so it can build a Flags list."],
  },
  instructions: {
    name: "Add clear instructions",
    what: "Same job. Now it is told exactly how you want it done.",
    adds: ["Clear instructions", "The sheet layout, and what to do with a duplicate."],
  },
};
const scores = {};
let freshName = null;
const reduceMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

function flagsNow() { return [$("lv-context").checked, $("lv-tool").checked, $("lv-instr").checked]; }
function matchSetup(flags) {
  return config.setups.find((s) => s.context === flags[0] && s.workspace === flags[1] && s.instructions === flags[2]);
}
function setupTitle(flags) {
  const m = matchSetup(flags);
  return m && ROUNDS[m.name] ? ROUNDS[m.name].name : "Your own mix";
}
function currentSetupLabel() { return setupTitle(flagsNow()); }

function applySetup(setup) {
  $("lv-context").checked = setup.context;
  $("lv-tool").checked = setup.workspace;
  $("lv-instr").checked = setup.instructions;
  refreshPanel();
}

function drawLadder(box, clickable) {
  clear(box);
  const current = matchSetup(flagsNow());
  config.setups.forEach((setup, i) => {
    const info = ROUNDS[setup.name] || { name: setup.label };
    const result = scores[setup.name];
    const pips = el("span", { class: `pips${freshName === setup.name ? " fresh" : ""}`, "aria-hidden": "true" });
    for (let k = 0; k < 7; k++) pips.append(el("i", { class: result && k < result.score ? "on" : "", style: `--k:${k}` }));
    const rung = el("button", { type: "button", class: `rung${result ? " done" : ""}`, "aria-pressed": String(Boolean(current && current.name === setup.name)) },
      el("span", { class: "rung-top" }, el("span", { class: "rung-no", text: String(i + 1) }), el("span", { class: "rung-name", text: info.name })),
      pips,
      el("span", { class: `rung-score${freshName === setup.name ? " fresh" : ""}`, text: result ? `Scored ${result.score} of ${result.total}` : "Not run yet" }));
    if (clickable) rung.addEventListener("click", () => { if (!running) applySetup(setup); });
    else rung.tabIndex = -1;
    box.append(el("li", {}, rung));
  });
}

let lastRoundKey = "";
function drawRound() {
  const current = matchSetup(flagsNow());
  const idx = current ? config.setups.indexOf(current) : -1;
  const info = current ? ROUNDS[current.name] : null;
  $("round-no").textContent = current ? `Round ${idx + 1} of ${config.setups.length}` : "Your own mix";
  $("round-title").textContent = info ? info.name : "A setup you mixed yourself";
  $("round-what").textContent = info ? info.what : "You chose your own combination in the advanced options. Run it and compare its score with the four rounds.";
  const adds = $("round-adds");
  clear(adds);
  if (info && info.adds) adds.append(el("b", { text: `New: ${info.adds[0]}.` }), document.createTextNode(" " + info.adds[1]));
  const bar = $("helpbar");
  clear(bar);
  [["Company facts", $("lv-context").checked], ["New ability", $("lv-tool").checked], ["Clear instructions", $("lv-instr").checked]].forEach(([label, on]) =>
    bar.append(el("span", { class: `hchip${on ? " on" : ""}` }, el("i", { "aria-hidden": "true", text: on ? "\u2713" : "" }), document.createTextNode(label))));
  const ran = current && scores[current.name];
  const roundKey = current ? current.name : "custom";
  if (roundKey !== lastRoundKey) {
    lastRoundKey = roundKey;
    const panel = $("round");
    panel.classList.remove("swap"); void panel.offsetWidth; panel.classList.add("swap");
  }
  $("run").textContent = current ? (ran ? `Run round ${idx + 1} again` : `Start round ${idx + 1}`) : "Run my mix";
}

function refreshPanel() {
  const provider = $("provider").value;
  const live = provider !== "demo";
  $("live-fields").hidden = !live;
  $("brain-badge").hidden = live;
  const info = config.providers.find((p) => p.id === provider);
  const ownKey = $("api-key").value.trim().length > 0;
  let note = "";
  let canRun = true;
  if (!live) {
    note = "Practice mode: a pre-written script plays the AI's part, so it runs in seconds with no sign-up. Want a real AI? Choose one in the menu at the top.";
  } else if (ownKey) {
    note = "Using your key for this run only. It is never stored.";
  } else if (info.server_key && config.runs_left > 0) {
    note = `Using the host's key. ${config.runs_left} live runs left today.`;
  } else if (info.server_key) {
    note = "The host's daily limit is used up. Paste your own key in the bar at the top, or play a recording.";
    canRun = false;
  } else {
    note = "Paste an API key in the bar at the top to run this AI. A free Gemini key: aistudio.google.com/apikey";
    canRun = false;
  }
  $("key-note").textContent = note;
  $("run").disabled = running || !canRun;
  $("run-mix").disabled = running || !canRun;
  $("cta-run").disabled = running;
  $("replay").disabled = running;
  const picked = [["Company facts", $("lv-context").checked], ["a new ability", $("lv-tool").checked], ["clear instructions", $("lv-instr").checked]].filter((x) => x[1]).map((x) => x[0]);
  $("setup-label").textContent = `Your mix: ${picked.length ? picked.join(" + ") : "no help (the goal only)"}`;
  $("mix-ai").textContent = live ? `It will run on: ${info.label}` : "It will run on: Practice mode (a script, not a real AI)";
  drawRound();
  drawLadder($("ladder"), true);
  drawLadder($("ladder2"), false);
  freshName = null;
}

function onProviderChange() {
  for (const key of Object.keys(scores)) delete scores[key];
  const info = config.providers.find((p) => p.id === $("provider").value);
  $("model").value = info ? info.default_model : "";
  refreshPanel();
}

/* ---------- plan ---------- */
function planNote(text) {
  const t = String(text).toLowerCase();
  if (t.includes("folder")) return "It lists the files so it knows what it has to read.";
  if (t.includes("read every")) return "It opens all 24 files one by one. They come in 4 different layouts.";
  if (t.includes("total") || t.includes("currenc")) return "It adds up the spending in each category. The euro receipt (120 EUR) must be turned into dollars first, and the duplicate counted only once.";
  if (t.includes("summary")) return "It writes the totals into a sheet called Summary in the spreadsheet.";
  if (t.includes("flag")) return "It lists problem receipts on a Flags sheet: meals over 75 USD (the \"big meals\") and the duplicate receipt.";
  return "";
}

function drawPlan(items) {
  const box = $("plan");
  clear(box);
  if (!items || !items.length) {
    $("plan-bar").style.width = "0";
    box.append(el("p", { class: "empty", text: "The plan appears once the agent starts." }));
    return;
  }
  const done = items.filter((i) => i.status === "done").length;
  $("plan-bar").style.width = `${Math.round((100 * done) / items.length)}%`;
  const list = el("ol");
  for (const item of items) {
    list.append(el("li", { class: `plan-${item.status}` },
      el("span", { class: "mark", "aria-hidden": "true", text: PLAN_ICON[item.status] || "○" }),
      el("span", {}, document.createTextNode(item.text), ...(planNote(item.text) ? [el("span", { class: "plan-why", text: planNote(item.text) })] : []),
        el("span", { class: "sr-only", text: ` (${item.status})` }))));
  }
  box.append(list, el("p", { class: "hint", text: `${done} of ${items.length} steps done` }));
}

/* ---------- activity feed ---------- */
function fileName(path) { return String(path ?? "").split("/").pop(); }
function describeTool(step) {
  const a = step.args || {};
  switch (step.name) {
    case "list_files": return "Looked at the files in the folder";
    case "read_file": return `Read ${fileName(a.path)}`;
    case "write_rows": return `Wrote ${(a.rows || []).length} row(s) to the ${a.sheet} sheet`;
    case "write_cell": return `Wrote ${a.value} into ${a.sheet} ${a.cell}`;
    case "add_sheet": return `Added a sheet called ${a.name}`;
    default: return `Used the ${step.name} tool`;
  }
}

let feed = null;
function startFeed() {
  feed = $("feed");
  clear(feed);
}

function addToFeed(step) {
  if (!feed) startFeed();
  const old = feed.querySelector(".f-wait");
  if (old) old.remove();
  if (step.type === "assistant") {
    $("live-status").textContent = step.text;
    feed.append(el("div", { class: "f-say" }, el("b", { text: "Agent: " }), document.createTextNode(step.text)));
  } else if (step.type === "plan") {
    drawPlan(step.items);
  } else if (step.type === "tool") {
    const text = String(step.observation ?? "").slice(0, 700);
    const row = el("details", { class: `f-act${step.ok ? "" : " bad"}` },
      el("summary", {}, el("span", { text: describeTool(step) }), el("code", { text: step.name })),
      el("pre", { text: step.ok ? text : `Error: ${text}` }));
    feed.append(row);
  } else if (step.type === "finish") {
    feed.append(el("div", { class: "f-done", text: `Finished: ${step.summary}` }));
  } else if (step.type === "error") {
    feed.append(el("div", { class: "f-err", text: `Stopped: ${step.message}` }));
  }
  if (running) feed.append(el("div", { class: "f-wait", text: "Working..." }));
  feed.scrollTop = feed.scrollHeight;
}

/* ---------- result ---------- */
function drawCoach(record) {
  const box = $("coach");
  clear(box);
  const hints = record.hints || [];
  const ranSetup = matchSetup([record.setup.context, record.setup.workspace, record.setup.instructions]);
  const idx = ranSetup ? config.setups.indexOf(ranSetup) : -1;
  const next = idx >= 0 ? config.setups[idx + 1] : null;
  const names = el("ul");
  for (const h of hints) names.append(el("li", { text: h.title }));

  if (!hints.length) {
    const toCompare = el("button", { type: "button", class: "btn", text: "Compare all four rounds" });
    toCompare.addEventListener("click", () => $("t-compare").click());
    box.append(el("div", { class: "coach win" },
      el("div", {}, el("h3", { text: "Perfect score" }),
        el("p", { text: "Every check passed. See how all four rounds compare, or run another round to try it yourself." })),
      toCompare));
    return;
  }
  if (next) {
    const info = ROUNDS[next.name];
    const button = el("button", { type: "button", class: "btn", text: `Start round ${idx + 2}: ${info.name.toLowerCase()}` });
    button.addEventListener("click", () => {
      applySetup(next);
      if (!$("run").disabled) runLive();
    });
    box.append(el("div", { class: "coach" },
      el("div", {}, el("h3", { text: "What it got wrong, and what to try next" }),
        el("p", { text: `Round ${idx + 2} gives it ${info.adds[0].toLowerCase()}. Run it and see if the score goes up.` }),
        el("p", { class: "hint", text: "It missed:" }), names),
      button));
    return;
  }
  if (idx >= 0) {
    box.append(el("div", { class: "coach" },
      el("div", {}, el("h3", { text: "It had all the help and still missed some" }),
        el("p", { text: "So these mistakes are the AI's own. Read its moves above to see where it slipped, then run the round again." }),
        names)));
    return;
  }
  const again = el("button", { type: "button", class: "btn", text: "Go back to round 1" });
  again.addEventListener("click", () => { applySetup(config.setups[0]); $("setup").scrollIntoView({ behavior: "smooth" }); });
  box.append(el("div", { class: "coach" }, el("div", {}, el("h3", { text: "Compare it with the four rounds" }), names), again));
}

let downloadUrl = null;
function bytesFromBase64(b64) {
  const raw = atob(b64);
  const out = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

function showResult(record, reportB64) {
  const check = record.check;
  drawScoreboard(check);
  $("live-status").textContent = "Done. Here is how it did.";
  const wait = $("feed").querySelector(".f-wait");
  if (wait) wait.remove();
  $("result").hidden = false;
  const big = $("big-score");
  clear(big);
  big.className = check.score === check.total ? "big-score good" : "big-score";
  const scoreNode = document.createTextNode(reduceMotion() ? String(check.score) : "0");
  big.append(scoreNode, el("small", { text: ` / ${check.total}` }));
  if (!reduceMotion()) {
    const started = performance.now();
    const tick = (now) => {
      const t = Math.min(1, (now - started) / 700);
      scoreNode.nodeValue = String(Math.round(check.score * (1 - Math.pow(1 - t, 3))));
      if (t < 1) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  }
  $("score-heading").textContent = check.score === check.total ? "Every check passed" : `${check.total - check.score} check(s) failed`;
  $("score-sub").textContent = `A script opened the real file and tested it. The agent saying "done" counts for nothing. Setup: ${setupTitle([record.setup.context, record.setup.workspace, record.setup.instructions])}.`;
  const delta = $("delta");
  delta.className = "delta";
  if (lastScore === null) {
    delta.textContent = "";
  } else if (check.score > lastScore) {
    delta.textContent = `Up from ${lastScore} on your last run.`; delta.classList.add("up");
  } else if (check.score < lastScore) {
    delta.textContent = `Down from ${lastScore} on your last run.`; delta.classList.add("down");
  } else {
    delta.textContent = `Same as your last run (${lastScore}).`;
  }
  lastScore = check.score;
  const list = $("checks");
  clear(list);
  for (const item of check.checks) {
    const pass = item.passed;
    list.append(el("li", { class: pass ? "pass" : "fail", style: `--i:${check.checks.indexOf(item)}` },
      el("span", { class: "ico", "aria-hidden": "true", text: pass ? "✓" : "✗" }),
      el("span", {},
        el("span", { class: "ctitle", text: item.title }),
        pass ? "" : el("span", { class: "cdetail", text: item.detail }),
        el("span", { class: "sr-only", text: pass ? " (passed)" : " (failed)" }))));
  }
  const ran = matchSetup([record.setup.context, record.setup.workspace, record.setup.instructions]);
  if (!record.demo) sessionRuns.push({ key: `${record.provider} / ${record.model}`, setup: ran ? ran.name : null, score: check.score, total: check.total, tools: record.steps.filter((x) => x.type === "tool").length, tokens: record.tokens_in + record.tokens_out, errored: Boolean(record.error) });
  if (ran && !record.error) { scores[ran.name] = { score: check.score, total: check.total }; freshName = ran.name; }
  $("result-title").textContent = `Result: ${setupTitle([record.setup.context, record.setup.workspace, record.setup.instructions])}`;
  refreshPanel();
  drawCoach(record);
  const link = $("download");
  if (downloadUrl) { URL.revokeObjectURL(downloadUrl); downloadUrl = null; }
  if (reportB64) {
    const blob = new Blob([bytesFromBase64(reportB64)], { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" });
    downloadUrl = URL.createObjectURL(blob);
    link.href = downloadUrl;
    link.download = "expense_report.xlsx";
    link.hidden = false;
  } else {
    link.hidden = true;
  }
  const model = record.demo ? `DEMO (scripted, not an AI): ${record.provider} / ${record.model}` : `${record.provider} / ${record.model}`;
  const tokens = record.tokens_in + record.tokens_out;
  $("meta").textContent = `Took ${record.seconds} seconds${record.demo ? "" : ` and ${tokens.toLocaleString()} tokens`} with ${model}.`;
  scrollToEl($("result"));
}

function resetRun() {
  $("watch-title").textContent = `Watching: ${currentSetupLabel()}`;
  $("live-status").textContent = "Starting...";
  $("result").hidden = true;
  $("watch").hidden = false;
  drawScoreboard(null);
  drawPlan([]);
  startFeed();
  scrollToEl($("watch"));
}

function setRunning(value, status = "") {
  running = value;
  $("status").textContent = status;
  refreshPanel();
}

/* ---------- live run (Server-Sent Events over fetch) ---------- */
function parseBlock(block) {
  let event = "message";
  const data = [];
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
  }
  return data.length ? { event, data: JSON.parse(data.join("\n")) } : null;
}

async function runLive() {
  const body = {
    provider: $("provider").value,
    model: $("model").value.trim() || null,
    api_key: $("api-key").value.trim() || null,
    context: $("lv-context").checked,
    workspace: $("lv-tool").checked,
    instructions: $("lv-instr").checked,
    overrides: { context: $("tx-context").value, instructions_clear: $("tx-instr").value },
  };
  resetRun();
  setRunning(true, "Starting...");
  let finished = false;
  let stoppedEarly = false;
  try {
    const response = await fetch("/api/run", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (!response.ok) {
      const detail = (await response.json().catch(() => ({}))).detail;
      throw new Error(typeof detail === "string" ? detail : "The server could not start the run.");
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let cut;
      while ((cut = buffer.indexOf("\n\n")) >= 0) {
        const block = buffer.slice(0, cut);
        buffer = buffer.slice(cut + 2);
        const message = parseBlock(block);
        if (!message) continue;
        if (message.event === "start") {
          showNotice(message.data.demo ? "demo" : "live", message.data.demo ? DEMO_NOTICE : `${message.data.provider} / ${message.data.model}. This is a real AI, so the score is a real measurement.`, message.data.demo ? DEMO_TITLE : "Real AI run");
          setRunning(true, "The agent is working...");
        } else if (message.event === "step") {
          addToFeed(message.data);
        } else if (message.event === "result") {
          finished = true;
          running = false;
          stoppedEarly = Boolean(message.data.record.error);
          showResult(message.data.record, message.data.report_b64);
        } else if (message.event === "error") {
          finished = true;
          throw new Error(message.data.message);
        }
      }
    }
    if (!finished) throw new Error("The connection closed before the run finished. Try again.");
    setRunning(false, stoppedEarly ? "The run stopped early. See the last line of the activity list." : "Done.");
  } catch (error) {
    running = false;
    addToFeed({ type: "error", message: error.message });
    setRunning(false, "The run did not finish.");
  }
}

/* ---------- replay ---------- */
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function replay() {
  const id = $("replay-pick").value;
  if (!id) return;
  resetRun();
  setRunning(true, "Playing the recording...");
  try {
    const { record, report_b64 } = await getJSON(`/api/examples/${encodeURIComponent(id)}`);
    showNotice(record.demo ? "demo" : "live", record.demo ? DEMO_NOTICE : `Recording of a saved real run with ${record.provider} / ${record.model}.`, record.demo ? "Recording of a practice run" : "Recording of a real run");
    for (const step of record.steps) {
      addToFeed(step);
      await sleep(step.type === "tool" ? 90 : 160);
    }
    running = false;
    showResult(record, report_b64);
    setRunning(false, "Recording finished.");
  } catch (error) {
    running = false;
    setRunning(false, error.message);
  }
}

/* ---------- compare tab ---------- */
let compareFiles = null;
let compareChoice = null;
let seenRuns = 0;

function sessionResults(key) {
  const runs = sessionRuns.filter((r) => r.key === key);
  const rows = config.setups.map((setup) => {
    const mine = runs.filter((r) => r.setup === setup.name);
    if (!mine.length) return { label: setup.label, none: true };
    const avg = (f) => mine.reduce((sum, r) => sum + f(r), 0) / mine.length;
    return {
      label: setup.label, runs: mine.length, total: mine[0].total,
      avg_score: avg((r) => r.score), avg_tool_calls: avg((r) => r.tools).toFixed(1), avg_tokens: Math.round(avg((r) => r.tokens)),
      errored_runs: mine.filter((r) => r.errored).length,
    };
  });
  return { provider: key, rows };
}

function drawCompare(rows, headline, notes) {
  const body = $("compare-body");
  clear(body);
  notes.forEach(([cls, text]) => body.append(el("div", { class: cls, role: "note", text })));
  body.append(el("p", { class: "lede", text: headline }));
  const bars = el("div", { class: "bars" });
  const table = el("table", { class: "cmp" }, el("thead", {}, el("tr", {},
    ...["Setup", "Average score", "Tool calls", "Tokens", "Errored runs"].map((h) => el("th", { text: h })))));
  const tbody = el("tbody");
  for (const row of rows) {
    const fill = el("span", { class: "fill" });
    if (row.none) {
      fill.style.width = "0%";
      bars.append(el("div", { class: "bar-row" }, el("span", { class: "bar-label", text: row.label }), el("span", { class: "track" }, fill), el("span", { class: "bar-value", text: "Not run yet" })));
      tbody.append(el("tr", {}, el("td", { text: row.label }), el("td", { text: "Not run yet", colspan: "4" })));
      continue;
    }
    fill.style.width = `${row.total ? Math.round((100 * row.avg_score) / row.total) : 0}%`;
    bars.append(el("div", { class: "bar-row" },
      el("span", { class: "bar-label", text: row.label }),
      el("span", { class: "track" }, fill),
      el("span", { class: "bar-value", text: `${Number(row.avg_score).toFixed(1)} of ${row.total}` })));
    tbody.append(el("tr", {}, ...[row.label, `${Number(row.avg_score).toFixed(1)} / ${row.total}`, row.avg_tool_calls, row.avg_tokens, row.errored_runs]
      .map((v) => el("td", { text: String(v) }))));
  }
  table.append(tbody);
  body.append(bars, el("div", { class: "cmp-wrap" }, table));
}

function renderCompare() {
  const [kind, id] = ($("cmp-select").value || "file:0").split(":");
  compareChoice = $("cmp-select").value;
  if (kind === "mine") {
    const results = sessionResults(id);
    const n = sessionRuns.filter((r) => r.key === id).length;
    drawCompare(results.rows, `${id}: your ${n} run(s) from this visit`, []);
    $("cmp-note").textContent = "These come from the runs you made on this page with your own key. They are kept only in this browser tab, so they disappear when you reload. A round you have not run shows as Not run yet.";
    return;
  }
  const file = compareFiles[Number(id)];
  if (!file) { drawCompare([], "", [["hint", "No saved comparison yet. Run: python -m praxis compare --provider gemini --runs 5"]]); $("cmp-note").textContent = ""; return; }
  const r = file.results;
  const label = r.demo ? `DEMO (scripted, not an AI): ${r.provider} / ${r.model}` : `${r.provider} / ${r.model}`;
  drawCompare(r.rows, `${label} · ${r.runs_per_setup ?? "?"} run(s) per setup`,
    r.demo ? [["notice demo", "These bars come from the scripted demo model. It is not an AI, so they are not results."]] : []);
  $("cmp-note").textContent = r.demo ? "Practice mode results: a pre-written script plays the AI, so these show how the scoring works, not how good a real AI is." : "Saved results from a real AI, measured with the command line.";
}

async function loadCompare() {
  const body = $("compare-body");
  try {
    if (!compareFiles) compareFiles = await getJSON("/api/compare");
    const select = $("cmp-select");
    clear(select);
    const mineKeys = [...new Set(sessionRuns.map((r) => r.key))];
    mineKeys.forEach((key) => select.append(el("option", { value: `mine:${key}`, text: `My AI: ${key} (this visit)` })));
    compareFiles.forEach((file, i) => {
      const r = file.results;
      select.append(el("option", { value: `file:${i}`, text: r.demo ? "Practice mode (scripted demo)" : `Saved: ${r.provider} / ${r.model}` }));
    });
    if (!select.options.length) select.append(el("option", { value: "file:none", text: "Practice mode (scripted demo)" }));
    const hasNewRuns = sessionRuns.length !== seenRuns;
    seenRuns = sessionRuns.length;
    if (mineKeys.length && (hasNewRuns || !compareChoice)) select.value = `mine:${sessionRuns[sessionRuns.length - 1].key}`;
    else if (compareChoice && [...select.options].some((o) => o.value === compareChoice)) select.value = compareChoice;
    $("cmp-pick").hidden = false;
    renderCompare();
  } catch (error) {
    clear(body);
    body.append(el("p", { class: "hint", text: error.message }));
  }
}

/* ---------- receipts tab ---------- */
let receiptsLoaded = false;
async function loadReceipts() {
  if (receiptsLoaded) return;
  const grid = $("receipt-grid");
  try {
    const items = await getJSON("/api/receipts");
    clear(grid);
    for (const item of items) {
      grid.append(el("div", { class: "paper" }, el("div", { class: "paper-name", text: item.name }), el("pre", { text: item.text })));
    }
    receiptsLoaded = true;
  } catch (error) {
    clear(grid);
    grid.append(el("p", { class: "hint", text: error.message }));
  }
}

/* ---------- tooltips and lever highlights ---------- */
let tipsGlobalBound = false;
function bindTips() {
  const wraps = [...document.querySelectorAll(".tip-wrap")];
  const closeAll = (except) => {
    for (const w of document.querySelectorAll(".tip-wrap")) if (w !== except) { w.classList.remove("open"); w.querySelector("button").setAttribute("aria-expanded", "false"); }
  };
  for (const w of wraps) {
    if (w.dataset.bound) continue;
    w.dataset.bound = "1";
    const btn = w.querySelector("button");
    btn.addEventListener("click", (event) => {
      event.stopPropagation();
      const open = !w.classList.contains("open");
      closeAll(w);
      w.classList.toggle("open", open);
      btn.setAttribute("aria-expanded", String(open));
    });
  }
  if (!tipsGlobalBound) {
    tipsGlobalBound = true;
    document.addEventListener("click", () => closeAll(null));
    document.addEventListener("keydown", (event) => { if (event.key === "Escape") closeAll(null); });
  }
}
function setupTips() { bindTips(); }

function setupLeverHighlights() {
  const mark = (ids, on) => {
    for (const li of document.querySelectorAll("#sb-grid li")) li.classList.toggle("target", on && ids.includes(li.dataset.id));
  };
  for (const lever of document.querySelectorAll(".lever")) {
    const ids = lever.dataset.targets.split(",");
    lever.addEventListener("mouseenter", () => mark(ids, true));
    lever.addEventListener("mouseleave", () => mark(ids, false));
    lever.addEventListener("focusin", () => mark(ids, true));
    lever.addEventListener("focusout", () => mark(ids, false));
  }
}

/* ---------- start ---------- */
async function init() {
  setupTabs();
  setupTips();
  try {
    [config, examples] = await Promise.all([getJSON("/api/config"), getJSON("/api/examples")]);
  } catch (error) {
    $("watch").hidden = false;
    showNotice("demo", "If you are running this locally, start it first (see the README).", "Could not reach the Praxis server");
    return;
  }
  $("goal").textContent = config.goal.replace(/\.$/, "");
  const select = $("provider");
  select.append(el("option", { value: "demo", text: "Practice mode" }));
  const SHORT = { gemini: "Gemini (free)", groq: "Groq (free)", openrouter: "OpenRouter (free)", anthropic: "Claude (paid)" };
  for (const p of config.providers) select.append(el("option", { value: p.id, text: SHORT[p.id] || p.label }));
  const hostProvider = config.providers.find((p) => p.server_key && config.runs_left > 0);
  select.value = hostProvider ? hostProvider.id : "demo";
  $("tx-context").value = config.levers.context;
  $("tx-instr").value = config.levers.instructions_clear;

  const pick = $("replay-pick");
  for (const ex of examples) {
    const name = ex.id.replace("example_demo_", "");
    const title = ROUNDS[name] ? ROUNDS[name].name : ex.label;
    pick.append(el("option", { value: ex.id, text: `${title}: scored ${ex.score} of ${ex.total}` }));
  }
  if (!examples.length) $("replay-row").hidden = true;

  select.addEventListener("change", onProviderChange);
  for (const id of ["api-key", "lv-context", "lv-tool", "lv-instr"]) $(id).addEventListener("input", refreshPanel);
  $("run").addEventListener("click", runLive);
  $("run-mix").addEventListener("click", runLive);
  $("cmp-select").addEventListener("change", renderCompare);
  $("replay").addEventListener("click", replay);
  drawScoreboard(null);
  setupLeverHighlights();
  onProviderChange();
  const vm = $("video-modal"), film = $("film");
  const closeVideo = () => { film.pause(); if (vm.open) vm.close(); };
  $("cta-video").addEventListener("click", () => { vm.showModal(); film.preload = "auto"; film.currentTime = 0; film.play().catch(() => {}); });
  $("video-close").addEventListener("click", closeVideo);
  vm.addEventListener("click", (e) => { if (e.target === vm) closeVideo(); });
  vm.addEventListener("close", () => film.pause());
  $("roadmap-link").addEventListener("click", (event) => {
    event.preventDefault();
    $("t-how").click();
    window.scrollTo({ top: 0, behavior: "smooth" });
  });
  $("cta-run").addEventListener("click", () => {
    $("cta-run").classList.add("used");
    if (!$("run").disabled) {
      applySetup(config.setups[0]);
      runLive();
    } else {
      $("setup").scrollIntoView({ behavior: "smooth" });
    }
  });
}

init();
