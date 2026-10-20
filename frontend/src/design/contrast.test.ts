/**
 * Every text/background token pair meets WCAG AA (4.5:1) in both themes (Part 10 §5: sufficient
 * contrast on coloured badges). Reads the real globals.css, so editing a colour that breaks
 * contrast fails this test.
 */
/// <reference types="node" />
// Read from disk: with `css: false` in the Vitest config, CSS imports (even ?raw) are empty.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const css = readFileSync(resolve(__dirname, "../styles/globals.css"), "utf8");

function block(selector: string): Record<string, string> {
  const start = css.indexOf(`${selector} {`);
  if (start < 0) throw new Error(`No ${selector} block in globals.css`);
  const body = css.slice(start, css.indexOf("}", start));
  const vars: Record<string, string> = {};
  for (const m of body.matchAll(/--([\w-]+):\s*([^;]+);/g)) vars[m[1]!] = m[2]!.trim();
  return vars;
}

function oklchToLinearRgb(value: string): [number, number, number] {
  const m = value.match(/oklch\(\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*\)/);
  if (!m) throw new Error(`Not an oklch() colour: ${value}`);
  const [L, C, H] = [Number(m[1]), Number(m[2]), (Number(m[3]) * Math.PI) / 180];
  const a = C * Math.cos(H);
  const b = C * Math.sin(H);
  const l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3;
  const mm = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3;
  const s = (L - 0.0894841775 * a - 1.291485548 * b) ** 3;
  const clamp = (x: number) => Math.min(1, Math.max(0, x));
  return [
    clamp(4.0767416621 * l - 3.3077115913 * mm + 0.2309699292 * s),
    clamp(-1.2684380046 * l + 2.6097574011 * mm - 0.3413193965 * s),
    clamp(-0.0041960863 * l - 0.7034186147 * mm + 1.707614701 * s),
  ];
}

function luminance(value: string): number {
  const [r, g, b] = oklchToLinearRgb(value);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(fg: string, bg: string): number {
  const [hi, lo] = [luminance(fg), luminance(bg)].sort((x, y) => y - x) as [number, number];
  return (hi + 0.05) / (lo + 0.05);
}

const TONES = ["success", "warning", "danger", "info", "neutral"];
const PAIRS: [string, string][] = [
  ["foreground", "background"],
  ["card-foreground", "card"],
  ["muted-foreground", "background"],
  ["muted-foreground", "card"],
  ["primary-foreground", "primary"],
  ["secondary-foreground", "secondary"],
  ["nav-foreground", "nav"],
  ["nav-muted", "nav"],
  ["nav-foreground", "nav-accent"],
  ...TONES.flatMap((t): [string, string][] => [
    [`tone-${t}-fg`, `tone-${t}`], // solid badges, banners
    [`tone-${t}-subtle-fg`, `tone-${t}-subtle`], // subtle badges, pills, tags
    [`tone-${t}-subtle-fg`, "card"], // toned text on cards (deltas, factor shares)
  ]),
];

describe.each([
  ["light", block(":root")],
  ["dark", { ...block(":root"), ...block(".dark") }],
])("%s theme", (_theme, vars) => {
  it.each(PAIRS)("%s on %s meets WCAG AA (4.5:1)", (fg, bg) => {
    const ratio = contrast(vars[fg]!, vars[bg]!);
    expect(ratio, `${fg} on ${bg} = ${ratio.toFixed(2)}`).toBeGreaterThanOrEqual(4.5);
  });

  it("separates the three risk colours from each other", () => {
    // Not a WCAG rule: a sanity check that Normal/Heatwave/Severe never collapse to one colour.
    const solids = ["success", "warning", "danger"].map((t) => vars[`tone-${t}`]);
    expect(new Set(solids).size).toBe(3);
  });
});

describe("risk semantics", () => {
  it("aliases each risk class to exactly one tone", () => {
    const risk = block(":root,\n.dark");
    expect(risk["risk-normal"]).toBe("var(--tone-success)");
    expect(risk["risk-heatwave"]).toBe("var(--tone-warning)");
    expect(risk["risk-severe"]).toBe("var(--tone-danger)");
    expect(risk["brand-accent"]).toBe("var(--tone-danger)");
  });
});
