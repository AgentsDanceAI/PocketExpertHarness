// PocketExpert Harness 网页端 —— 无构建、无依赖。事件协议见 README「事件流」一节。
"use strict";

const $ = (sel) => document.querySelector(sel);
const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
};

const state = { sid: null, running: false, info: null, token: "" };
try { state.token = localStorage.getItem("peh_token") || ""; } catch (_) { /* 无痕模式 */ }

async function api(path, opts = {}) {
  const headers = Object.assign({ "Content-Type": "application/json" }, opts.headers || {});
  if (state.token) headers.Authorization = "Bearer " + state.token;
  const res = await fetch(path, Object.assign({}, opts, { headers }));
  if (res.status === 401) { askToken(); throw new Error("需要访问口令"); }
  return res;
}
const getJSON = async (p) => (await api(p)).json();

// ── Markdown (先转义再排版, 不会注入 HTML) ─────────────────────────────
const esc = (s) => s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
function inline(s) {
  return s.split(/(`[^`\n]+`)/g).map((p) => {
    if (p.length > 1 && p.startsWith("`") && p.endsWith("`")) return "<code>" + esc(p.slice(1, -1)) + "</code>";
    let t = esc(p);
    t = t.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, (_m, a, u) => `<a href="${u}" target="_blank" rel="noopener noreferrer">${a}</a>`);
    t = t.replace(/(^|[\s(（:：])(https?:\/\/[^\s<)）\]]+)/g, (_m, pre, u) => `${pre}<a href="${u}" target="_blank" rel="noopener noreferrer">${u}</a>`);
    t = t.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>").replace(/(^|[^*\w])\*([^*\s][^*]*?)\*(?!\w)/g, "$1<em>$2</em>");
    return t;
  }).join("");
}
const cells = (row) => row.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
function md(src) {
  const lines = String(src || "").replace(/\r\n?/g, "\n").split("\n");
  const isBlockStart = (l) => /^```|^#{1,6}\s|^>\s?|^\s*([-*+]|\d+[.)])\s+|^\|.*\|\s*$/.test(l);
  let html = "", i = 0;
  while (i < lines.length) {
    const l = lines[i];
    let m;
    if (/^```/.test(l)) {
      const buf = []; i++;
      while (i < lines.length && !/^```/.test(lines[i])) buf.push(lines[i++]);
      i++; html += `<pre><code>${esc(buf.join("\n"))}</code></pre>`; continue;
    }
    if (/^\s*$/.test(l)) { i++; continue; }
    if ((m = l.match(/^(#{1,6})\s+(.*)$/))) { const n = Math.min(m[1].length, 4); html += `<h${n}>${inline(m[2])}</h${n}>`; i++; continue; }
    if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(l)) { html += "<hr>"; i++; continue; }
    if (/^\|.*\|\s*$/.test(l) && i + 1 < lines.length && /^\|?\s*:?-{2,}/.test(lines[i + 1])) {
      const head = cells(l); i += 2; const rows = [];
      while (i < lines.length && /^\|.*\|\s*$/.test(lines[i])) rows.push(cells(lines[i++]));
      html += '<div class="tbl"><table><thead><tr>' + head.map((c) => `<th>${inline(c)}</th>`).join("") + "</tr></thead><tbody>" +
        rows.map((r) => "<tr>" + r.map((c) => `<td>${inline(c)}</td>`).join("") + "</tr>").join("") + "</tbody></table></div>";
      continue;
    }
    if (/^>\s?/.test(l)) {
      const buf = [];
      while (i < lines.length && /^>\s?/.test(lines[i])) buf.push(lines[i++].replace(/^>\s?/, ""));
      html += `<blockquote>${md(buf.join("\n"))}</blockquote>`; continue;
    }
    if ((m = l.match(/^\s*([-*+]|\d+[.)])\s+/))) {
      const ordered = /\d/.test(m[1]); const items = [];
      while (i < lines.length) {
        const mm = lines[i].match(/^\s*([-*+]|\d+[.)])\s+(.*)$/);
        if (mm) { items.push(mm[2]); i++; continue; }
        if (/^\s{2,}\S/.test(lines[i]) && items.length) { items[items.length - 1] += "<br>" + lines[i].trim(); i++; continue; }
        break;
      }
      const tag = ordered ? "ol" : "ul";
      html += `<${tag}>` + items.map((t) => `<li>${t.includes("<br>") ? t.split("<br>").map(inline).join("<br>") : inline(t)}</li>`).join("") + `</${tag}>`;
      continue;
    }
    const buf = [];
    while (i < lines.length && !/^\s*$/.test(lines[i]) && !isBlockStart(lines[i])) buf.push(lines[i++]);
    if (!buf.length) { buf.push(lines[i++]); }
    html += `<p>${buf.map(inline).join("<br>")}</p>`;
  }
  return html;
}

// ── 渲染 ───────────────────────────────────────────────────────────────
const thread = $("#thread");
const shortArgs = (a) => { const s = JSON.stringify(a || {}); return s === "{}" ? "" : (s.length > 140 ? s.slice(0, 139) + "…" : s); };
const scrollDown = () => { thread.scrollTop = thread.scrollHeight; };
const nearBottom = () => thread.scrollHeight - thread.scrollTop - thread.clientHeight < 120;

function userBubble(text) {
  const wrap = el("div", "msg-user");
  wrap.appendChild(el("div", "bubble", text));
  thread.appendChild(wrap);
}

function stepNode(st) {
  const li = el("li", "step" + (st.tool === "steer" ? " steer" : st.ok === true ? " ok" : st.ok === false ? " bad" : ""));
  li.appendChild(el("span", "mark", st.tool === "steer" ? "↳" : st.ok === true ? "✓" : st.ok === false ? "!" : "·"));
  const body = el("div");
  if (st.tool === "steer") {
    body.appendChild(el("div", "thought", "你补充: " + (st.thought || "")));
  } else {
    if (st.thought) body.appendChild(el("div", "thought", st.thought));
    const line = el("div");
    line.appendChild(el("span", "tool", st.tool));
    const a = shortArgs(st.args);
    if (a) { line.appendChild(document.createTextNode(" ")); line.appendChild(el("span", "args", a)); }
    body.appendChild(line);
    if (st.summary) body.appendChild(el("div", "obs", st.summary));
  }
  li.appendChild(body);
  return li;
}

function aiBlock() {
  const wrap = el("div", "msg-ai");
  const trace = el("details", "trace");
  const sum = el("summary");
  const steps = el("ol", "steps");
  trace.append(sum, steps);
  trace.hidden = true;
  const answer = el("div", "answer md");
  answer.hidden = true;
  wrap.append(trace, answer);
  thread.appendChild(wrap);
  return { wrap, trace, sum, steps, answer, list: [] };
}

function setSummary(b, live) {
  b.sum.textContent = "";
  if (live) b.sum.appendChild(el("span", "live-dot"));
  const n = b.list.filter((s) => s.tool !== "steer").length;
  b.sum.appendChild(document.createTextNode(live ? `正在做第 ${n} 步…` : `做了 ${n} 步`));
}

function renderRecord(rec) {
  const b = aiBlock();
  b.list = rec.steps || [];
  if (b.list.length) {
    b.trace.hidden = false;
    b.list.forEach((s) => b.steps.appendChild(stepNode(s)));
    setSummary(b, false);
  }
  b.answer.hidden = false;
  b.answer.innerHTML = md(rec.text || (rec.kind === "aborted" ? "" : "(没有回答)"));
  if (rec.kind === "aborted") { b.answer.classList.add("aborted"); b.answer.appendChild(el("div", "note", "这一轮被停止了")); }
}

function showEmpty(show) { $("#empty").hidden = !show; }

// ── 会话 ───────────────────────────────────────────────────────────────
async function loadSessions() {
  const list = await getJSON("/api/sessions");
  const nav = $("#sessions");
  nav.textContent = "";
  for (const s of list) {
    const a = el("a", "sess" + (s.id === state.sid ? " active" : ""));
    a.href = "#" + s.id;
    a.appendChild(el("span", null, s.title || "新对话"));
    const del = el("button", "del", "✕");
    del.type = "button"; del.title = "删除"; del.setAttribute("aria-label", "删除会话");
    del.onclick = async (e) => {
      e.preventDefault(); e.stopPropagation();
      await api(`/api/sessions/${s.id}`, { method: "DELETE" });
      if (s.id === state.sid) newChat(); else loadSessions();
    };
    a.appendChild(del);
    a.onclick = (e) => { e.preventDefault(); openSession(s.id); $("#app").classList.remove("side-open"); };
    nav.appendChild(a);
  }
  return list;
}

async function openSession(sid) {
  if (state.running) return;
  const res = await api(`/api/sessions/${sid}`);
  if (!res.ok) return newChat();
  const s = await res.json();
  state.sid = sid;
  try { history.replaceState(null, "", "#" + sid); } catch (_) { /* file:// */ }
  $("#title").textContent = s.title || "新对话";
  [...thread.querySelectorAll(".msg-user, .msg-ai")].forEach((n) => n.remove());
  showEmpty(!s.transcript.length);
  for (const item of s.transcript) item.role === "user" ? userBubble(item.text) : renderRecord(item);
  // 打开会话时停在最近一问的开头 (长回答从头往下读), 最近一轮不满一屏就直接到底
  const users = thread.querySelectorAll(".msg-user");
  const last = users[users.length - 1];
  if (last && thread.scrollHeight - last.offsetTop > thread.clientHeight) thread.scrollTop = last.offsetTop - 16;
  else scrollDown();
  loadSessions();
}

function newChat() {
  if (state.running) return;
  state.sid = null;
  try { history.replaceState(null, "", location.pathname); } catch (_) { /* file:// */ }
  $("#title").textContent = "新对话";
  [...thread.querySelectorAll(".msg-user, .msg-ai")].forEach((n) => n.remove());
  showEmpty(true);
  loadSessions();
  $("#input").focus();
}

// ── 发送与事件流 ───────────────────────────────────────────────────────
function setRunning(on) {
  state.running = on;
  $("#stop").hidden = !on;
  $("#send").textContent = on ? "补充" : "发送";
  $("#input").placeholder = on ? "补充或纠正" : "输入问题";
}

async function send(text) {
  if (state.running) {
    await api(`/api/sessions/${state.sid}/steer`, { method: "POST", body: JSON.stringify({ text }) });
    return;
  }
  if (!state.sid) {
    const s = await (await api("/api/sessions", { method: "POST", body: "{}" })).json();
    state.sid = s.id;
    try { history.replaceState(null, "", "#" + s.id); } catch (_) { /* file:// */ }
  }
  showEmpty(false);
  userBubble(text);
  const b = aiBlock();
  let draft = "", draftEl = null;
  const ensureDraft = () => {
    if (!draftEl) { draftEl = el("div", "answer md draft cursor"); b.wrap.insertBefore(draftEl, b.answer); }
    return draftEl;
  };
  const dropDraft = () => { if (draftEl) { draftEl.remove(); draftEl = null; } draft = ""; };
  setRunning(true);
  scrollDown();
  if ($("#title").textContent === "新对话") $("#title").textContent = text.split("\n")[0].slice(0, 40);

  const handle = (ev) => {
    const stick = nearBottom();
    switch (ev.event) {
      case "assistant_delta":
        draft += ev.text || "";
        ensureDraft().innerHTML = md(draft);
        break;
      case "step": {
        const st = { n: ev.n, tool: ev.tool, args: ev.args, thought: (ev.thought || draft).trim(), ok: null, summary: "" };
        dropDraft();
        b.list.push(st); st.node = stepNode(st); b.steps.appendChild(st.node);
        b.trace.hidden = false; b.trace.open = true; setSummary(b, true);
        break;
      }
      case "observation": {
        const st = [...b.list].reverse().find((s) => s.n === ev.n);
        if (st) { st.ok = ev.ok; st.summary = ev.summary || ""; const fresh = stepNode(st); st.node.replaceWith(fresh); st.node = fresh; }
        break;
      }
      case "steer": {
        const st = { n: ev.n, tool: "steer", thought: ev.text }; b.list.push(st);
        b.steps.appendChild(stepNode(st)); b.trace.hidden = false; b.trace.open = true;
        break;
      }
      case "notice":
        if (ev.kind === "wrap_up") dropDraft();
        break;
      case "done": {
        const answer = ev.answer || draft;
        dropDraft();
        b.answer.hidden = false;
        b.answer.innerHTML = md(answer || "(没有回答)");
        if (ev.kind === "aborted") { b.answer.classList.add("aborted"); b.answer.appendChild(el("div", "note", "这一轮被停止了")); }
        if (b.list.length) { setSummary(b, false); b.trace.open = false; }
        break;
      }
      case "error":
        dropDraft();
        b.answer.hidden = false;
        b.answer.innerHTML = md("出错了: " + (ev.message || "未知错误"));
        break;
    }
    if (stick) scrollDown();
  };

  try {
    const res = await api(`/api/sessions/${state.sid}/messages`, { method: "POST", body: JSON.stringify({ text }) });
    if (!res.ok) { const e = await res.json().catch(() => ({})); handle({ event: "error", message: e.error || res.statusText }); return; }
    const reader = res.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let cut;
      while ((cut = buf.indexOf("\n\n")) >= 0) {
        const frame = buf.slice(0, cut); buf = buf.slice(cut + 2);
        const data = frame.split("\n").filter((l) => l.startsWith("data:")).map((l) => l.slice(5).trimStart()).join("\n");
        if (data) { try { handle(JSON.parse(data)); } catch (_) { /* 坏帧跳过 */ } }
      }
    }
  } catch (e) {
    handle({ event: "error", message: String(e.message || e) });
  } finally {
    setRunning(false);
    loadSessions();
  }
}

// ── 记忆 / 信息 / 口令 ─────────────────────────────────────────────────
async function openMemory() {
  const m = await getJSON("/api/memory");
  $("#soul").value = m.soul || "";
  const ul = $("#memItems"); ul.textContent = "";
  if (!m.items.length) ul.appendChild(el("li", "none", "还没有。对它说「记住: …」试试。"));
  for (const it of [...m.items].reverse()) {
    const li = el("li"); li.appendChild(el("span", null, it.text));
    const del = el("button", "icon-btn", "✕"); del.type = "button"; del.setAttribute("aria-label", "删除");
    del.onclick = async () => { await api(`/api/memory/items/${it.id}`, { method: "DELETE" }); li.remove(); };
    li.appendChild(del); ul.appendChild(li);
  }
  $("#soulSaved").hidden = true;
  $("#memoryPanel").showModal();
}

function openInfo() {
  const i = state.info; if (!i) return;
  const body = $("#infoBody"); body.textContent = "";
  const sec = (title) => { const s = el("div", "info-sec"); s.appendChild(el("h3", null, title)); body.appendChild(s); return s; };
  const kv = el("dl", "kv");
  [["模型", `${i.provider} / ${i.model}`], ["联网搜索", i.web_search || "未配置"], ["代码执行", { on: "开启", ask: "每次询问", off: "关闭" }[i.python] || i.python],
    ["工作区", i.workspace], ["版本", i.version]].forEach(([k, v]) => { kv.appendChild(el("dt", null, k)); kv.appendChild(el("dd", null, v)); });
  sec("运行配置").appendChild(kv);
  const tg = el("div", "info-grid"); i.tools.forEach((t) => tg.appendChild(el("code", null, t))); sec(`工具 (${i.tools.length})`).appendChild(tg);
  const ss = sec(`技能 (${i.skills.length})`);
  if (!i.skills.length) ss.appendChild(el("p", "panel-note", "把含 SKILL.md 的目录放进 ./skills 就能用。"));
  i.skills.forEach((s) => { const p = el("p"); p.appendChild(el("strong", null, s.name)); p.appendChild(document.createTextNode(" — " + s.description)); ss.appendChild(p); });
  const ms = sec(`MCP 服务 (${i.mcp.length})`);
  if (!i.mcp.length) ms.appendChild(el("p", "panel-note", "在 mcp.json 里配置 (格式与 Claude Desktop 相同)。"));
  i.mcp.forEach((m) => ms.appendChild(el("p", m.status === "failed" ? "status-bad" : null,
    m.status === "failed" ? `${m.name}: 没连上 — ${m.error}` : `${m.name}: ${m.tools} 个工具`)));
  $("#infoPanel").showModal();
}

function askToken() {
  const d = $("#tokenPanel");
  if (!d.open) d.showModal();
}

async function loadInfo() {
  state.info = await getJSON("/api/info");
  const c = $("#chips"); c.textContent = "";
  const chip = (label, val) => { const s = el("span", "chip"); s.append(label + " "); s.appendChild(el("b", null, val)); c.appendChild(s); };
  chip("模型", state.info.model);
  chip("工具", String(state.info.tools.length));
  if (state.info.skills.length) chip("技能", String(state.info.skills.length));
  if (state.info.mcp.length) chip("MCP", String(state.info.mcp.filter((m) => m.status === "ready").length));
}

// ── 绑定 ───────────────────────────────────────────────────────────────
const input = $("#input");
const autosize = () => { input.style.height = "auto"; input.style.height = Math.min(input.scrollHeight, window.innerHeight * 0.4) + "px"; };
input.addEventListener("input", autosize);
input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); $("#composer").requestSubmit(); }
});
$("#composer").addEventListener("submit", (e) => {
  e.preventDefault();
  const text = input.value.trim();
  if (!text) return;
  input.value = ""; autosize();
  send(text);
});
$("#stop").onclick = () => state.sid && api(`/api/sessions/${state.sid}/stop`, { method: "POST" });
$("#newChat").onclick = newChat;
$("#openMemory").onclick = openMemory;
$("#openInfo").onclick = openInfo;
$("#toggleSide").onclick = () => $("#app").classList.toggle("side-open");
$("#saveSoul").onclick = async () => {
  await api("/api/memory/soul", { method: "PUT", body: JSON.stringify({ text: $("#soul").value }) });
  $("#soulSaved").hidden = false;
};
$("#starters").addEventListener("click", (e) => { if (e.target.tagName === "BUTTON") send(e.target.textContent); });
$("#tokenForm").addEventListener("submit", (e) => {
  e.preventDefault();
  state.token = $("#tokenInput").value.trim();
  try { localStorage.setItem("peh_token", state.token); } catch (_) { /* 无痕模式 */ }
  $("#tokenPanel").close();
  boot();
});

async function boot() {
  const a = await (await fetch("/api/auth")).json();
  if (a.token_required && !state.token) { askToken(); return; }
  try {
    await loadInfo();
    const list = await loadSessions();
    const want = location.hash.slice(1);
    if (want && list.some((s) => s.id === want)) openSession(want); else showEmpty(true);
  } catch (e) { /* 口令错了会弹口令框 */ }
}
boot();
