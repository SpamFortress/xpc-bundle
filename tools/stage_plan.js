// Release-time tool: choose what the FIRST page leaves out, from page.min.tsx, by rule (not by hand).
// Writes page/regions.json: spans of page.min.tsx that the first page replaces with a stub.
//  - JSX children for the Review and Run steps and the archive-only post list (not shown before the archive loads)
//  - two expressions that keep Review locked on the first page (stepper lock, and the Pick "Next" button)
//  - every module-level or App-level declaration that nothing left on the first page uses (found with the TypeScript checker)
// Usage: node tools/stage_plan.js page.min.tsx page/regions.json
const path = require("path"), fs = require("fs");
const req = (m) => { try { return require(m); } catch { return require(path.join(process.env.XPC_NODE_TOOLS || "/workspace/x-post-cleaner/node-tools", "node_modules", m)); } };
const ts = req("typescript");
const [, , inp, out] = process.argv;
const text = fs.readFileSync(inp, "utf8");
const STUB_DTS = `declare module "grok/canvas" { export type { CSSProperties, ReactNode } from "react"; export { Fragment, useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react"; type C = (props: any) => any; export const Page: C, Section: C, Text: C, Callout: C, Select: C, Input: C, Button: C, Toggle: C, Table: C, Rows: C, Properties: C, BulletList: C, Status: C, Segmented: C, Floating: C, BackToTop: C, TextLink: C; export function useGrokTheme(): any; }`;
const files = { "/p/page.tsx": text, "/p/grok.d.ts": STUB_DTS };
const opts = { strict: true, noEmit: true, jsx: ts.JsxEmit.Preserve, module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022, moduleResolution: ts.ModuleResolutionKind.Bundler, skipLibCheck: true, types: [], lib: ["lib.es2022.d.ts", "lib.dom.d.ts"] };
const host = ts.createCompilerHost(opts);
const og = host.getSourceFile.bind(host);
host.getSourceFile = (f, l) => files[f] !== undefined ? ts.createSourceFile(f, files[f], l, true, f.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS) : og(f, l);
host.fileExists = (f) => files[f] !== undefined || ts.sys.fileExists(f);
host.readFile = (f) => files[f] !== undefined ? files[f] : ts.sys.readFile(f);
const reactTypes = path.join(path.dirname(require.resolve ? (() => { try { return req.resolve; } catch { return null; } })() || "" : ""), "");
opts.typeRoots = [path.join(process.env.XPC_NODE_TOOLS || "/workspace/x-post-cleaner/node-tools", "node_modules", "@types")]; opts.types = ["react"];
const program = ts.createProgram(["/p/page.tsx", "/p/grok.d.ts"], opts, host);
const sf = program.getSourceFile("/p/page.tsx");
const checker = program.getTypeChecker();

// forced regions. phase "A" = the Pick screen (built first in the background), "B" = Review and Run.
const forced = [];
let app = null;
sf.statements.forEach((s) => { if (ts.isFunctionDeclaration(s) && s.name && s.name.text === "App") app = s; });
if (!app) throw new Error("App not found");
(function walk(n) {
  if (ts.isJsxExpression(n) && n.expression && ts.isBinaryExpression(n.expression) && n.expression.operatorToken.kind === ts.SyntaxKind.AmpersandAmpersandToken) {
    const left = n.expression.left.getText(sf), right = n.expression.right.getText(sf);
    let phase = null;
    if (left === 'step==="pick"' || left === "SHOW_SIGNIN_DETAILS" || left === "SHOW_WHERE_DATA" || left === "SHOW_LIVE_COUNTS") phase = "A";
    else if (left === "SHOW_NEXT_BAR") phase = "B";
    else if (left === 'step==="review"' || left === 'step==="run"' || (left === "archiveReady" && right.includes('id="pick-posts"'))) phase = "B";
    if (phase) { forced.push({ start: n.getStart(sf), end: n.end, kind: "jsx", phase, stub: "{null", tail: "}", why: left }); return; }
  }
  ts.forEachChild(n, walk);
})(app.body);
function exprRegion(exact, from, len, stub, phase, kind, why) {
  const i = text.indexOf(exact);
  if (i < 0 || text.indexOf(exact, i + 1) >= 0) throw new Error("anchor not unique: " + exact);
  forced.push({ start: i + from, end: i + from + len, kind, phase, stub, tail: "", why });
}
// Review stays locked until the full page is verified; Pick until phase A is verified.
exprRegion('id==="run"&&runPhase==="idle"', 0, 'id==="run"&&runPhase==="idle"'.length, '(id==="run"||id==="review")', "B", "expr", "stepper: Review locked");
exprRegion('disabled={locked}', 'disabled={'.length, "locked".length, 'locked||id==="pick"', "A", "expr", "stepper: Pick locked");
exprRegion('disabled:!rulesActive', 'disabled:'.length, '!rulesActive'.length, "true", "B", "expr", "Pick Next button off");
{ const t = 'if(step==="archive"){if(phase==="choose")return null;'; const i = text.indexOf(t); if (i < 0) throw new Error("archive anchor");
  const j = text.indexOf("}", text.indexOf('return{label:"Next: choose what goes →",action:()=>goStep("pick")};return{', i) + 60) ; // end of if-block
  const blockEnd = text.indexOf("};}", i) + 3;
  forced.push({ start: i, end: blockEnd, kind: "stmt", phase: "A", stub: 'if(step==="archive")return null;', tail: "", why: "archive Next hidden until Pick is built" }); }

// Post-only helpers: on the first page POOL is empty, so functions that take a single post are never called and
// computeVerdicts only ever sees an empty pool. Their bodies are stubbed until phase B; the bot never loads posts
// into the page before the full page is verified.
sf.statements.forEach((s) => {
  if (!ts.isFunctionDeclaration(s) || !s.body || !s.name) return;
  const p0 = s.parameters[0];
  const t0 = p0 && p0.type ? p0.type.getText(sf) : "";
  let stub = null;
  if (t0 === "Post") stub = "{return null as any";
  else if (t0 === "Post[]" && s.name.text === "computeVerdicts") stub = "{return new Map()";
  if (stub) forced.push({ start: s.body.getStart(sf), end: s.body.end, kind: "body", phase: "B", stub, tail: "}", why: "post-only body: " + s.name.text });
});

// Page 1 keeps the archive view, stepper, styles, and status. The counts sidebar,
// section rail, and mobile next bar come back in phase A so the first write stays small.
function pushElement(classFrag, phase, why) {
  function walk(n) {
    if (ts.isJsxOpeningElement(n) || ts.isJsxSelfClosingElement(n)) {
      if (n.getText(sf).includes(classFrag)) {
        const el = n.parent;
        if (el && el.getStart && el.end > el.getStart(sf)) {
          forced.push({ start: el.getStart(sf), end: el.end, kind: "jsx", phase, stub: "{null", tail: "}", why });
          return;
        }
      }
    }
    ts.forEachChild(n, walk);
  }
  walk(app.body);
}
pushElement('className="xpc-rail"', "A", "section rail");
pushElement('className="xpc-summary"', "B", "live counts sidebar");
app.body.statements.forEach((s) => {
  const raw = s.getText(sf);
  if (raw.startsWith("useEffect") && raw.includes("railItems.map")) {
    forced.push({ start: s.getStart(sf), end: s.end, kind: "stmt", phase: "A", stub: "", tail: "", why: "rail scroll effect" });
  }
  if (raw.startsWith("const totalsRows") || raw.startsWith("if(!LOADED_TOTALS)") || raw.startsWith("if (!LOADED_TOTALS)") || raw.startsWith("totalsRows.push") || (raw.startsWith("useEffect") && raw.includes("setWipeConfirm"))) {
    forced.push({ start: s.getStart(sf), end: s.end, kind: "stmt", phase: "B", stub: "", tail: "", why: raw.slice(0, 48) });
  }
  if (raw.startsWith("useEffect") && (raw.includes("setNarrow") || raw.includes("scrollPageTop"))) {
    forced.push({ start: s.getStart(sf), end: s.end, kind: "stmt", phase: "A", stub: "", tail: "", why: "layout effect" });
  }
});
const verdictHelpers = new Set(["isStrongKeep", "threadGroupKey", "scopeParts", "explicitKeep", "computeVerdicts"]);
sf.statements.forEach((s) => {
  if (ts.isFunctionDeclaration(s) && s.name && verdictHelpers.has(s.name.text)) {
    forced.push({ start: s.getStart(sf), end: s.end, kind: "stmt", phase: "A", stub: "", tail: "", why: "verdict helper " + s.name.text });
  }
});
const forcedKept = forced.filter((f) => !forced.some((o) => o !== f && o.start <= f.start && o.end >= f.end && (o.start < f.start || o.end > f.end)));
forced.length = 0;
forcedKept.forEach((f) => forced.push(f));

// candidate statements
const cands = [];
const isCand = (s) => ts.isVariableStatement(s) || ts.isFunctionDeclaration(s) || ts.isTypeAliasDeclaration(s) || ts.isInterfaceDeclaration(s);
sf.statements.forEach((s) => { if (s !== app && isCand(s)) cands.push(s); });
app.body.statements.forEach((s) => { if (isCand(s)) cands.push(s); });
const declSym = new Map(); // symbol -> cand index
const nameNodes = new Set();
cands.forEach((s, i) => {
  const names = [];
  if (ts.isVariableStatement(s)) s.declarationList.declarations.forEach((d) => (function bn(b) { if (ts.isIdentifier(b)) names.push(b); else b.elements.forEach((e) => { if (!ts.isOmittedExpression(e)) bn(e.name); }); })(d.name));
  else if (s.name) names.push(s.name);
  names.forEach((nm) => { nameNodes.add(nm); const sym = checker.getSymbolAtLocation(nm); if (sym) declSym.set(sym, i); });
});
const removedIn = (phases) => forced.filter((r) => phases.includes(r.phase));
function keptSet(phases) {
  const rem = removedIn(phases);
  const unitOf = (pos) => {
    for (const r of rem) if (pos >= r.start && pos < r.end) return "x";
    for (let i = cands.length - 1; i >= 0; i--) if (pos >= cands[i].getStart(sf) && pos < cands[i].end) return i;
    return "root";
  };
  const edges = new Map();
  for (const [pos, c] of refs) { const u = unitOf(pos); if (u === "x") continue; if (!edges.has(u)) edges.set(u, new Set()); edges.get(u).add(c); }
  const kept = new Set(); const stack = [...(edges.get("root") || [])];
  while (stack.length) { const c = stack.pop(); if (kept.has(c)) continue; kept.add(c); for (const d of edges.get(c) || []) stack.push(d); }
  return kept;
}
const refs = [];
(function walk(n) {
  if (ts.isIdentifier(n) && !nameNodes.has(n)) {
    const sym = ts.isShorthandPropertyAssignment(n.parent) && n.parent.name === n ? checker.getShorthandAssignmentValueSymbol(n.parent) : checker.getSymbolAtLocation(n);
    if (sym && declSym.has(sym)) refs.push([n.getStart(sf), declSym.get(sym)]);
  }
  ts.forEachChild(n, walk);
})(sf);
const keptStage1 = keptSet(["A", "B"]), keptAfterA = keptSet(["B"]);
let regions = [];
cands.forEach((s, i) => { if (!keptStage1.has(i)) regions.push({ start: s.getStart(sf), end: s.end, kind: "stmt", phase: keptAfterA.has(i) ? "A" : "B", stub: "", tail: "", why: (s.name && s.name.text) || s.getText(sf).slice(0, 40) }); });
const inside = (r, o) => r.start >= o.start && r.end <= o.end;
regions = regions.filter((s) => !forced.some((f) => inside(s, f)));
regions = regions.concat(forced.filter((f) => !regions.some((s) => inside(f, s))));
const candRegion = new Map();
cands.forEach((s, i) => {
  const hit = regions.find((r) => r.start === s.getStart(sf) && r.end === s.end);
  if (hit) candRegion.set(i, hit);
});
let promoted = true;
while (promoted) {
  promoted = false;
  for (const [pos, target] of refs) {
    const host = regions.find((r) => pos >= r.start && pos < r.end);
    if (!host || host.phase !== "A") continue;
    const dest = candRegion.get(target);
    if (dest && dest.phase === "B") { dest.phase = "A"; promoted = true; }
  }
}
regions.sort((a, b) => a.start - b.start);
const merged = [];
for (const r of regions) {
  const last = merged[merged.length - 1];
  if (last && last.kind === "stmt" && r.kind === "stmt" && last.stub === "" && r.stub === "" && last.phase === r.phase && last.end === r.start) { last.end = r.end; last.why += "," + r.why; }
  else merged.push({ ...r });
}
for (let i = 1; i < merged.length; i++) if (merged[i].start < merged[i - 1].end) throw new Error("overlapping regions at " + merged[i].why);
const bytes = (rs) => rs.reduce((a, r) => a + Buffer.byteLength(text.slice(r.start, r.end)), 0);
const cp = (i) => [...text.slice(0, i)].length;
fs.writeFileSync(out, JSON.stringify({ source: "page.min.tsx", regions: merged.map((r) => ({ start: cp(r.start), end: cp(r.end), kind: r.kind, phase: r.phase, stub: r.stub, tail: r.tail, why: r.why })) }, null, 1) + "\n");
console.log(JSON.stringify({ regions: merged.length, phaseA_bytes: bytes(merged.filter((r) => r.phase === "A")), phaseB_bytes: bytes(merged.filter((r) => r.phase === "B")), first_page_kept_bytes: Buffer.byteLength(text) - bytes(merged) }));
