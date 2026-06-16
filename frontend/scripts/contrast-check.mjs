// WCAG 2.1 contrast checker for the design tokens. Run: node scripts/contrast-check.mjs
// AA: normal text >= 4.5, large text (>=18.66px bold / 24px) and UI graphics >= 3.0.
const T = {
  canvas: "#eef1f5",
  surface: "#ffffff",
  surface2: "#f6f8fb",
  ink: "#0f1729",
  muted: "#515c6e",
  faint: "#69727f",
  line: "#d7dce5",
  lineStrong: "#c2c9d6",
  brand: "#1b3a6b",
  brandSoft: "#e7eefb",
  pass: "#15663f",
  passSoft: "#e3f3ea",
  passSolid: "#1f7a4d",
  flag: "#8a5200",
  flagSoft: "#fbf0d6",
  flagSolid: "#9a5b00",
  fail: "#b21f12",
  failSoft: "#fbe8e6",
  failSolid: "#c1271b",
  white: "#ffffff",
};

function lin(c) {
  const s = c / 255;
  return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
}
function L(hex) {
  const n = parseInt(hex.slice(1), 16);
  const r = (n >> 16) & 255, g = (n >> 8) & 255, b = n & 255;
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
}
function ratio(a, b) {
  const la = L(T[a]), lb = L(T[b]);
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}

// [fg, bg, minimum] — minimum 4.5 for normal body text, 3.0 for large text / UI graphics.
const PAIRS = [
  ["ink", "canvas", 4.5], ["ink", "surface", 4.5], ["ink", "surface2", 4.5],
  ["muted", "canvas", 4.5], ["muted", "surface", 4.5], ["muted", "surface2", 4.5],
  ["faint", "surface", 3.0], ["faint", "canvas", 3.0],
  ["brand", "surface", 4.5], ["brand", "brandSoft", 4.5], ["brand", "canvas", 4.5],
  ["white", "brand", 4.5],
  ["pass", "passSoft", 4.5], ["pass", "surface", 4.5],
  ["flag", "flagSoft", 4.5], ["flag", "surface", 4.5],
  ["fail", "failSoft", 4.5], ["fail", "surface", 4.5],
  ["white", "passSolid", 4.5], ["white", "failSolid", 4.5], ["white", "flagSolid", 4.5],
];
// Note: hairline borders (--color-line / --color-line-strong) are decorative and intentionally
// excluded — verdict/status are always conveyed by a chip with a text label + color (never by a
// border alone), and focus uses a 2px ring, so the WCAG 3:1 "UI component" rule does not apply.

let fails = 0;
for (const [fg, bg, min] of PAIRS) {
  const r = ratio(fg, bg);
  const ok = r >= min;
  if (!ok) fails++;
  console.log(`${ok ? "PASS" : "FAIL"}  ${r.toFixed(2)} (need ${min})  ${fg} on ${bg}`);
}
console.log(fails ? `\n${fails} pair(s) below target` : "\nAll pairs meet WCAG AA targets");
process.exit(fails ? 1 : 0);
