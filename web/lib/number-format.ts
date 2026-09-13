/** Per-share facts are never scaled, including older SEC rows whose unit is just USD. */
export type Scale = "units" | "thousands" | "millions" | "billions";
const FACTORS: Record<Scale, number> = { units: 1, thousands: 1e3, millions: 1e6, billions: 1e9 };
export function isPerShare(unit: string | null, concept = ""): boolean {
  return !!unit?.includes("/") || /(?:Earnings|Income|Loss|Dividend|Dividends|Distribution|Distributions).*Per(?:Common|Ordinary)?Share|PerShare(?:Basic|Diluted)?$/i.test(concept);
}
export function isUnscaled(unit: string | null, concept = ""): boolean { return isPerShare(unit, concept) || /^shares$/i.test(unit ?? ""); }
export function formatFinancialValue(value: number | null, unit: string | null, scale: Scale, negative: string, concept = ""): string {
  if (value == null || !Number.isFinite(value)) return "";
  const perShare = isPerShare(unit, concept);
  const factor = isUnscaled(unit, concept) ? 1 : FACTORS[scale];
  const x = value / factor;
  const text = perShare ? Math.abs(x).toFixed(2) : Math.abs(x).toLocaleString("en-US", { maximumFractionDigits: factor === 1 ? 0 : x % 1 === 0 ? 0 : 1 });
  return x < 0 ? (negative === "minus" ? `-${text}` : `(${text})`) : text;
}
