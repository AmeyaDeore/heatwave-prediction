/**
 * Date and time display. Times are shown in the viewer's local time zone with an explicit
 * 24-hour clock ("09 Oct, 14:05"), because officials compare them against field reports.
 */

const timeFmt = new Intl.DateTimeFormat("en-IN", {
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});
const dateTimeFmt = new Intl.DateTimeFormat("en-IN", {
  day: "2-digit",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});
const dateFmt = new Intl.DateTimeFormat("en-IN", {
  weekday: "short",
  day: "2-digit",
  month: "short",
});
const relativeFmt = new Intl.RelativeTimeFormat("en", { numeric: "auto" });

function toDate(value: string | number | Date): Date {
  return value instanceof Date ? value : new Date(value);
}

export function formatTime(value: string | number | Date): string {
  return timeFmt.format(toDate(value));
}

export function formatDateTime(value: string | number | Date): string {
  return dateTimeFmt.format(toDate(value));
}

/** A forecast's valid date ("Fri, 09 Oct"). API dates are calendar dates, not instants. */
export function formatCalendarDate(isoDate: string): string {
  const [y, m, d] = isoDate.split("-").map(Number);
  return dateFmt.format(new Date(y ?? 1970, (m ?? 1) - 1, d ?? 1));
}

/** "just now", "2 min ago", "3 hours ago". */
export function formatRelative(value: string | number | Date, now: number = Date.now()): string {
  const seconds = Math.round((toDate(value).getTime() - now) / 1_000);
  const abs = Math.abs(seconds);
  if (abs < 45) return "just now";
  if (abs < 3_600) return relativeFmt.format(Math.round(seconds / 60), "minute");
  if (abs < 86_400) return relativeFmt.format(Math.round(seconds / 3_600), "hour");
  return relativeFmt.format(Math.round(seconds / 86_400), "day");
}

/** "Next 1–3 Days" style label for the short-term horizon (CLAUDE.md: 1–3 day predictions). */
export function forecastLabel(leadDays: number): string {
  if (leadDays === 0) return "Today";
  if (leadDays === 1) return "Tomorrow";
  return `In ${leadDays} days`;
}

const fullDateFmt = new Intl.DateTimeFormat("en-IN", {
  day: "2-digit",
  month: "short",
  year: "numeric",
});

/** A historical calendar date with its year ("22 May 2010"): for records spanning decades. */
export function formatHistoricDate(isoDate: string): string {
  const [y, m, d] = isoDate.split("-").map(Number);
  return fullDateFmt.format(new Date(y ?? 1970, (m ?? 1) - 1, d ?? 1));
}
