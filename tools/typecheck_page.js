// Release check: tsc --strict with the React types, the same check the canvas tool runs.
// Usage: XPC_NODE_TOOLS=<dir with typescript and @types/react> node tools/typecheck_page.js <file.tsx>...
// Each file is checked on its own. Exit 1 if any file has a diagnostic.
const fs = require("fs");
const os = require("os");
const path = require("path");
const { spawnSync } = require("child_process");

const tools = process.env.XPC_NODE_TOOLS || "/workspace/xpc-node-tools";
const tsc = path.join(tools, "node_modules", "typescript", "bin", "tsc");
const typeRoots = path.join(tools, "node_modules", "@types");
if (!fs.existsSync(tsc)) {
  console.log("page-typecheck skipped: typescript is not installed in " + tools);
  process.exit(0);
}
const stub = `declare module "grok/canvas" { export type { CSSProperties, ReactNode } from "react"; export { Fragment, useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react"; type C = (props: any) => any; export const Page: C, Section: C, Text: C, Callout: C, Select: C, Input: C, Button: C, Toggle: C, Table: C, Rows: C, Properties: C, BulletList: C, Status: C, Segmented: C, Floating: C, BackToTop: C, TextLink: C; export function useGrokTheme(): any; }\n`;

const files = process.argv.slice(2);
if (files.length === 0) {
  console.error("usage: node tools/typecheck_page.js <file.tsx>...");
  process.exit(2);
}
let failed = false;
for (const file of files) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "xpc-tsc-"));
  const target = path.join(dir, "page.tsx");
  const dts = path.join(dir, "grok.d.ts");
  fs.copyFileSync(file, target);
  fs.writeFileSync(dts, stub);
  const r = spawnSync(process.execPath, [
    tsc, "--strict", "--noEmit", "--pretty", "false",
    "--jsx", "preserve", "--target", "es2022", "--module", "esnext",
    "--moduleResolution", "bundler", "--skipLibCheck",
    "--types", "react", "--typeRoots", typeRoots, "--lib", "es2022,dom",
    target, dts,
  ], { encoding: "utf8" });
  const out = ((r.stdout || "") + (r.stderr || "")).trim();
  const label = path.basename(file);
  if (r.status !== 0) {
    failed = true;
    console.error("FAIL " + label);
    if (out) console.error(out);
  } else {
    console.log("ok " + label);
  }
}
process.exit(failed ? 1 : 0);
