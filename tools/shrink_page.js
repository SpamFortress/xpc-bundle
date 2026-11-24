// Release-time tool: shrink page.canvas.tsx (readable design source) into page.min.tsx (what the canvas holds).
// Keeps TypeScript types (the canvas type-checks in strict mode). Only drops comments and insignificant
// whitespace, rewrites JSX text to its exact rendered form, minifies the CSS block, and dedupes repeated
// theme-only inline style objects. Requires: npm i typescript esbuild (dev only; bots never run this).
// Usage: node tools/shrink_page.js page.canvas.tsx page.min.tsx
const path = require("path");
const fs = require("fs");
const req = (m) => { try { return require(m); } catch { return require(path.join(process.env.XPC_NODE_TOOLS || "/workspace/x-post-cleaner/node-tools", "node_modules", m)); } };
const ts = req("typescript");
const esbuild = req("esbuild");
const [, , inp, out] = process.argv;
const src = fs.readFileSync(inp, "utf8");

function jsxClean(value) {
  const lines = value.split(/\r\n|\n|\r/);
  let lastNonEmpty = 0;
  lines.forEach((l, i) => { if (/[^ \t]/.test(l)) lastNonEmpty = i; });
  let str = "";
  lines.forEach((line, i) => {
    let t = line.replace(/\t/g, " ");
    if (i !== 0) t = t.replace(/^[ ]+/, "");
    if (i !== lines.length - 1) t = t.replace(/[ ]+$/, "");
    if (t) { if (i !== lastNonEmpty) t += " "; str += t; }
  });
  return str;
}

// 1. token re-emit
function tokenMinify(text) {
  const sf = ts.createSourceFile("p.tsx", text, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const toks = [];
  (function walk(n) {
    if (n.kind >= ts.SyntaxKind.FirstJSDocNode && n.kind <= ts.SyntaxKind.LastJSDocNode) return;
    if (n.kind === ts.SyntaxKind.JsxText) { toks.push({ jsx: true, start: n.pos, end: n.end, text: jsxClean(text.slice(n.pos, n.end)) }); return; }
    const kids = n.getChildren(sf);
    if (kids.length === 0) {
      if (n.kind === ts.SyntaxKind.EndOfFileToken) return;
      const st = n.getStart(sf);
      toks.push({ jsx: false, start: st, end: n.end, text: text.slice(st, n.end) });
      return;
    }
    kids.forEach(walk);
  })(sf);
  const idc = /[A-Za-z0-9_$\u0080-\uffff]/;
  let outS = "";
  let prev = null;
  for (const t of toks) {
    if (t.jsx && t.text === "") { continue; }
    if (prev) {
      const gap = text.slice(prev.end, t.start);
      if (gap.length > 0 && !prev.jsx && !t.jsx) {
        const a = outS[outS.length - 1], b = t.text[0];
        const need = (idc.test(a) && idc.test(b)) || (a === "+" && b === "+") || (a === "-" && b === "-") ||
          (a === "/" && (b === "/" || b === "*")) || ((a === '"' || a === "'" || a === "}" || a === "`") && idc.test(b)) ||
          (/[0-9]/.test(a) && b === ".");
        if (need) outS += " ";
      }
    }
    outS += t.text;
    prev = t;
  }
  return outS;
}

// 2. CSS block inside <style>{`...`}</style> (no ${} and no quotes in it; checked)
function cssMinify(s) {
  let out = "", i = 0;
  while (true) {
    const a = s.indexOf("<style>{`", i);
    if (a < 0) return out + s.slice(i);
    const b = s.indexOf("`}</style>", a);
    if (b < 0) throw new Error("unclosed style");
    const css = s.slice(a + 9, b);
    if (/\$\{|["'\\]|\/\*/.test(css)) throw new Error("css block has interpolation, quotes, escapes or comments; refusing");
    const m = css.replace(/\s+/g, " ").replace(/ ?([{};]) ?/g, "$1").replace(/;}/g, "}").trim();
    out += s.slice(i, a + 9) + m;
    i = b;
  }
}

// 3. dedupe repeated theme-only style objects inside App
function dedupe(s) {
  const anchor = "export default function App(){const theme=useGrokTheme();";
  const at = s.indexOf(anchor);
  if (at < 0) throw new Error("App anchor not found");
  const head = s.slice(0, at + anchor.length), body = s.slice(at + anchor.length);
  const counts = new Map();
  for (const m of body.matchAll(/style=\{\{([^{}]*)\}\}/g)) {
    const inner = m[1];
    const ids = inner.replace(/"[^"]*"/g, "").match(/[A-Za-z_$][\w$]*/g) || [];
    // every identifier must be a property key (followed by ':') or part of theme.x.y
    const ok = !/\.\.\./.test(inner) && inner.split(",").every((kv) => /^[A-Za-z]+:("[^"]*"|-?[0-9.]+|theme(\.[A-Za-z0-9]+)+)$/.test(kv));
    if (ok) counts.set(inner, (counts.get(inner) || 0) + 1);
  }
  const picks = [...counts.entries()].filter(([k, n]) => n >= 2 && (n - 1) * (k.length + 4) > k.length + 24).sort((x, y) => y[1] * y[0].length - x[1] * x[0].length);
  let defs = "", b2 = body;
  picks.forEach(([inner], i) => {
    const name = `_s${i}`;
    if (new RegExp(`\\b${name}\\b`).test(s)) throw new Error("name clash " + name);
    defs += `const ${name}:CSSProperties={${inner}};`;
    b2 = b2.split(`style={{${inner}}}`).join(`style={${name}}`);
  });
  return { text: head + defs + b2, picks: picks.map(([k, n], i) => ({ name: `_s${i}`, uses: n, style: k })) };
}
function undedupe(s, picks) {
  for (const p of picks) {
    s = s.replace(`const ${p.name}:CSSProperties={${p.style}};`, "");
    s = s.split(`style={${p.name}}`).join(`style={{${p.style}}}`);
  }
  return s;
}

function jsOf(code) {
  return esbuild.transformSync(code, { loader: "tsx", jsx: "transform", minifyWhitespace: true, charset: "utf8", format: "esm" }).code;
}

const step1 = tokenMinify(src);
if (jsOf(step1) !== jsOf(src)) throw new Error("token minify changed the compiled output");
const step2 = cssMinify(step1);
const { text: step3, picks } = dedupe(step2);
if (undedupe(step3, picks) !== step2) throw new Error("dedupe is not reversible");
if (jsOf(step3).length === 0) throw new Error("empty");
for (const bad of ["\n//~", "\n//=", "@@", "\u2028", "\u2029", "\r"]) if (step3.includes(bad)) throw new Error("min source contains reserved sequence " + JSON.stringify(bad));
fs.writeFileSync(out, step3);
const B = (x) => Buffer.byteLength(x);
console.log(JSON.stringify({ source: B(src), tokens_and_jsx_text: B(step1), css: B(step2), deduped: B(step3), dedupe_styles: picks.length, compiled_output_identical_after_token_pass: true, dedupe_reversible: true }));
