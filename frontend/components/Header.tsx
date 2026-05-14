import { formatRaceDay, formatWallTime } from "@/lib/format";

interface HeaderProps {
  raceStart: string;
  lastReplan: string | null;
}

export function Header({ raceStart, lastReplan }: HeaderProps) {
  return (
    <header className="flex items-center justify-between pb-4 mb-6 border-b border-[var(--color-border)]">
      <div className="flex items-center gap-3 text-[11px] tracking-[0.14em] uppercase text-[var(--color-muted)] font-medium">
        <span className="inline-block w-1.5 h-1.5 rounded-full bg-[var(--color-accent)] shadow-[0_0_8px_rgba(245,166,35,0.6)]" />
        <span className="text-[var(--color-text)] font-medium">24h-OL Thüringen 2026</span>
        <span>· Heyda</span>
      </div>
      <div className="flex items-center gap-5">
        <span className="inline-flex items-center gap-1.5 text-[10px] tracking-[0.14em] uppercase text-[var(--color-accent)]">
          <span className="w-1.5 h-1.5 rounded-full bg-[var(--color-accent)] shadow-[0_0_8px_rgba(245,166,35,0.7)] pulse-glow" />
          Live
        </span>
        <span className="text-[11px] tracking-[0.08em] uppercase text-[var(--color-muted)]">
          {formatRaceDay(raceStart)}
          {lastReplan ? ` · Letzte Planung ${formatWallTime(lastReplan)}` : ""}
        </span>
      </div>
    </header>
  );
}
