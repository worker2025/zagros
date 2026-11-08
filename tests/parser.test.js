const test = require("node:test");
const assert = require("node:assert");
const { newParseState, parse, xterm256 } = require("../src/zagros/web/console.js");

const run = (...chunks) => { const st = newParseState(); return chunks.flatMap((c) => parse(st, c)); };
const texts = (ops) => ops.filter((o) => o.k === "text").map((o) => o.s).join("");

test("plain Persian text and newline", () => {
  assert.deepStrictEqual(run("سلام\n"), [{ k: "text", s: "سلام", fg: null, bg: null, bold: false }, { k: "nl" }]);
});

test("CRLF is one newline, also when split across chunks", () => {
  assert.deepStrictEqual(run("a\r\nb").map((o) => o.k), ["text", "nl", "text"]);
  assert.deepStrictEqual(run("a\r", "\nb").map((o) => o.k), ["text", "nl", "text"]);
});

test("lone CR means overwrite current line (progress bars)", () => {
  assert.deepStrictEqual(run("10%\r20%").map((o) => o.k), ["text", "cr", "text"]);
  assert.deepStrictEqual(run("10%\r", "20%").map((o) => o.k), ["text", "cr", "text"]);
});

test("SGR colours and reset", () => {
  const ops = run("\x1b[31mred\x1b[0m plain \x1b[1;92mbold-green\x1b[m");
  assert.strictEqual(ops[0].fg, 1);
  assert.strictEqual(ops[1].fg, null);
  assert.strictEqual(ops[2].fg, 10); assert.strictEqual(ops[2].bold, true);
});

test("background and 256/true colour", () => {
  const ops = run("\x1b[44mx\x1b[38;5;196my\x1b[38;2;1;2;3mz");
  assert.strictEqual(ops[0].bg, 4);
  assert.strictEqual(ops[1].fg, "rgb(255,0,0)");
  assert.strictEqual(ops[2].fg, "rgb(1,2,3)");
});

test("escape sequence split across chunks", () => {
  const ops = run("ab\x1b[3", "1mred");
  assert.strictEqual(texts(ops), "abred");
  assert.strictEqual(ops[ops.length - 1].fg, 1);
});

test("clear screen and erase line", () => {
  assert.deepStrictEqual(run("\x1b[2J\x1b[H").map((o) => o.k), ["clear"]);
  assert.deepStrictEqual(run("\x1b[2K").map((o) => o.k), ["cr"]);
});

test("unknown CSI, OSC titles and control chars are dropped", () => {
  assert.strictEqual(texts(run("\x1b[?25lhi\x1b[?25h")), "hi");
  assert.strictEqual(texts(run("\x1b]0;title\x07after")), "after");
  assert.strictEqual(texts(run("a\x07b\x00c")), "abc");
});

test("backspace and tabs", () => {
  assert.deepStrictEqual(run("ab\b").map((o) => o.k), ["text", "bs"]);
  assert.strictEqual(texts(run("a\tb")), "a\tb");
});

test("emoji and non-BMP survive", () => {
  assert.strictEqual(texts(run("سلام 👋")), "سلام 👋");
});

test("xterm256 mapping", () => {
  assert.strictEqual(xterm256(3), 3);
  assert.strictEqual(xterm256(232), "rgb(8,8,8)");
  assert.strictEqual(xterm256(21), "rgb(0,0,255)");
});
