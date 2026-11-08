"use strict";
/* ------------------------------------------------------------------
 * Part 1: pure terminal-stream parser (no DOM) — unit-tested with node.
 * Turns raw program output into abstract operations:
 *   {k:"text", s, fg, bg, bold} | {k:"nl"} | {k:"cr"} | {k:"bs"} | {k:"clear"}
 * ------------------------------------------------------------------ */
function newParseState() {
  return { pending: "", fg: null, bg: null, bold: false };
}

function xterm256(n) {
  if (n < 16) return n;
  if (n >= 232) { const v = 8 + (n - 232) * 10; return "rgb(" + v + "," + v + "," + v + ")"; }
  n -= 16;
  const f = (x) => (x === 0 ? 0 : 55 + x * 40);
  return "rgb(" + f(Math.floor(n / 36)) + "," + f(Math.floor(n / 6) % 6) + "," + f(n % 6) + ")";
}

function applyCSI(st, params, final, ops) {
  if (final === "m") {
    const p = params === "" ? [0] : params.split(";").map((x) => (x === "" ? 0 : parseInt(x, 10)));
    for (let i = 0; i < p.length; i++) {
      const c = p[i];
      if (c === 0) { st.fg = null; st.bg = null; st.bold = false; }
      else if (c === 1) st.bold = true;
      else if (c === 22) st.bold = false;
      else if (c >= 30 && c <= 37) st.fg = c - 30;
      else if (c >= 90 && c <= 97) st.fg = c - 90 + 8;
      else if (c === 39) st.fg = null;
      else if (c >= 40 && c <= 47) st.bg = c - 40;
      else if (c >= 100 && c <= 107) st.bg = c - 100 + 8;
      else if (c === 49) st.bg = null;
      else if (c === 38 || c === 48) {
        const key = c === 38 ? "fg" : "bg";
        if (p[i + 1] === 5 && Number.isInteger(p[i + 2])) { st[key] = xterm256(p[i + 2]); i += 2; }
        else if (p[i + 1] === 2 && [2, 3, 4].every((d) => Number.isInteger(p[i + d]))) {
          st[key] = "rgb(" + p[i + 2] + "," + p[i + 3] + "," + p[i + 4] + ")"; i += 4;
        }
      }
    }
  } else if (final === "J") {
    if (params === "2" || params === "3") ops.push({ k: "clear" });
  } else if (final === "K") {
    if (params === "2") ops.push({ k: "cr" });
  }
}

const CSI = /^\x1b\[([0-9;?]*)([ -\/]*[@-~])/;
const OSC = /^\x1b\][^\x07\x1b]*(\x07|\x1b\\)/;
const PARTIAL = /^\x1b(\[[0-9;?]*[ -\/]*|\][^\x07\x1b]*\x1b?)?$/;

function parse(st, chunk) {
  const s = st.pending + chunk;
  st.pending = "";
  const ops = [];
  let text = "";
  const flush = () => {
    if (text) { ops.push({ k: "text", s: text, fg: st.fg, bg: st.bg, bold: st.bold }); text = ""; }
  };
  for (let i = 0; i < s.length; i++) {
    const ch = s[i];
    if (ch === "\x1b") {
      const rest = s.slice(i);
      let m = CSI.exec(rest);
      if (m) { flush(); applyCSI(st, m[1], m[2].slice(-1), ops); i += m[0].length - 1; continue; }
      m = OSC.exec(rest);
      if (m) { i += m[0].length - 1; continue; }
      if (PARTIAL.test(rest)) { st.pending = rest; break; }
      continue; // lone ESC: drop it
    }
    if (ch === "\r") {
      flush();
      if (i + 1 >= s.length) { st.pending = "\r"; break; }
      if (s[i + 1] === "\n") continue;
      ops.push({ k: "cr" });
      continue;
    }
    if (ch === "\n") { flush(); ops.push({ k: "nl" }); continue; }
    if (ch === "\b") { flush(); ops.push({ k: "bs" }); continue; }
    if (ch === "\t" || ch >= " ") { if (ch !== "\x7f") text += ch; continue; }
    // other control characters (BEL etc.) are ignored
  }
  flush();
  return ops;
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = { newParseState, parse, xterm256 };
}

/* ------------------------------------------------------------------
 * Part 2: the browser UI.
 *  modes   : "shell" (typing commands) | "program" (typing into stdin) | "busy" | "idle"
 *  display : normal console, or "result mode" (only the program's output, very large)
 * ------------------------------------------------------------------ */
if (typeof document !== "undefined") (function () {
  const $ = (id) => document.getElementById(id);
  const qs = new URLSearchParams(location.search);
  const token = qs.get("t") || "";
  const screen = $("screen"), live = $("live"), promptEl = $("prompt"), input = $("in");
  const FA = "۰۱۲۳۴۵۶۷۸۹";
  const MAX_LINES = 5000, MAX_UPLOAD = 1000000;
  const RTL = /[\u0590-\u08FF\uFB1D-\uFDFF\uFE70-\uFEFF]/, LTR = /[A-Za-z]/;

  const S = { font: 17, theme: "auto", normalize: true, faDigits: false, resultMode: false, resultFont: 52 };
  if (qs.get("m") === "result") S.resultMode = true;          // launched from the "show result" menu entry
  const states = { out: newParseState(), err: newParseState() };
  let run = 0, mode = "idle", title = "", cwdName = "", hist = [], hpos = 0;
  let watchOn = false, winAvail = false, version = "", lineLtr = false, lineMeta = false, toastTimer = null;

  const setClass = (el, name, on) => {
    const rest = el.className.split(/\s+/).filter((c) => c && c !== name);
    el.className = (on ? rest.concat(name) : rest).join(" ");
  };
  const press = (el, on) => { setClass(el, "on", on); el.setAttribute("aria-pressed", String(!!on)); };
  const show = (el, on) => { el.hidden = !on; };

  function toast(text) {
    const t = $("toast");
    t.textContent = text; show(t, true);
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(() => show(t, false), 3500);
  }

  /* ---------- settings (kept on the server: the port, hence the origin, changes every launch) */
  function applySettings() {
    const root = document.documentElement;
    root.style.setProperty("--fs", S.font + "px");
    root.style.setProperty("--rfs", S.resultFont + "px");
    if (S.theme === "auto") root.removeAttribute("data-theme"); else root.setAttribute("data-theme", S.theme);
    setClass(document.body, "result", S.resultMode);
    $("optNorm").checked = S.normalize;
    $("optFa").checked = S.faDigits;
    $("btnTheme").textContent = { auto: "پوسته: خودکار", dark: "پوسته: تیره", light: "پوسته: روشن" }[S.theme];
    press($("btnResult"), S.resultMode);
    refreshView();
  }
  function pushSettings(patch) { return api("/api/settings", { patch: patch }); }
  function bumpFont(dir) {
    if (S.resultMode) S.resultFont = Math.max(20, Math.min(200, Math.round(S.resultFont * (dir > 0 ? 1.1 : 1 / 1.1))));
    else S.font = Math.max(10, Math.min(40, S.font + dir));
    applySettings();
    pushSettings({ font: S.font, resultFont: S.resultFont });
  }

  /* ---------- status chip (toolbar only: there is no status bar) */
  function setChip(kind, text) {
    const c = $("chip");
    c.className = "chip " + kind;
    c.textContent = text;
    c.title = text;
  }
  function updateTitle() {
    document.title = (cwdName ? cwdName + " — " : "") + "زاگرس · zagros:" + location.port;
  }

  function setMode(m, p) {
    mode = m;
    const typing = m === "shell" || m === "program";
    input.disabled = !typing;
    $("btnStop").disabled = m !== "program";
    if (m === "program") setChip("running", "در حال اجرا");
    else if (m === "shell") setChip("idle", "آماده");
    if (typing) input.focus();
    refreshView();
  }

  /* ---------- what is visible depends on mode and result mode */
  function refreshView() {
    show(live, !(S.resultMode && mode !== "program"));   // result mode: no prompt unless a program asks for input
    const anything = Array.from(screen.children).some((c) => c !== live && !/\bmeta\b/.test(c.className)) || promptEl.textContent !== "";
    show($("empty"), S.resultMode && mode !== "program" && !anything);
  }

  function setLiveDir() {
    const t = promptEl.textContent;
    const r = t.search(RTL), l = t.search(LTR);
    live.dir = r !== -1 && (l === -1 || r < l) ? "rtl" : "ltr";
  }

  function addText(op, cls, raw) {
    let s = op.s;
    if (S.faDigits && !raw) s = s.replace(/[0-9]/g, (d) => FA[d]);
    const sp = document.createElement("span");
    const c = cls ? [cls] : [];
    if (cls === "ps") lineMeta = true;
    if (op.bold) c.push("b");
    if (typeof op.fg === "number") c.push("fg" + op.fg); else if (op.fg) sp.style.color = op.fg;
    if (typeof op.bg === "number") c.push("bg" + op.bg); else if (op.bg) sp.style.backgroundColor = op.bg;
    sp.className = c.join(" ");
    sp.textContent = s;
    promptEl.appendChild(sp);
    setLiveDir();
  }

  function newline() {
    const ln = document.createElement("div");
    ln.className = "ln" + (lineMeta ? " meta" : "");
    ln.dir = lineLtr ? "ltr" : "auto";
    lineLtr = false; lineMeta = false;
    while (promptEl.firstChild) ln.appendChild(promptEl.firstChild);
    if (!ln.firstChild) ln.appendChild(document.createTextNode("\u200b"));
    screen.insertBefore(ln, live);
    while (screen.childElementCount - 1 > MAX_LINES) screen.removeChild(screen.firstElementChild);
    setLiveDir();
  }

  function note(text, extra) {
    const d = document.createElement("div");
    d.className = "ln meta " + (extra || "note");
    d.dir = "auto";
    d.textContent = text;
    screen.insertBefore(d, live);
  }

  function clearLines() { while (screen.firstElementChild !== live) screen.removeChild(screen.firstElementChild); refreshView(); }
  function clearScreen() { clearLines(); promptEl.textContent = ""; lineLtr = false; lineMeta = false; setLiveDir(); }

  function backspace() {
    const last = promptEl.lastElementChild;
    if (!last) return;
    last.textContent = Array.from(last.textContent).slice(0, -1).join("");
    if (!last.textContent) promptEl.removeChild(last);
    setLiveDir();
  }

  /* ---------- scrolling */
  const atBottom = () => screen.scrollHeight - screen.scrollTop - screen.clientHeight < 40;
  const toEnd = () => { screen.scrollTop = screen.scrollHeight; updateToBottom(); };
  function updateToBottom() { show($("toBottom"), !atBottom()); }

  function applyOps(ops, err, flags) {
    const stick = atBottom();
    if (flags && flags.ltr) lineLtr = true;
    if (flags && flags.meta) lineMeta = true;
    for (const op of ops) {
      if (op.k === "text") addText(op, err ? "err" : "");
      else if (op.k === "nl") newline();
      else if (op.k === "cr") { promptEl.textContent = ""; setLiveDir(); }
      else if (op.k === "bs") backspace();
      else if (op.k === "clear") clearScreen();
    }
    refreshView();
    if (stick) toEnd(); else updateToBottom();
  }

  /* ---------- server events */
  function onEvent(p) {
    if (p.t === "clear") { clearScreen(); return; }
    if (p.t === "settings") { Object.assign(S, p.settings); applySettings(); return; }
    if (p.t === "watch") { watchOn = !!p.on; press($("btnWatch"), watchOn); return; }
    if (p.t === "window") { refreshWin(); return; }
    if (p.t === "start") {
      run = p.run; title = p.title;
      if (p.cwd) { cwdName = p.cwd.split(/[\\/]/).filter(Boolean).pop() || p.cwd; updateTitle(); }
      states.out = newParseState(); states.err = newParseState();
      if (S.resultMode) clearLines();                    // like launching a fresh program window
      promptEl.textContent = ""; lineLtr = false; lineMeta = false;   // the dropped prompt must not tag the program's first line
      setLiveDir();
      setMode("program", p);
      return;
    }
    if (p.t === "prompt") {
      if (promptEl.textContent) newline();
      addText({ s: p.s }, "ps", true);
      if (p.cwd) { cwdName = p.cwd.split(/[\\/]/).filter(Boolean).pop() || p.cwd; updateTitle(); }
      setMode("shell");
      toEnd();
      return;
    }
    if (p.run && p.run !== run) return;                  // late output of a replaced program
    if (p.t === "out" || p.t === "err") {
      applyOps(parse(states[p.t], p.s), p.t === "err", { ltr: p.ltr, meta: !p.run });
    } else if (p.t === "exit") {
      if (promptEl.textContent) newline();
      const secs = typeof p.elapsed === "number" ? "، " + p.elapsed.toFixed(1) + " ثانیه" : "";
      note(p.stopped ? "— اجرا متوقف شد —" : "— پایان (کد خروج " + p.code + secs + ") —", p.code === 0 || p.stopped ? "" : "bad");
      if (p.stopped) setChip("idle", "متوقف شد");
      else if (p.code === 0) setChip("ok", "پایان ✓");
      else setChip("bad", "خطا (کد " + p.code + ")");
      mode = p.shell ? "busy" : "idle";
      input.disabled = true; $("btnStop").disabled = true;
      refreshView();
      toEnd();
    }
  }

  async function api(path, body) {
    try {
      const r = await fetch(path, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-FC-Token": token },
        body: JSON.stringify(body || {}),
      });
      return await r.json();
    } catch (e) {
      return { ok: false, error: "ارتباط با برنامه برقرار نشد" };
    }
  }
  const getJson = (path) => fetch(path, { headers: { "X-FC-Token": token } }).then((r) => r.json()).catch(() => null);

  /* ---------- running things */
  async function pickAndRun() {
    const r = await api("/api/pick");
    if (r.ok && r.path) { const q = await api("/api/run", { path: r.path }); if (!q.ok) toast(q.error); }
    else if (r.error) toast(r.error);
  }
  async function rerun() {
    const r = await api("/api/run");
    if (!r.ok) { if (r.error === "no script") pickAndRun(); else toast(r.error); }
  }

  async function submit() {
    if (mode !== "shell" && mode !== "program") return;
    const v = input.value;
    input.value = "";
    addText({ s: v }, "typed", true);
    newline();
    toEnd();
    if (mode === "shell") {
      if (v.trim() && hist[hist.length - 1] !== v) hist.push(v);
      hpos = hist.length;
      mode = "busy"; input.disabled = true; refreshView();
      const r = await api("/api/shell", { line: v });
      if (!r.ok) {
        toast(r.error === "busy" ? "برنامه‌ای در حال اجراست." : (r.error || "خطا"));
        if (mode === "busy") setMode("shell");
      }
    } else {
      await api("/api/stdin", { text: v + "\n", normalize: S.normalize });
    }
  }

  async function complete() {
    const line = input.value;
    const cur = input.selectionStart == null ? line.length : input.selectionStart;
    const r = await api("/api/complete", { line: line, cursor: cur });
    if (!r.ok || input.value !== line) return;
    if (r.replacement != null) {
      input.value = line.slice(0, r.start) + r.replacement + line.slice(r.end);
      const pos = r.start + r.replacement.length;
      input.setSelectionRange(pos, pos);
    }
    if (r.items && r.items.length > 1) { note(r.items.join("   "), "cands"); toEnd(); }
  }

  function insertAtCaret(text) {
    const s = input.selectionStart == null ? input.value.length : input.selectionStart;
    const e = input.selectionEnd == null ? s : input.selectionEnd;
    input.value = input.value.slice(0, s) + text + input.value.slice(e);
    input.setSelectionRange(s + text.length, s + text.length);
    input.focus();
  }

  /* ---------- drag & drop: run a script, or type the path of any other file */
  async function handleDrop(files, shift) {
    if (!files.length) return;
    const meta = files.map((f) => ({ name: f.name, size: f.size, mtime: f.lastModified }));
    const r = await api("/api/drop", { files: meta, shift: !!shift });
    if (!r.ok) { toast(r.error || "خطا"); return; }
    if (r.action === "insert") {
      if (input.disabled) { toast("برای درج مسیر باید پرامپت آماده باشد."); return; }
      insertAtCaret(r.text);
      if (r.missing && r.missing.length) toast("مسیر کامل پیدا نشد؛ فقط نام فایل درج شد.");
    } else if (r.action === "upload") {
      const f = files[r.index];
      if (f.size > MAX_UPLOAD) { toast("این فایل بزرگ‌تر از ۱ مگابایت است."); return; }
      const res = await fetch("/api/upload?name=" + encodeURIComponent(f.name), {
        method: "POST", headers: { "X-FC-Token": token, "Content-Type": "application/octet-stream" },
        body: await f.arrayBuffer(),
      }).then((x) => x.json()).catch(() => ({ ok: false, error: "ارسال فایل ناموفق بود" }));
      if (!res.ok) toast(res.error || "خطا");
    }
  }
  let dragDepth = 0;
  const hasFiles = (e) => e.dataTransfer && Array.from(e.dataTransfer.types || []).indexOf("Files") !== -1;
  window.addEventListener("dragenter", (e) => { if (hasFiles(e)) { e.preventDefault(); dragDepth++; show($("drop"), true); } });
  window.addEventListener("dragover", (e) => { if (hasFiles(e)) { e.preventDefault(); e.dataTransfer.dropEffect = "copy"; } });
  window.addEventListener("dragleave", () => { if (--dragDepth <= 0) { dragDepth = 0; show($("drop"), false); } });
  window.addEventListener("drop", (e) => {
    e.preventDefault(); dragDepth = 0; show($("drop"), false);
    if (e.dataTransfer) handleDrop(Array.from(e.dataTransfer.files || []), e.shiftKey);
  });

  /* ---------- output: copy / save */
  function outputText() {
    const lines = Array.from(screen.children).filter((c) => c !== live).map((c) => c.textContent);
    if (promptEl.textContent) lines.push(promptEl.textContent);
    return lines.join("\n").replace(/\u200b/g, "");
  }
  $("btnCopy").onclick = async () => {
    try { await navigator.clipboard.writeText(outputText()); toast("خروجی کپی شد."); }
    catch (e) { toast("کپی انجام نشد."); }
  };
  $("btnSave").onclick = () => {
    const url = URL.createObjectURL(new Blob([outputText()], { type: "text/plain;charset=utf-8" }));
    const a = document.createElement("a");
    a.href = url; a.download = "zagros-output.txt";
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
  };

  /* ---------- window panel (Windows only; the server tells us if it is available) */
  function renderWin(r) {
    if (!r) return;
    const ok = !!(r.available && r.found);
    show($("btnTop"), winAvail); show($("btnWin"), winAvail);
    press($("btnTop"), !!r.topmost);
    $("winLock").checked = !!r.locked;
    $("winOpacity").value = String(Math.round((r.opacity || 1) * 100));
    $("winOpVal").textContent = Math.round((r.opacity || 1) * 100) + "٪";
    if (r.w) { $("winW").value = String(r.w); $("winH").value = String(r.h); }
    show($("winNote"), !ok);
  }
  const refreshWin = () => api("/api/window", { action: "state" }).then(renderWin);
  async function winCall(body) {
    const r = await api("/api/window", body);
    if (!r.ok && r.error && r.error !== "unavailable") toast("پنجره: " + r.error);
    renderWin(r);
  }
  $("btnTop").onclick = () => winCall({ action: "topmost", on: !/\bon\b/.test($("btnTop").className) });
  Array.from(document.querySelectorAll ? document.querySelectorAll("[data-preset]") : []).forEach((b) => {
    b.onclick = () => winCall({ action: "preset", name: b.getAttribute("data-preset") });
  });
  Array.from(document.querySelectorAll ? document.querySelectorAll("[data-snap]") : []).forEach((b) => {
    b.onclick = () => winCall({ action: "snap", side: b.getAttribute("data-snap") });
  });
  $("winApply").onclick = () => winCall({ action: "size", w: parseInt($("winW").value, 10), h: parseInt($("winH").value, 10) });
  $("winLock").onchange = (e) => winCall({ action: "lock", on: e.target.checked });
  $("winOpacity").oninput = (e) => { $("winOpVal").textContent = e.target.value + "٪"; };
  $("winOpacity").onchange = (e) => winCall({ action: "opacity", value: parseInt(e.target.value, 10) / 100 });

  /* ---------- popovers */
  const pops = ["popWin", "popSet"];
  function togglePop(id) { pops.forEach((p) => show($(p), p === id && $(p).hidden)); }
  $("btnWin").onclick = (e) => { e.stopPropagation(); togglePop("popWin"); refreshWin(); };
  $("btnSet").onclick = (e) => { e.stopPropagation(); togglePop("popSet"); };
  document.addEventListener("click", (e) => {
    if (!e.target || !e.target.closest || !e.target.closest(".pop")) pops.forEach((p) => show($(p), false));
  });

  /* ---------- keyboard */
  input.addEventListener("keydown", (e) => {
    const noSel = input.selectionStart === input.selectionEnd && !String(window.getSelection());
    if (e.key === "Enter" && !e.isComposing) { e.preventDefault(); submit(); }
    else if (e.key === "Tab" && mode === "shell") { e.preventDefault(); complete(); }
    else if (e.key === "ArrowUp" && mode === "shell") { if (hpos > 0) input.value = hist[--hpos]; e.preventDefault(); }
    else if (e.key === "ArrowDown" && mode === "shell") {
      input.value = hpos < hist.length - 1 ? hist[++hpos] : ((hpos = hist.length), ""); e.preventDefault();
    }
    else if (e.key === "PageUp") { screen.scrollTop -= screen.clientHeight * 0.9; e.preventDefault(); updateToBottom(); }
    else if (e.key === "PageDown") { screen.scrollTop += screen.clientHeight * 0.9; e.preventDefault(); updateToBottom(); }
    else if (e.ctrlKey && e.key === "Home") { screen.scrollTop = 0; e.preventDefault(); updateToBottom(); }
    else if (e.ctrlKey && e.key === "End") { e.preventDefault(); toEnd(); }
    else if (e.ctrlKey && e.key.toLowerCase() === "l") { e.preventDefault(); clearLines(); }
    else if (e.ctrlKey && e.key.toLowerCase() === "c" && noSel) {
      e.preventDefault();
      if (mode === "program") api("/api/stop"); else input.value = "";
    }
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "F5") { e.preventDefault(); rerun(); }
    else if (e.ctrlKey && (e.key === "+" || e.key === "=")) { e.preventDefault(); bumpFont(1); }
    else if (e.ctrlKey && (e.key === "-" || e.key === "_")) { e.preventDefault(); bumpFont(-1); }
    else if (e.ctrlKey && e.key === "0") {
      e.preventDefault(); S.font = 17; S.resultFont = 52; applySettings(); pushSettings({ font: 17, resultFont: 52 });
    }
    else if (e.ctrlKey && e.key.toLowerCase() === "o") { e.preventDefault(); pickAndRun(); }
  });
  screen.addEventListener("wheel", (e) => { if (e.ctrlKey) { e.preventDefault(); bumpFont(e.deltaY < 0 ? 1 : -1); } }, { passive: false });
  screen.addEventListener("scroll", updateToBottom);
  screen.addEventListener("click", () => { if (!String(window.getSelection()) && !input.disabled) input.focus(); });
  $("toBottom").onclick = toEnd;

  /* ---------- toolbar */
  $("btnOpen").onclick = pickAndRun;
  $("btnRerun").onclick = rerun;
  $("btnRepl").onclick = () => api("/api/repl");
  $("btnStop").onclick = () => api("/api/stop");
  $("btnClear").onclick = clearLines;
  $("btnWatch").onclick = async () => {
    const r = await api("/api/watch", { on: !watchOn });
    if (!r.ok) toast(r.error === "no script" ? "ابتدا یک برنامه را اجرا کنید." : r.error);
  };
  $("btnResult").onclick = () => { S.resultMode = !S.resultMode; applySettings(); pushSettings({ resultMode: S.resultMode }); };
  $("fontInc").onclick = () => bumpFont(1);
  $("fontDec").onclick = () => bumpFont(-1);
  $("btnTheme").onclick = () => { S.theme = { auto: "dark", dark: "light", light: "auto" }[S.theme]; applySettings(); pushSettings({ theme: S.theme }); };
  $("optNorm").onchange = (e) => { S.normalize = e.target.checked; pushSettings({ normalize: S.normalize }); };
  $("optFa").onchange = (e) => { S.faDigits = e.target.checked; pushSettings({ faDigits: S.faDigits }); };

  /* ---------- start */
  applySettings();
  setMode("idle");
  setChip("idle", "در حال اتصال…");
  updateTitle();
  getJson("/api/settings").then((j) => {
    if (!j || !j.settings) return;
    const urlResult = qs.get("m") === "result";
    Object.assign(S, j.settings);
    if (urlResult) S.resultMode = true;
    version = j.version || "";
    winAvail = !!j.window_available;
    $("aboutVer").textContent = version ? "zagros " + version : "zagros";
    applySettings();
    if (winAvail) refreshWin();
  });
  getJson("/api/history").then((j) => { if (j && j.history) { hist = j.history.slice(); hpos = hist.length; } });
  const es = new EventSource("/events?since=0&t=" + encodeURIComponent(token));
  es.onmessage = (m) => { try { onEvent(JSON.parse(m.data)); } catch (e) { /* ignore malformed */ } };
  es.onopen = () => { if (mode === "idle" && !run) setChip("idle", "آماده"); };
  es.onerror = () => setChip("bad", "ارتباط قطع شد");
})();
