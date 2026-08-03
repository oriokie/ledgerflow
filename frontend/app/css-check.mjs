/* Brace-balance + orphan-declaration check across every stylesheet. */
import { readFileSync, readdirSync } from "node:fs";
const dir = "src/styles";
let bad = 0;
for (const f of readdirSync(dir).filter((n) => n.endsWith(".css"))) {
  const src = readFileSync(`${dir}/${f}`, "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
  let depth = 0, line = 1, err = null;
  for (let i = 0; i < src.length; i++) {
    const c = src[i];
    if (c === "\n") line++;
    else if (c === "{") depth++;
    else if (c === "}") { depth--; if (depth < 0 && !err) err = `unbalanced } at line ${line}`; }
  }
  if (depth !== 0 && !err) err = `${depth > 0 ? "unclosed" : "extra"} braces (depth ${depth})`;
  // A declaration at depth 0 means an orphan left outside any rule.
  const orphan = src.split("\n").findIndex((l, idx) => {
    const before = src.split("\n").slice(0, idx).join("\n");
    const d = (before.match(/{/g) || []).length - (before.match(/}/g) || []).length;
    return d === 0 && /^\s+[a-z-]+\s*:\s*[^;{]+;\s*$/.test(l);
  });
  if (orphan >= 0 && !err) err = `orphaned declaration at line ${orphan + 1}`;
  if (err) { console.log(`FAIL ${f}: ${err}`); bad++; }
}
console.log(bad === 0 ? `OK — all stylesheets parse cleanly` : `${bad} file(s) with problems`);
process.exit(bad ? 1 : 0);
