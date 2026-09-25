export function fmtDate(value?: string | null, opts: Intl.DateTimeFormatOptions = {}) {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString(undefined, { day: "2-digit", month: "short", year: "numeric", ...opts });
}

export function fmtDateTime(value?: string | null) {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString(undefined, { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}

export function timeAgo(value?: string | null) {
  if (!value) return "—";
  const secs = Math.round((Date.now() - new Date(value).getTime()) / 1000);
  if (secs < 45) return "just now";
  const mins = Math.round(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.round(hrs / 24);
  return days < 30 ? `${days}d ago` : fmtDate(value);
}

export function fmtBytes(n: number) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

export function fmtPeriod(period?: string | null) {
  if (!period) return "—";
  const [y, m] = period.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, 2)).toLocaleString(undefined, { month: "long", year: "numeric" });
}

export function fmtHours(n?: number | null) {
  if (n == null) return "";
  return Number.isInteger(n) ? String(n) : n.toFixed(1);
}
