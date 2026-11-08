const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "2026-03-31" -> "31 Mar 2026" (no locale or timezone surprises). */
export function fmtDate(iso: string): string {
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  if (!y || !m || !d) return iso;
  return `${d} ${MONTHS[m - 1]} ${y}`;
}

/** Indian digit grouping: 162736 -> "₹1,62,736". */
export function fmtInr(value: number): string {
  return `₹${value.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
}

export function safeStorageGet(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

export function safeStorageSet(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    /* storage blocked: the UI still works, it just forgets */
  }
}

export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}

/** "2026-11-08T14:02:11Z" -> "8 Nov 2026, 14:02" in the viewer's time zone. */
export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  return `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}, ${hh}:${mm}`;
}

/** "3 min ago", "5 h ago", "2 d ago". */
export function fmtAgo(iso: string | null | undefined, now: number = Date.now()): string {
  if (!iso) return "";
  const s = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000));
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
}

/** "price_tolerance.general_cap_amount" -> "General cap amount". */
export function humanKey(key: string): string {
  const tail = key.includes(".") ? key.slice(key.indexOf(".") + 1) : key;
  const words = tail.replace(/^other:/, "").replace(/[_:]+/g, " ").trim();
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : key;
}

/** A fact value as people read it: "₹500", "1 %", "Tuesday, Friday", "yes". */
export function valueText(v: {
  number?: number | null;
  unit?: string | null;
  text?: string | null;
  items?: string[] | null;
  type?: string;
}): string {
  if (v.items?.length) return v.items.join(", ");
  if (v.text) return v.text;
  if (v.number !== null && v.number !== undefined) {
    if (v.unit === "INR") return fmtInr(v.number);
    if (v.unit === "%") return `${v.number}%`;
    return `${v.number}${v.unit ? ` ${v.unit.replace(/_/g, " ")}` : ""}`;
  }
  return "";
}

export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n.toLocaleString("en-IN")} ${n === 1 ? one : many}`;
}
