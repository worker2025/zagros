// Runs the real DOM half of console.js against a tiny fake DOM (there is no browser in CI).
// `children` is deliberately array-LIKE, not an Array, exactly like a real HTMLCollection.
const test = require("node:test");
const assert = require("node:assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

class N {
  constructor(tag) {
    this.tag = tag; this._kids = []; this.parent = null; this.style = {}; this.className = ""; this.dir = "";
    this._t = ""; this.l = {}; this.value = ""; this.disabled = false; this.checked = false; this.hidden = false;
    this.scrollTop = 0; this.scrollHeight = 0; this.clientHeight = 0; this.selectionStart = 0; this.selectionEnd = 0;
    this.attrs = {}; this.title = ""; this.clicked = false;
  }
  get children() { const o = { length: this._kids.length }; this._kids.forEach((c, i) => (o[i] = c)); return o; }
  get firstChild() { return this._kids[0] || null; }
  get firstElementChild() { return this._kids.find((c) => c.tag !== "#text") || null; }
  get lastElementChild() { const e = this._kids.filter((c) => c.tag !== "#text"); return e[e.length - 1] || null; }
  get childElementCount() { return this._kids.filter((c) => c.tag !== "#text").length; }
  appendChild(c) { if (c.parent) c.parent.removeChild(c); c.parent = this; this._kids.push(c); return c; }
  insertBefore(c, ref) { if (c.parent) c.parent.removeChild(c); c.parent = this;
    const i = this._kids.indexOf(ref); this._kids.splice(i < 0 ? this._kids.length : i, 0, c); return c; }
  removeChild(c) { const i = this._kids.indexOf(c); if (i >= 0) this._kids.splice(i, 1); c.parent = null; return c; }
  get textContent() { return this.tag === "#text" ? this._t : this._kids.map((c) => c.textContent).join(""); }
  set textContent(v) { this._kids.forEach((c) => (c.parent = null)); this._kids = [];
    if (this.tag === "#text") this._t = v; else if (v !== "") { const t = new N("#text"); t._t = v; this.appendChild(t); } }
  addEventListener(ev, fn) { (this.l[ev] = this.l[ev] || []).push(fn); }
  fire(ev, e) { (this.l[ev] || []).forEach((f) => f(e)); }
  focus() {} removeAttribute(k) { delete this.attrs[k]; }
  setAttribute(k, v) { this.attrs[k] = String(v); } getAttribute(k) { return this.attrs[k]; }
  setSelectionRange(a, b) { this.selectionStart = a; this.selectionEnd = b; }
  click() { this.clicked = true; }
  closest() { return null; }
}
const text = (s) => { const t = new N("#text"); t._t = s; return t; };

const SETTINGS = { font: 17, theme: "auto", normalize: true, faDigits: false, resultMode: false, resultFont: 52 };
const HIDDEN = ["btnTop", "btnWin", "popWin", "popSet", "winNote", "empty", "toBottom", "toast", "drop"];

function boot(opts = {}) {
  const ids = {};
  ["screen", "live", "prompt", "in", "chip", "btnOpen", "btnRerun", "btnStop", "btnWatch", "btnResult", "fontDec",
   "fontInc", "btnRepl", "btnCopy", "btnSave", "btnClear", "btnTop", "btnWin", "btnSet", "popWin", "popSet", "winW",
   "winH", "winApply", "winLock", "winOpacity", "winOpVal", "winNote", "optNorm", "optFa", "btnTheme", "aboutVer",
   "empty", "toBottom", "toast", "drop"].forEach((i) => (ids[i] = new N(i)));
  HIDDEN.forEach((i) => (ids[i].hidden = true));
  ids.screen.appendChild(ids.live); ids.live.appendChild(ids.prompt); ids.live.appendChild(ids.in);
  const presets = ["small", "medium", "large"].map((n) => { const b = new N("button"); b.setAttribute("data-preset", n); return b; });
  const snaps = ["left", "center", "right"].map((n) => { const b = new N("button"); b.setAttribute("data-snap", n); return b; });
  const calls = [], uploads = [];
  const reply = Object.assign({
    "/api/settings": { ok: true, settings: Object.assign({}, SETTINGS), version: "0.3.0", window_available: false },
    "/api/history": { ok: true, history: [] },
  }, opts.reply || {});
  let es;
  class ES { constructor(u) { this.url = u; es = this; } }
  const docN = new N("doc"), winN = new N("win"), body = new N("body");
  const props = {}, htmlAttrs = {};
  const clip = [], blobs = [], revoked = [], anchors = [];
  const sandbox = {
    document: {
      getElementById: (i) => ids[i], createElement: (t) => { const n = new N(t); if (t === "a") anchors.push(n); return n; },
      createTextNode: text, body, title: "",
      documentElement: { style: { setProperty(k, v) { props[k] = v; } }, setAttribute(k, v) { htmlAttrs[k] = v; }, removeAttribute(k) { delete htmlAttrs[k]; } },
      addEventListener: (ev, fn) => docN.addEventListener(ev, fn),
      querySelectorAll: (sel) => (sel === "[data-preset]" ? presets : sel === "[data-snap]" ? snaps : []),
    },
    window: { getSelection: () => "", addEventListener: (ev, fn) => winN.addEventListener(ev, fn) },
    location: { search: opts.search || "?t=TOK", port: "5000" },
    navigator: { clipboard: { writeText: async (t) => { if (opts.clipFail) throw new Error("no"); clip.push(t); } } },
    Blob: class { constructor(parts, o) { this.parts = parts; this.type = o && o.type; blobs.push(this); } },
    URL: { createObjectURL: () => "blob:x", revokeObjectURL: (u) => revoked.push(u) },
    EventSource: ES, URLSearchParams, encodeURIComponent,
    setTimeout: (f, ms) => { const t = setTimeout(f, ms); if (t.unref) t.unref(); return t; }, clearTimeout,
    fetch: async (url, opt) => {
      const o = opt || {};
      const parsed = typeof o.body === "string" ? JSON.parse(o.body) : (o.body === undefined ? null : o.body);
      calls.push([url, parsed, o.headers || {}, o]);
      const key = url.split("?")[0];
      return { json: async () => (typeof reply[key] === "function" ? reply[key](parsed) : reply[key] !== undefined ? reply[key] : { ok: true }) };
    },
    console,
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../src/zagros/web/console.js"), "utf8"), sandbox);
  const lineNodes = () => Array.from(ids.screen.children).filter((c) => c !== ids.live);
  return {
    ids, calls, reply, props, htmlAttrs, clip, blobs, revoked, anchors, doc: docN, win: winN, body, document: sandbox.document,
    es: () => es, send: (p) => es.onmessage({ data: JSON.stringify(p) }),
    nodes: lineNodes, lines: () => lineNodes().map((c) => c.textContent),
    tick: async () => { for (let i = 0; i < 4; i++) await new Promise((r) => setImmediate(r)); },
    api: (u) => calls.filter((c) => c[0].split("?")[0] === u),
  };
}
const key = (u, k, extra) => u.ids.in.fire("keydown", Object.assign({ key: k, preventDefault() {}, isComposing: false }, extra || {}));
const dkey = (u, k, extra) => u.doc.fire("keydown", Object.assign({ key: k, preventDefault() {} }, extra || {}));
const has = (el, cls) => new RegExp("(^|\\s)" + cls + "(\\s|$)").test(el.className);

// ---------------------------------------------------------------- startup
test("starts: connects with token, loads settings + history, shows version, hides window buttons", async () => {
  const u = boot({ reply: { "/api/history": { ok: true, history: ["pwd", "help"] } } });
  assert.match(u.es().url, /^\/events\?since=0&t=TOK$/);
  await u.tick();
  assert.strictEqual(u.api("/api/settings")[0][2]["X-FC-Token"], "TOK");
  assert.strictEqual(u.ids.aboutVer.textContent, "zagros 0.3.0");
  assert.strictEqual(u.ids.btnTop.hidden, true);
  assert.strictEqual(u.document.title, "زاگرس · zagros:5000");
  u.es().onopen();
  assert.strictEqual(u.ids.chip.textContent, "آماده");
  u.send({ t: "prompt", run: 0, s: "> " });
  key(u, "ArrowUp"); assert.strictEqual(u.ids.in.value, "help");          // history came from the server
});

test("saved settings are applied (font, theme, flags)", async () => {
  const u = boot({ reply: { "/api/settings": { ok: true, version: "x", window_available: false,
    settings: { font: 25, theme: "dark", normalize: false, faDigits: true, resultMode: false, resultFont: 80 } } } });
  await u.tick();
  assert.strictEqual(u.props["--fs"], "25px");
  assert.strictEqual(u.props["--rfs"], "80px");
  assert.strictEqual(u.htmlAttrs["data-theme"], "dark");
  assert.strictEqual(u.ids.optNorm.checked, false);
  assert.strictEqual(u.ids.optFa.checked, true);
});

// ---------------------------------------------------------------- shell + program
test("shell prompt: type a command, it is echoed and sent to /api/shell; title shows the folder", async () => {
  const u = boot();
  u.send({ t: "out", run: 0, s: "hello\n" });
  u.send({ t: "prompt", run: 0, s: "~/proj> ", cwd: "/home/x/proj" });
  assert.strictEqual(u.ids.prompt.textContent, "~/proj> ");
  assert.strictEqual(u.ids.live.dir, "ltr");
  assert.strictEqual(u.ids.in.disabled, false);
  assert.strictEqual(u.document.title, "proj — زاگرس · zagros:5000");
  u.ids.in.value = "run برنامه.py";
  key(u, "Enter"); await u.tick();
  assert.deepStrictEqual(u.lines(), ["hello", "~/proj> run برنامه.py"]);
  assert.deepStrictEqual(u.api("/api/shell").map((c) => c[1]), [{ line: "run برنامه.py" }]);
  assert.strictEqual(u.ids.in.disabled, true);                           // busy until the next prompt
  assert.ok(has(u.ids.screen.children[1].children[0], "ps"));
});

test("program lifecycle with status chip: running -> ok / bad / stopped", async () => {
  const u = boot();
  u.send({ t: "prompt", run: 0, s: "> " });
  u.ids.in.value = "x.py"; key(u, "Enter"); await u.tick();
  u.send({ t: "start", run: 1, kind: "script", title: "x.py", cwd: "C:\\Users\\me\\iz" });
  assert.strictEqual(u.ids.btnStop.disabled, false);
  assert.ok(has(u.ids.chip, "running"));
  assert.strictEqual(u.document.title, "iz — زاگرس · zagros:5000");
  u.send({ t: "out", run: 1, s: "نام: " });
  assert.strictEqual(u.ids.live.dir, "rtl");
  u.ids.in.value = "علی"; key(u, "Enter"); await u.tick();
  assert.deepStrictEqual(u.api("/api/stdin")[0][1], { text: "علی\n", normalize: true });
  u.send({ t: "err", run: 1, s: "Traceback\n" });
  u.send({ t: "exit", run: 1, code: 1, stopped: false, elapsed: 0.42, shell: true });
  const l = u.lines();
  assert.deepStrictEqual(l.slice(0, 3), ["> x.py", "نام: علی", "Traceback"]);
  assert.match(l[3], /کد خروج 1، 0\.4 ثانیه/);
  assert.ok(has(u.ids.chip, "bad")); assert.match(u.ids.chip.textContent, /کد 1/);
  assert.strictEqual(u.ids.in.disabled, true);
  u.send({ t: "prompt", run: 0, s: "> " });
  assert.strictEqual(u.ids.in.disabled, false);
  assert.ok(has(u.ids.chip, "idle"));

  u.send({ t: "start", run: 2, kind: "script", title: "y.py" });
  u.send({ t: "exit", run: 2, code: 0, stopped: false, shell: true });
  assert.ok(has(u.ids.chip, "ok")); assert.strictEqual(u.ids.chip.textContent, "پایان ✓");
  u.send({ t: "start", run: 3, kind: "script", title: "z.py" });
  u.send({ t: "exit", run: 3, code: 1, stopped: true, shell: true });
  assert.strictEqual(u.ids.chip.textContent, "متوقف شد");
});

test("without a shell the UI goes idle after exit", () => {
  const u = boot();
  u.send({ t: "start", run: 1, kind: "script", title: "t" });
  u.send({ t: "exit", run: 1, code: 0, stopped: false, shell: false });
  assert.strictEqual(u.ids.in.disabled, true);
});

test("late output of a replaced program is ignored; start keeps scrollback in normal mode", () => {
  const u = boot();
  u.send({ t: "start", run: 1, kind: "script", title: "a" });
  u.send({ t: "out", run: 1, s: "old\n" });
  u.send({ t: "start", run: 2, kind: "script", title: "b" });
  assert.deepStrictEqual(u.lines(), ["old"]);
  u.send({ t: "out", run: 1, s: "ghost\n" });
  u.send({ t: "out", run: 2, s: "new\n" });
  assert.deepStrictEqual(u.lines(), ["old", "new"]);
});

test("left-to-right flag: file listings are LTR, other lines auto", () => {
  const u = boot();
  u.send({ t: "out", run: 0, s: "سلام.py\n", ltr: true });
  u.send({ t: "out", run: 0, s: "متن\n" });
  assert.deepStrictEqual(u.nodes().map((n) => n.dir), ["ltr", "auto"]);
});

// ---------------------------------------------------------------- result mode
test("result mode via the launcher URL: only program output is visible, huge font, no prompt", async () => {
  const u = boot({ search: "?t=TOK&m=result" });
  await u.tick();
  assert.ok(has(u.body, "result"));
  assert.ok(has(u.ids.btnResult, "on"));
  assert.strictEqual(u.ids.btnResult.attrs["aria-pressed"], "true");
  assert.strictEqual(u.ids.live.hidden, true);                       // nothing to type into yet
  assert.strictEqual(u.ids.empty.hidden, false);                     // only a faint hint

  u.send({ t: "out", run: 0, s: "banner\n" });                       // shell chatter
  u.send({ t: "prompt", run: 0, s: "~> " });
  u.send({ t: "start", run: 1, kind: "script", title: "p.py" });
  assert.strictEqual(u.ids.live.hidden, false);                      // a program may ask for input
  u.send({ t: "out", run: 1, s: "نام: " });
  u.ids.in.value = "علی"; key(u, "Enter"); await u.tick();
  u.send({ t: "out", run: 1, s: "سلام علی\n" });
  u.send({ t: "exit", run: 1, code: 0, stopped: false, elapsed: 1, shell: true });
  const meta = u.nodes().map((n) => has(n, "meta"));
  assert.deepStrictEqual(u.lines(), ["نام: علی", "سلام علی", "— پایان (کد خروج 0، 1.0 ثانیه) —"]);   // old chatter was cleared at start
  assert.deepStrictEqual(meta, [false, false, true]);                // the "finished" note is meta -> hidden by CSS
  assert.strictEqual(u.ids.empty.hidden, true);
  assert.strictEqual(u.ids.live.hidden, true);                       // program is over: no prompt, just the result
  u.send({ t: "start", run: 2, kind: "script", title: "p.py" });     // next run replaces the picture
  assert.deepStrictEqual(u.lines(), []);
});

test("meta flags: shell chatter and prompt lines are meta, program lines are not", () => {
  const u = boot();
  u.send({ t: "out", run: 0, s: "welcome\n" });
  u.send({ t: "prompt", run: 0, s: "~> " });
  u.send({ t: "out", run: 0, s: 'run "a.py"\n' });                   // appended to the prompt line
  u.send({ t: "start", run: 1, kind: "script", title: "a.py" });
  u.send({ t: "out", run: 1, s: "result\n" });
  u.send({ t: "err", run: 1, s: "boom\n" });
  assert.deepStrictEqual(u.lines(), ['welcome', '~> run "a.py"', "result", "boom"]);
  assert.deepStrictEqual(u.nodes().map((n) => has(n, "meta")), [true, true, false, false]);
});

test("result mode toggle persists, and a settings event can switch it off", async () => {
  const u = boot();
  await u.tick();
  assert.ok(!has(u.body, "result"));
  u.ids.btnResult.onclick();
  assert.ok(has(u.body, "result"));
  assert.deepStrictEqual(u.api("/api/settings").filter((c) => c[1]).map((c) => c[1]), [{ patch: { resultMode: true } }]);
  u.send({ t: "settings", run: 0, settings: Object.assign({}, SETTINGS, { resultMode: false, theme: "light" }) });
  assert.ok(!has(u.body, "result"));
  assert.strictEqual(u.htmlAttrs["data-theme"], "light");
});

test("font keys: Ctrl +/-/0, Ctrl+wheel, A+/A-; result mode scales proportionally and clamps", async () => {
  const u = boot();
  await u.tick();
  const last = () => u.api("/api/settings").filter((c) => c[1]).pop()[1].patch;
  dkey(u, "+", { ctrlKey: true });
  assert.strictEqual(u.props["--fs"], "18px");
  assert.strictEqual(last().font, 18);
  u.ids.screen.fire("wheel", { ctrlKey: true, deltaY: 100, preventDefault() {} });
  assert.strictEqual(u.props["--fs"], "17px");
  u.ids.screen.fire("wheel", { ctrlKey: false, deltaY: 100, preventDefault() { throw new Error("must scroll normally"); } });
  dkey(u, "0", { ctrlKey: true });
  assert.deepStrictEqual(last(), { font: 17, resultFont: 52 });
  u.ids.btnResult.onclick();
  u.ids.fontInc.onclick();
  assert.strictEqual(u.props["--rfs"], "57px");                      // 52 * 1.1
  u.ids.fontDec.onclick(); u.ids.fontDec.onclick();
  assert.strictEqual(u.props["--rfs"], "47px");
  for (let i = 0; i < 40; i++) u.ids.fontInc.onclick();
  assert.strictEqual(u.props["--rfs"], "200px");
  for (let i = 0; i < 60; i++) u.ids.fontDec.onclick();
  assert.strictEqual(u.props["--rfs"], "20px");
});

// ---------------------------------------------------------------- scrolling
test("scrolling: jump-to-end button, no yanking while reading old output, PageUp/PageDown, Ctrl+Home/End", () => {
  const u = boot();
  const s = u.ids.screen;
  s.scrollHeight = 1000; s.clientHeight = 300; s.scrollTop = 700;     // at the bottom
  s.fire("scroll");
  assert.strictEqual(u.ids.toBottom.hidden, true);
  u.send({ t: "out", run: 0, s: "a\n" });
  assert.strictEqual(s.scrollTop, 1000);                              // follows the output
  s.scrollTop = 100;                                                  // user scrolled up to read
  s.fire("scroll");
  assert.strictEqual(u.ids.toBottom.hidden, false);
  u.send({ t: "out", run: 0, s: "more output\n" });
  assert.strictEqual(s.scrollTop, 100);                               // not yanked away
  assert.strictEqual(u.ids.toBottom.hidden, false);
  u.ids.toBottom.onclick();
  assert.strictEqual(s.scrollTop, 1000);
  assert.strictEqual(u.ids.toBottom.hidden, true);
  s.scrollTop = 500;
  key(u, "PageUp"); assert.strictEqual(s.scrollTop, 500 - 270);
  key(u, "PageDown"); assert.strictEqual(s.scrollTop, 500);
  key(u, "Home", { ctrlKey: true }); assert.strictEqual(s.scrollTop, 0);
  key(u, "End", { ctrlKey: true }); assert.strictEqual(s.scrollTop, 1000);
});

test("submitting always jumps back to the end", async () => {
  const u = boot();
  u.send({ t: "prompt", run: 0, s: "> " });
  u.ids.screen.scrollHeight = 900; u.ids.screen.clientHeight = 300; u.ids.screen.scrollTop = 0;
  u.ids.in.value = "ls"; key(u, "Enter"); await u.tick();
  assert.strictEqual(u.ids.screen.scrollTop, 900);
});

// ---------------------------------------------------------------- drag & drop
const dt = (files, types) => ({ files, types: types || ["Files"], dropEffect: "" });
const ev = (d, extra) => Object.assign({ preventDefault() {}, dataTransfer: d }, extra || {});
const file = (name, size, mtime, buf) => ({ name, size, lastModified: mtime, arrayBuffer: async () => buf || Buffer.from("print(1)") });

test("drag overlay appears for files only and disappears on leave/drop", () => {
  const u = boot();
  u.win.fire("dragenter", ev(dt([], ["text/plain"])));
  assert.strictEqual(u.ids.drop.hidden, true);                        // ordinary text drags are ignored
  u.win.fire("dragenter", ev(dt([file("a.py", 1, 1)])));
  u.win.fire("dragenter", ev(dt([file("a.py", 1, 1)])));              // child elements fire enter again
  assert.strictEqual(u.ids.drop.hidden, false);
  u.win.fire("dragleave", {});
  assert.strictEqual(u.ids.drop.hidden, false);
  u.win.fire("dragleave", {});
  assert.strictEqual(u.ids.drop.hidden, true);
});

test("drop a script: sends name/size/mtime (+Shift) and the server runs it", async () => {
  const u = boot({ reply: { "/api/drop": { ok: true, action: "run", path: "C:\\x\\a.py", matches: 1 } } });
  u.win.fire("drop", ev(dt([file("سلام.py", 42, 1700000000000)]), { shiftKey: false }));
  await u.tick();
  assert.deepStrictEqual(u.api("/api/drop")[0][1], { files: [{ name: "سلام.py", size: 42, mtime: 1700000000000 }], shift: false });
  assert.strictEqual(u.api("/api/upload").length, 0);
  assert.strictEqual(u.ids.drop.hidden, true);
});

test("drop of other files inserts their path at the caret (needs a ready prompt)", async () => {
  const u = boot({ reply: { "/api/drop": { ok: true, action: "insert", text: '"C:\\my data\\n.csv" ', missing: [] } } });
  u.send({ t: "prompt", run: 0, s: "> " });
  u.ids.in.value = "cat "; u.ids.in.selectionStart = u.ids.in.selectionEnd = 4;
  u.win.fire("drop", ev(dt([file("n.csv", 5, 5)]), { shiftKey: true }));
  await u.tick();
  assert.strictEqual(u.api("/api/drop")[0][1].shift, true);
  assert.strictEqual(u.ids.in.value, 'cat "C:\\my data\\n.csv" ');
  assert.strictEqual(u.ids.in.selectionStart, u.ids.in.value.length);
  u.send({ t: "start", run: 1, kind: "script", title: "p" });        // a program is running: input is for the program
  u.ids.in.disabled = true;
  u.win.fire("drop", ev(dt([file("n.csv", 5, 5)])));
  await u.tick();
  assert.match(u.ids.toast.textContent, /پرامپت/);
});

test("drop of a script whose path is unknown uploads a copy; big files are refused locally", async () => {
  const u = boot({ reply: { "/api/drop": { ok: true, action: "upload", index: 1, name: "b ü.py" } } });
  u.win.fire("drop", ev(dt([file("x.txt", 1, 1), file("b ü.py", 9, 9, Buffer.from("print(2)"))])));
  await u.tick();
  const up = u.api("/api/upload")[0];
  assert.strictEqual(up[0], "/api/upload?name=b%20%C3%BC.py");
  assert.strictEqual(up[2]["X-FC-Token"], "TOK");
  assert.strictEqual(String(up[1]), "print(2)");
  u.calls.length = 0;
  u.win.fire("drop", ev(dt([file("x.txt", 1, 1), file("b ü.py", 5_000_000, 9)])));
  await u.tick();
  assert.strictEqual(u.api("/api/upload").length, 0);
  assert.match(u.ids.toast.textContent, /۱ مگابایت/);
});

test("drop errors from the server are shown in a toast", async () => {
  const u = boot({ reply: { "/api/drop": { ok: false, error: "bad file info" } } });
  u.win.fire("drop", ev(dt([file("a.py", 1, 1)])));
  await u.tick();
  assert.strictEqual(u.ids.toast.textContent, "bad file info");
  assert.strictEqual(u.ids.toast.hidden, false);
});

// ---------------------------------------------------------------- window panel
const WIN = { ok: true, available: true, found: true, topmost: false, locked: false, opacity: 1, w: 900, h: 600 };

test("window buttons are shown only when the server says control is available, and reflect state", async () => {
  const u = boot({ reply: {
    "/api/settings": { ok: true, settings: SETTINGS, version: "1", window_available: true },
    "/api/window": () => Object.assign({}, WIN, u_state),
  } });
  await u.tick();
  assert.strictEqual(u.ids.btnTop.hidden, false);
  assert.strictEqual(u.ids.btnWin.hidden, false);
  assert.strictEqual(u.ids.winW.value, "900");
  assert.strictEqual(u.ids.winNote.hidden, true);

  u_state = { topmost: true, locked: true, opacity: 0.7 };
  u.send({ t: "window", run: 0 }); await u.tick();                    // the shell changed it with `window top`
  assert.ok(has(u.ids.btnTop, "on"));
  assert.strictEqual(u.ids.winLock.checked, true);
  assert.strictEqual(u.ids.winOpacity.value, "70");
  assert.strictEqual(u.ids.winOpVal.textContent, "70٪");

  u_state = { found: false };
  u.send({ t: "window", run: 0 }); await u.tick();
  assert.strictEqual(u.ids.winNote.hidden, false);
  u_state = {};
});
let u_state = {};

test("window panel actions call the API with the right bodies", async () => {
  u_state = {};
  const u = boot({ reply: {
    "/api/settings": { ok: true, settings: SETTINGS, version: "1", window_available: true },
    "/api/window": () => Object.assign({}, WIN, u_state),
  } });
  await u.tick();
  const body = () => u.api("/api/window").pop()[1];
  u.ids.btnTop.onclick(); await u.tick();
  assert.deepStrictEqual(body(), { action: "topmost", on: true });
  u_state = { topmost: true };
  u.ids.btnTop.onclick(); await u.tick();                             // second click turns it off
  assert.deepStrictEqual(body(), { action: "topmost", on: true });    // (state not refreshed yet: still "off" in the DOM)
  u.send({ t: "window", run: 0 }); await u.tick();
  u.ids.btnTop.onclick(); await u.tick();
  assert.deepStrictEqual(body(), { action: "topmost", on: false });
  const presets = u.document.querySelectorAll("[data-preset]");
  presets[1].onclick(); await u.tick();
  assert.deepStrictEqual(body(), { action: "preset", name: "medium" });
  u.document.querySelectorAll("[data-snap]")[2].onclick(); await u.tick();
  assert.deepStrictEqual(body(), { action: "snap", side: "right" });
  u.ids.winW.value = "1000"; u.ids.winH.value = "650"; u.ids.winApply.onclick(); await u.tick();
  assert.deepStrictEqual(body(), { action: "size", w: 1000, h: 650 });
  u.ids.winLock.onchange({ target: { checked: true } }); await u.tick();
  assert.deepStrictEqual(body(), { action: "lock", on: true });
  u.ids.winOpacity.oninput({ target: { value: "55" } });
  assert.strictEqual(u.ids.winOpVal.textContent, "55٪");
  u.ids.winOpacity.onchange({ target: { value: "55" } }); await u.tick();
  assert.deepStrictEqual(body(), { action: "opacity", value: 0.55 });
});

test("a failing window action shows a toast", async () => {
  const u = boot({ reply: {
    "/api/settings": { ok: true, settings: SETTINGS, version: "1", window_available: true },
    "/api/window": (b) => (b.action === "state" ? WIN : { ok: false, error: "window not found", available: true, found: false }),
  } });
  await u.tick();
  u.ids.btnTop.onclick(); await u.tick();
  assert.match(u.ids.toast.textContent, /window not found/);
});

test("popovers: open on click, close on outside click, window panel refreshes state when opened", async () => {
  const u = boot({ reply: { "/api/settings": { ok: true, settings: SETTINGS, version: "1", window_available: true } } });
  await u.tick();
  const stop = { stopPropagation() {} };
  u.ids.btnSet.onclick(stop);
  assert.strictEqual(u.ids.popSet.hidden, false);
  u.ids.btnWin.onclick(stop);
  assert.strictEqual(u.ids.popWin.hidden, false);
  assert.strictEqual(u.ids.popSet.hidden, true);                      // only one at a time
  u.doc.fire("click", { target: { closest: () => ({}) } });           // click inside a popover
  assert.strictEqual(u.ids.popWin.hidden, false);
  u.doc.fire("click", { target: { closest: () => null } });           // outside
  assert.strictEqual(u.ids.popWin.hidden, true);
  u.ids.btnSet.onclick(stop); u.ids.btnSet.onclick(stop);             // toggle off
  assert.strictEqual(u.ids.popSet.hidden, true);
});

// ---------------------------------------------------------------- toolbar actions
test("watch toggle posts the opposite state; 'watch' events flip the button; no-script is explained", async () => {
  const u = boot({ reply: { "/api/watch": { ok: false, error: "no script" } } });
  u.ids.btnWatch.onclick(); await u.tick();
  assert.deepStrictEqual(u.api("/api/watch")[0][1], { on: true });
  assert.match(u.ids.toast.textContent, /ابتدا یک برنامه/);
  u.send({ t: "watch", run: 0, on: true, path: "x.py" });
  assert.ok(has(u.ids.btnWatch, "on"));
  u.reply["/api/watch"] = { ok: true, active: false };
  u.ids.btnWatch.onclick(); await u.tick();
  assert.deepStrictEqual(u.api("/api/watch")[1][1], { on: false });   // it was on, so ask to turn off
  u.send({ t: "watch", run: 0, on: false });
  assert.ok(!has(u.ids.btnWatch, "on"));
});

test("copy and save output (zero-width placeholders removed, prompt line included)", async () => {
  const u = boot();
  u.send({ t: "start", run: 1, kind: "script", title: "p" });
  u.send({ t: "out", run: 1, s: "سلام\n\nدنیا\n" });
  u.send({ t: "out", run: 1, s: "نام: " });
  await u.ids.btnCopy.onclick();
  assert.deepStrictEqual(u.clip, ["سلام\n\nدنیا\nنام: "]);
  assert.match(u.ids.toast.textContent, /کپی شد/);
  u.ids.btnSave.onclick();
  assert.strictEqual(u.blobs[0].parts[0], "سلام\n\nدنیا\nنام: ");
  assert.strictEqual(u.anchors[0].download, "zagros-output.txt");
  assert.strictEqual(u.anchors[0].clicked, true);
});

test("copy failure is reported", async () => {
  const u = boot({ clipFail: true });
  await u.ids.btnCopy.onclick();
  assert.match(u.ids.toast.textContent, /کپی انجام نشد/);
});

test("keyboard shortcuts: F5 re-run, Ctrl+O open file; buttons call the API", async () => {
  const u = boot();
  dkey(u, "F5"); await u.tick();
  assert.strictEqual(u.api("/api/run").length, 1);
  dkey(u, "o", { ctrlKey: true }); await u.tick();
  assert.strictEqual(u.api("/api/pick").length, 1);
  u.ids.btnStop.onclick(); u.ids.btnRepl.onclick(); await u.tick();
  assert.strictEqual(u.api("/api/stop").length, 1);
  assert.strictEqual(u.api("/api/repl").length, 1);
});

test("re-run with no script falls back to the file picker", async () => {
  const u = boot({ reply: { "/api/run": { ok: false, error: "no script" }, "/api/pick": { ok: true, path: "C:\\p.py" } } });
  u.ids.btnRerun.onclick(); await u.tick();
  assert.strictEqual(u.api("/api/pick").length, 1);
  assert.deepStrictEqual(u.api("/api/run").pop()[1], { path: "C:\\p.py" });
});

// ---------------------------------------------------------------- typing keys (unchanged behaviour)
test("history with arrow keys works in shell mode only", async () => {
  const u = boot({ reply: { "/api/history": { ok: true, history: ["pwd", "help"] } } });
  await u.tick();
  u.send({ t: "prompt", run: 0, s: "> " });
  key(u, "ArrowUp"); assert.strictEqual(u.ids.in.value, "help");
  key(u, "ArrowUp"); assert.strictEqual(u.ids.in.value, "pwd");
  key(u, "ArrowDown"); assert.strictEqual(u.ids.in.value, "help");
  key(u, "ArrowDown"); assert.strictEqual(u.ids.in.value, "");
  u.send({ t: "start", run: 1, kind: "repl", title: "Python" });
  u.ids.in.value = "keep"; key(u, "ArrowUp");
  assert.strictEqual(u.ids.in.value, "keep");
});

test("Tab completion replaces the token and lists ambiguous candidates", async () => {
  const u = boot();
  u.send({ t: "prompt", run: 0, s: "> " });
  u.ids.in.value = "run al"; u.ids.in.selectionStart = u.ids.in.selectionEnd = 6;
  u.reply["/api/complete"] = { ok: true, start: 4, end: 6, replacement: "alpha", items: ["alpha.py", "alpha_two.py"] };
  key(u, "Tab"); await u.tick();
  assert.deepStrictEqual(u.api("/api/complete")[0][1], { line: "run al", cursor: 6 });
  assert.strictEqual(u.ids.in.value, "run alpha");
  assert.deepStrictEqual(u.lines(), ["alpha.py   alpha_two.py"]);
  assert.ok(has(u.nodes()[0], "meta"));
  u.ids.in.value = "run z"; u.reply["/api/complete"] = { ok: true, start: 4, end: 5, replacement: null, items: [] };
  key(u, "Tab"); await u.tick();
  assert.strictEqual(u.ids.in.value, "run z");
  u.send({ t: "start", run: 1, kind: "script", title: "p" });
  const n = u.api("/api/complete").length;
  key(u, "Tab"); await u.tick();
  assert.strictEqual(u.api("/api/complete").length, n);               // no completion while a program runs
});

test("Ctrl+C stops a program but only clears the line at the prompt; Ctrl+L keeps the prompt", async () => {
  const u = boot();
  u.send({ t: "out", run: 0, s: "a\n" });
  u.send({ t: "prompt", run: 0, s: "> " });
  u.ids.in.value = "half"; key(u, "c", { ctrlKey: true });
  assert.strictEqual(u.ids.in.value, "");
  assert.strictEqual(u.api("/api/stop").length, 0);
  key(u, "l", { ctrlKey: true });
  assert.deepStrictEqual(u.lines(), []);
  assert.strictEqual(u.ids.prompt.textContent, "> ");
  u.send({ t: "start", run: 1, kind: "script", title: "p" });
  key(u, "c", { ctrlKey: true }); await u.tick();
  assert.strictEqual(u.api("/api/stop").length, 1);
});

test("clear event wipes the screen including the prompt", () => {
  const u = boot();
  u.send({ t: "out", run: 0, s: "a\n" });
  u.send({ t: "prompt", run: 0, s: "> " });
  u.send({ t: "clear", run: 0 });
  assert.deepStrictEqual(u.lines(), []);
  assert.strictEqual(u.ids.prompt.textContent, "");
});

test("busy rejection from the server re-enables the prompt with a toast", async () => {
  const u = boot();
  u.send({ t: "prompt", run: 0, s: "> " });
  u.reply["/api/shell"] = { ok: false, error: "busy" };
  u.ids.in.value = "pwd"; key(u, "Enter"); await u.tick();
  assert.strictEqual(u.ids.in.disabled, false);
  assert.match(u.ids.toast.textContent, /در حال اجراست/);
});

test("English prompt flips live line to LTR; empty line keeps height", () => {
  const u = boot();
  u.send({ t: "start", run: 1, kind: "repl", title: "Python" });
  u.send({ t: "out", run: 1, s: "Enter: " });
  assert.strictEqual(u.ids.live.dir, "ltr");
  u.send({ t: "out", run: 1, s: "\n\n" });
  assert.strictEqual(u.lines()[1], "\u200b");
});

test("carriage return overwrites the live line; ANSI colours become classes", () => {
  const u = boot();
  u.send({ t: "start", run: 1, kind: "script", title: "p" });
  u.send({ t: "out", run: 1, s: "10%\r50%\r100%\n\x1b[31mred\x1b[0m\n" });
  assert.deepStrictEqual(u.lines(), ["100%", "red"]);
  assert.ok(has(u.ids.screen.children[1].children[0], "fg1"));
});

test("Persian digits option converts program output but never prompt or typed text", async () => {
  const u = boot();
  await u.tick();                                                     // let the server's saved settings arrive first
  u.ids.optFa.onchange({ target: { checked: true } });
  assert.deepStrictEqual(u.api("/api/settings").filter((c) => c[1]).pop()[1], { patch: { faDigits: true } });
  u.send({ t: "prompt", run: 0, s: "~/p1> " });
  u.ids.in.value = "run a1.py"; key(u, "Enter"); await u.tick();
  u.send({ t: "start", run: 1, kind: "script", title: "d" });
  u.send({ t: "out", run: 1, s: "جمع: 42\n" });
  assert.deepStrictEqual(u.lines(), ["~/p1> run a1.py", "جمع: ۴۲"]);
});

test("regression: a run started by a button/drop (prompt never frozen) must not tag the first output line as meta", async () => {
  const u = boot({ search: "?t=TOK&m=result" });
  await u.tick();
  u.send({ t: "prompt", run: 0, s: "~> " });                          // prompt visible, user never pressed Enter
  u.send({ t: "start", run: 1, kind: "script", title: "p.py" });      // started from the toolbar / by dropping a file
  u.send({ t: "out", run: 1, s: "FIRST LINE\n" });
  assert.deepStrictEqual(u.lines(), ["FIRST LINE"]);
  assert.deepStrictEqual(u.nodes().map((n) => has(n, "meta")), [false]);
  u.send({ t: "out", run: 0, s: "a.py\n", ltr: true });
  u.send({ t: "start", run: 2, kind: "script", title: "q.py" });
  u.send({ t: "out", run: 2, s: "x\n" });
  assert.strictEqual(u.nodes().pop().dir, "auto");                    // and the ltr flag does not leak either
});
