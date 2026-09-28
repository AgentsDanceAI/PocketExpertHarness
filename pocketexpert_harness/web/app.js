// PocketExpert Harness 网页端 —— 无构建、无依赖。事件协议见 README「事件流」一节。
"use strict";

const $ = (sel) => document.querySelector(sel);
const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
};

const state = { sid: null, running: false, info: null, token: "", pending: [] };
try { state.token = localStorage.getItem("peh_token") || ""; } catch (_) { /* 无痕模式 */ }

async function api(path, opts = {}) {
  const headers = Object.assign({ "Content-Type": "application/json" }, opts.headers || {});
  if (state.token) headers.Authorization = "Bearer " + state.token;
  const res = await fetch(path, Object.assign({}, opts, { headers }));
  if (res.status === 401) { askToken(); throw new Error("需要访问口令"); }
  return res;
}
const getJSON = async (p) => (await api(p)).json();

/** 工作区文件的地址 (img/a 标签带不了请求头, 口令走 ?token=) */
function fileUrl(path, download) {
  const enc = String(path).split("/").map(encodeURIComponent).join("/");
  const q = [];
  if (download) q.push("download=1");
  if (state.token) q.push("token=" + encodeURIComponent(state.token));
  return "/api/files/" + enc + (q.length ? "?" + q.join("&") : "");
}

const KIND_ICON = { image: "🖼", video: "🎬", audio: "🎵", table: "📊", doc: "📄", file: "📎" };
function kindOf(name) {
  const n = String(name).toLowerCase();
  if (/\.(png|jpe?g|gif|webp|bmp)$/.test(n)) return "image";
  if (/\.(mp4|mov|webm|m4v|avi|mkv)$/.test(n)) return "video";
  if (/\.(mp3|wav|m4a|aac|ogg|flac)$/.test(n)) return "audio";
  if (/\.(csv|tsv|xlsx?)$/.test(n)) return "table";
  if (/\.(pdf|docx?|pptx|txt|md|json|html)$/.test(n)) return "doc";
  return "file";
}
function humanSize(n) {
  if (!n) return "";
  const u = ["B", "KB", "MB", "GB"]; let i = 0;
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return (i ? n.toFixed(1) : n) + u[i];
}

// ── Markdown (先转义再排版, 不会注入 HTML) ─────────────────────────────
const esc = (s) => s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const unesc = (s) => s.replace(/&(amp|lt|gt|quot|#39);/g, (_m, e) => ({ amp: "&", lt: "<", gt: ">", quot: '"', "#39": "'" }[e]));
/** 链接目标: http(s) 原样; 工作区相对路径 → /api/files/…; 其余 (javascript: 之类) 一律不认 */
function resolveUrl(raw) {
  const u = unesc(raw).trim();
  if (/^https?:\/\//i.test(u)) return { href: u, local: false };
  if (u.startsWith("/api/files/")) return { href: u, local: true };
  if (/^[a-z][a-z0-9+.-]*:/i.test(u) || u.startsWith("//") || u.startsWith("/")) return null;
  const clean = u.replace(/^\.\//, "");
  if (!clean || clean.includes("..")) return null;
  return { href: fileUrl(clean), local: true, path: clean };
}
function inline(s) {
  return s.split(/(`[^`\n]+`)/g).map((p) => {
    if (p.length > 1 && p.startsWith("`") && p.endsWith("`")) return "<code>" + esc(p.slice(1, -1)) + "</code>";
    let t = esc(p);
    // 图片: 工作区里的图 (模型用 matplotlib 画的) 直接显示, 点开看原图
    t = t.replace(/!\[([^\]]*)\]\(([^)\s]+)\)/g, (m, alt, u) => {
      const r = resolveUrl(u);
      if (!r) return m;
      if (r.local && kindOf(r.path || u) === "video") return `<video class="md-video" src="${esc(r.href)}" controls preload="metadata"></video>`;
      return `<a href="${esc(r.href)}" target="_blank" rel="noopener"><img class="md-img" src="${esc(r.href)}" alt="${alt}" loading="lazy"></a>`;
    });
    t = t.replace(/(^|[^!])\[([^\]]+)\]\(([^)\s]+)\)/g, (m, pre, a, u) => {
      const r = resolveUrl(u);
      if (!r) return m;
      const cls = r.local ? ' class="file-link"' : "";
      return `${pre}<a${cls} href="${esc(r.href)}" target="_blank" rel="noopener noreferrer">${r.local ? (KIND_ICON[kindOf(r.path || u)] || "📎") + " " : ""}${a}</a>`;
    });
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
      i++; html += `<pre><button class="code-copy" type="button">复制</button><code>${esc(buf.join("\n"))}</code></pre>`; continue;
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

// ── 复制 ───────────────────────────────────────────────────────────────
async function copyText(text, btn) {
  try {
    await navigator.clipboard.writeText(text);
  } catch (_) {
    const ta = el("textarea"); ta.value = text; document.body.appendChild(ta); ta.select();
    try { document.execCommand("copy"); } catch (_e) { /* 放弃 */ }
    ta.remove();
  }
  if (btn) { const old = btn.textContent; btn.textContent = "已复制"; setTimeout(() => { btn.textContent = old; }, 1200); }
}
document.addEventListener("click", (e) => {
  const b = e.target.closest(".code-copy");
  if (b) copyText(b.parentElement.querySelector("code").textContent, b);
});

// ── 渲染 ───────────────────────────────────────────────────────────────
const thread = $("#thread");
const shortArgs = (a) => { const s = JSON.stringify(a || {}); return s === "{}" ? "" : (s.length > 140 ? s.slice(0, 139) + "…" : s); };
const scrollDown = () => { thread.scrollTop = thread.scrollHeight; };
const nearBottom = () => thread.scrollHeight - thread.scrollTop - thread.clientHeight < 120;
const secs = (ms) => Math.max(0, Math.round(ms / 1000));
const fmtTook = (s) => (s >= 60 ? `${Math.floor(s / 60)} 分 ${s % 60} 秒` : `${s} 秒`);

function attachmentNodes(list) {
  const box = el("div", "msg-atts");
  for (const a of list || []) {
    if (a.kind === "image") {
      const link = el("a"); link.href = fileUrl(a.path); link.target = "_blank"; link.rel = "noopener";
      const img = el("img", "att-thumb"); img.src = fileUrl(a.path); img.alt = a.name || a.path; img.loading = "lazy";
      link.appendChild(img); box.appendChild(link);
    } else {
      const chip = el("a", "att-chip"); chip.href = fileUrl(a.path); chip.target = "_blank"; chip.rel = "noopener";
      chip.append(`${KIND_ICON[a.kind] || "📎"} ${a.name || a.path}`);
      if (a.size) chip.appendChild(el("span", "att-size", humanSize(a.size)));
      box.appendChild(chip);
    }
  }
  return box;
}

function userBubble(text, atts) {
  const wrap = el("div", "msg-user");
  const col = el("div", "user-col");
  if (atts && atts.length) col.appendChild(attachmentNodes(atts));
  if (text) col.appendChild(el("div", "bubble", text));
  wrap.appendChild(col);
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
  const meta = el("div", "answer-meta");
  meta.hidden = true;
  wrap.append(trace, answer, meta);
  thread.appendChild(wrap);
  return { wrap, trace, sum, steps, answer, meta, list: [] };
}

const nSteps = (b) => b.list.filter((s) => s.tool !== "steer").length;
function setSummary(b, live, elapsed) {
  b.sum.textContent = "";
  if (live) b.sum.appendChild(el("span", "live-dot"));
  const n = nSteps(b);
  const t = elapsed != null ? ` · ${fmtTook(elapsed)}` : "";
  b.sum.appendChild(document.createTextNode(live ? (n ? `正在做第 ${n} 步${t}` : `正在思考${t}`) : `做了 ${n} 步${t}`));
}

/** 答案下面那一行: 用时 + 复制 */
function finishMeta(b, text, took) {
  b.meta.textContent = "";
  if (took != null && !nSteps(b)) b.meta.appendChild(el("span", "took", `用时 ${fmtTook(took)}`));
  if (text) {
    const c = el("button", "copy-btn", "复制"); c.type = "button";
    c.onclick = () => copyText(text, c);
    b.meta.appendChild(c);
  }
  b.meta.hidden = !b.meta.childNodes.length;
}

function renderRecord(rec) {
  const b = aiBlock();
  b.list = rec.steps || [];
  const took = rec.took != null ? Math.round(rec.took) : null;
  if (b.list.length) {
    b.trace.hidden = false;
    b.list.forEach((s) => b.steps.appendChild(stepNode(s)));
    setSummary(b, false, took);
  }
  b.answer.hidden = false;
  b.answer.innerHTML = md(rec.text || (rec.kind === "aborted" ? "" : "(没有回答)"));
  if (rec.kind === "aborted") { b.answer.classList.add("aborted"); b.answer.appendChild(el("div", "note", "这一轮被停止了")); }
  finishMeta(b, rec.text, took);
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
  for (const item of s.transcript) item.role === "user" ? userBubble(item.text, item.attachments) : renderRecord(item);
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

// ── 附件 (点选 / 粘贴 / 拖进来) ────────────────────────────────────────
let attSeq = 0;
function renderTray() {
  const tray = $("#tray");
  tray.textContent = "";
  tray.hidden = !state.pending.length;
  for (const p of state.pending) {
    const item = el("div", "tray-item" + (p.status === "error" ? " err" : ""));
    if (p.kind === "image" && p.preview) {
      const img = el("img", "tray-thumb"); img.src = p.preview; img.alt = p.name; item.appendChild(img);
    } else {
      item.appendChild(el("span", "tray-icon", KIND_ICON[p.kind] || "📎"));
    }
    const label = el("div", "tray-label");
    label.appendChild(el("span", "tray-name", p.name));
    label.appendChild(el("span", "tray-sub", p.status === "uploading" ? "上传中…" : p.status === "error" ? (p.error || "上传失败") : humanSize(p.size)));
    item.appendChild(label);
    const x = el("button", "tray-x", "✕"); x.type = "button"; x.setAttribute("aria-label", "移除");
    x.onclick = () => { state.pending = state.pending.filter((q) => q.id !== p.id); if (p.preview) URL.revokeObjectURL(p.preview); renderTray(); };
    item.appendChild(x);
    tray.appendChild(item);
  }
  const imgs = state.pending.some((p) => p.kind === "image");
  const hint = $("#visionHint");
  hint.hidden = !(imgs && state.info && !state.info.vision);
  updateSend();
}

async function addFiles(fileList) {
  const max = ((state.info && state.info.max_upload_mb) || 50) * 1024 * 1024;
  for (const f of [...fileList]) {
    if (state.pending.length >= 10) break;
    const name = f.name && f.name !== "image.png" ? f.name : `粘贴的图片-${Date.now()}.png`;
    const p = { id: ++attSeq, name, size: f.size, kind: kindOf(name), status: "uploading" };
    if (p.kind === "image") p.preview = URL.createObjectURL(f);
    state.pending.push(p);
    renderTray();
    if (f.size > max) { p.status = "error"; p.error = `超过 ${max / 1024 / 1024}MB`; renderTray(); continue; }
    try {
      const headers = { "Content-Type": f.type || "application/octet-stream" };
      if (state.token) headers.Authorization = "Bearer " + state.token;
      const res = await fetch("/api/uploads?name=" + encodeURIComponent(name), { method: "POST", body: f, headers });
      if (res.status === 401) { askToken(); throw new Error("需要访问口令"); }
      const info = await res.json();
      if (!res.ok) throw new Error(info.error || res.statusText);
      Object.assign(p, { status: "done", path: info.path, kind: info.kind, size: info.size });
    } catch (e) {
      p.status = "error"; p.error = String(e.message || e);
    }
    renderTray();
  }
}

function updateSend() {
  const uploading = state.pending.some((p) => p.status === "uploading");
  $("#send").disabled = uploading;
  $("#attach").disabled = state.running;
}

// ── 发送与事件流 ───────────────────────────────────────────────────────
function setRunning(on) {
  state.running = on;
  $("#stop").hidden = !on;
  $("#send").textContent = on ? "补充" : "发送";
  $("#input").placeholder = on ? "补充或纠正" : "输入问题, 也可以把图片或文件拖进来";
  updateSend();
}

async function send(text) {
  if (state.running) {
    if (text) await api(`/api/sessions/${state.sid}/steer`, { method: "POST", body: JSON.stringify({ text }) });
    return;
  }
  const atts = state.pending.filter((p) => p.status === "done").map((p) => ({ path: p.path, name: p.name, kind: p.kind, size: p.size }));
  if (!text && !atts.length) return;
  state.pending.forEach((p) => p.preview && URL.revokeObjectURL(p.preview));
  state.pending = []; renderTray();
  if (!state.sid) {
    const s = await (await api("/api/sessions", { method: "POST", body: "{}" })).json();
    state.sid = s.id;
    try { history.replaceState(null, "", "#" + s.id); } catch (_) { /* file:// */ }
  }
  showEmpty(false);
  userBubble(text, atts);
  const b = aiBlock();
  let draft = "", draftEl = null;
  const t0 = Date.now();
  // 一发出去就有反馈: 模型第一次回话前 (或它直接调工具、一个字都没吐) 也在读秒
  b.trace.hidden = false; b.trace.open = true; setSummary(b, true, 0);
  const ticker = setInterval(() => setSummary(b, true, secs(Date.now() - t0)), 1000);
  const ensureDraft = () => {
    if (!draftEl) { draftEl = el("div", "answer md draft cursor"); b.wrap.insertBefore(draftEl, b.answer); }
    return draftEl;
  };
  const dropDraft = () => { if (draftEl) { draftEl.remove(); draftEl = null; } draft = ""; };
  setRunning(true);
  scrollDown();
  if ($("#title").textContent === "新对话") $("#title").textContent = (text || (atts[0] && atts[0].name) || "新对话").split("\n")[0].slice(0, 40);

  const finish = () => {
    clearInterval(ticker);
    const took = secs(Date.now() - t0);
    if (nSteps(b)) { setSummary(b, false, took); b.trace.open = false; } else { b.trace.hidden = true; }
    return took;
  };
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
        setSummary(b, true, secs(Date.now() - t0));
        break;
      }
      case "observation": {
        const st = [...b.list].reverse().find((s) => s.n === ev.n);
        if (st) { st.ok = ev.ok; st.summary = ev.summary || ""; const fresh = stepNode(st); st.node.replaceWith(fresh); st.node = fresh; }
        break;
      }
      case "steer": {
        const st = { n: ev.n, tool: "steer", thought: ev.text }; b.list.push(st);
        b.steps.appendChild(stepNode(st));
        break;
      }
      case "notice":
        if (ev.kind === "wrap_up") dropDraft();
        break;
      case "done": {
        const answer = ev.answer || draft;
        dropDraft();
        const took = finish();
        b.answer.hidden = false;
        b.answer.innerHTML = md(answer || "(没有回答)");
        if (ev.kind === "aborted") { b.answer.classList.add("aborted"); b.answer.appendChild(el("div", "note", "这一轮被停止了")); }
        finishMeta(b, answer, took);
        break;
      }
      case "error":
        dropDraft();
        finish();
        b.answer.hidden = false;
        b.answer.innerHTML = md("出错了: " + (ev.message || "未知错误"));
        break;
    }
    if (stick) scrollDown();
  };

  try {
    const res = await api(`/api/sessions/${state.sid}/messages`, { method: "POST", body: JSON.stringify({ text, attachments: atts }) });
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
    clearInterval(ticker);
    setRunning(false);
    loadSessions();
  }
}

// ── 记忆 / 信息 / 工作区文件 / 口令 ───────────────────────────────────
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

async function openFiles() {
  const list = await getJSON("/api/files");
  const ul = $("#fileList"); ul.textContent = "";
  if (!list.length) ul.appendChild(el("li", "none", "工作区还是空的。上传文件, 或者让它写报告、画图, 产物都会出现在这里。"));
  for (const f of list) {
    const li = el("li", "file-row");
    if (f.kind === "image") {
      const img = el("img", "file-thumb"); img.src = fileUrl(f.path); img.alt = f.name; img.loading = "lazy"; li.appendChild(img);
    } else {
      li.appendChild(el("span", "file-icon", KIND_ICON[f.kind] || "📎"));
    }
    const info = el("div", "file-info");
    const open = el("a", "file-name", f.path); open.href = fileUrl(f.path); open.target = "_blank"; open.rel = "noopener";
    info.appendChild(open);
    info.appendChild(el("span", "file-sub", `${humanSize(f.size)} · ${new Date(f.mtime * 1000).toLocaleString()}`));
    li.appendChild(info);
    const dl = el("a", "file-dl", "下载"); dl.href = fileUrl(f.path, true);
    li.appendChild(dl);
    ul.appendChild(li);
  }
  $("#filesPanel").showModal();
}

function openInfo() {
  const i = state.info; if (!i) return;
  const body = $("#infoBody"); body.textContent = "";
  const sec = (title) => { const s = el("div", "info-sec"); s.appendChild(el("h3", null, title)); body.appendChild(s); return s; };
  const kv = el("dl", "kv");
  [["模型", `${i.provider} / ${i.model}`], ["看图", i.vision ? "支持" : "不支持 (图片按文件处理; 换 qwen-vl-max 等看图模型, 或设 PEH_VISION=on)"],
    ["联网搜索", i.web_search || "未配置"], ["代码执行", { on: "开启", ask: "每次询问", off: "关闭" }[i.python] || i.python],
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
input.addEventListener("paste", (e) => {
  const files = e.clipboardData && e.clipboardData.files;
  if (files && files.length && !state.running) { e.preventDefault(); addFiles(files); }
});
$("#composer").addEventListener("submit", (e) => {
  e.preventDefault();
  if ($("#send").disabled) return;
  const text = input.value.trim();
  if (!text && !state.pending.some((p) => p.status === "done")) return;
  input.value = ""; autosize();
  send(text);
});
$("#attach").onclick = () => $("#fileInput").click();
$("#fileInput").addEventListener("change", (e) => { addFiles(e.target.files); e.target.value = ""; });
// 拖进来: 整个窗口都能放
let dragDepth = 0;
window.addEventListener("dragenter", (e) => { if (e.dataTransfer && [...e.dataTransfer.types].includes("Files")) { dragDepth++; $("#dropMask").hidden = false; } });
window.addEventListener("dragleave", () => { dragDepth = Math.max(0, dragDepth - 1); if (!dragDepth) $("#dropMask").hidden = true; });
window.addEventListener("dragover", (e) => e.preventDefault());
window.addEventListener("drop", (e) => {
  e.preventDefault(); dragDepth = 0; $("#dropMask").hidden = true;
  if (!state.running && e.dataTransfer && e.dataTransfer.files.length) addFiles(e.dataTransfer.files);
});
$("#stop").onclick = () => state.sid && api(`/api/sessions/${state.sid}/stop`, { method: "POST" });
$("#newChat").onclick = newChat;
$("#openMemory").onclick = openMemory;
$("#openFiles").onclick = openFiles;
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
