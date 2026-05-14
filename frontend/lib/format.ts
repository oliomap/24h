/** German-locale formatting helpers for the dashboard. */

const TZ = "Europe/Berlin";

/** "HH:MM" same-day, "So HH:MM" Sunday of the race. raceStart anchors the day. */
export function formatRaceTime(iso: string, raceStart: string): string {
  const dt = new Date(iso);
  const start = new Date(raceStart);
  const hhmm = dt.toLocaleTimeString("de-DE", {
    hour: "2-digit",
    minute: "2-digit",
    timeZone: TZ,
  });
  if (dt.toDateString() === start.toDateString()) return hhmm;
  return `So ${hhmm}`;
}

export function formatDurationMin(value: number | null | undefined): string {
  if (value == null) return "—";
  if (value >= 100) return value.toFixed(0);
  return value.toFixed(1).replace(".", ",");
}

/** "2h 47m" or "47m" */
export function formatHM(totalMinutes: number): string {
  const sign = totalMinutes < 0 ? "−" : "";
  const m = Math.abs(Math.round(totalMinutes));
  const h = Math.floor(m / 60);
  const mm = m % 60;
  if (h === 0) return `${sign}${mm}m`;
  return `${sign}${h}h ${mm.toString().padStart(2, "0")}m`;
}

/** "+18 Min" / "−12 Min" */
export function formatSlack(min: number): string {
  const sign = min >= 0 ? "+" : "−";
  return `${sign}${Math.abs(Math.round(min))} Min`;
}

/** Long Saturday label like "Sa 16. Mai" */
export function formatRaceDay(iso: string): string {
  const dt = new Date(iso);
  return dt
    .toLocaleDateString("de-DE", {
      weekday: "short",
      day: "numeric",
      month: "long",
      timeZone: TZ,
    })
    .replace(",", "");
}

/** "11:47" — wall clock of last replan or last finish. */
export function formatWallTime(iso: string): string {
  return new Date(iso).toLocaleTimeString("de-DE", {
    hour: "2-digit",
    minute: "2-digit",
    timeZone: TZ,
  });
}

const TYPE_LABELS: Record<string, string> = {
  SF: "Start",
  TH: "Thema",
  E: "Tag leicht",
  H: "Tag schwer",
  ST: "Dämmer kurz",
  LT: "Dämmer lang",
  EN: "Nacht leicht",
  HN: "Nacht schwer",
  FF: "Schluss",
};

export function typeLabel(type: string): string {
  return TYPE_LABELS[type] ?? type;
}

const STATUS_LABELS: Record<string, string> = {
  planned: "geplant",
  in_progress: "läuft",
  done: "fertig",
};

export function statusLabel(status: string): string {
  return STATUS_LABELS[status] ?? status;
}
