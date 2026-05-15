import { formatRaceDay, formatWallTime } from "@/lib/format";

interface HeaderProps {
  raceStart: string;
  lastReplan: string | null;
}

export function Header({ raceStart, lastReplan }: HeaderProps) {
  return (
    <header className="flex items-center justify-between gap-3 pb-3 sm:pb-4 mb-4 sm:mb-6 border-b border-[var(--color-border)]">
      <div className="flex items-center gap-2 sm:gap-3 text-[10px] sm:text-[11px] tracking-[0.12em] sm:tracking-[0.14em] uppercase text-[var(--color-muted)] font-medium min-w-0">
        <span className="inline-block w-1.5 h-1.5 rounded-full bg-[var(--color-accent)] shadow-[0_0_8px_rgba(245,166,35,0.6)] shrink-0" />
        <span className="text-[var(--color-text)] font-medium truncate">
          <span className="sm:hidden">24h-OL Heyda</span>
          <span className="hidden sm:inline">24h-OL Thüringen 2026</span>
        </span>
        <span className="hidden sm:inline">· Heyda</span>
      </div>
      <div className="flex items-center gap-3 sm:gap-5 shrink-0">
        <span className="inline-flex items-center gap-1.5 text-[10px] tracking-[0.14em] uppercase text-[var(--color-accent)]">
          <span className="w-1.5 h-1.5 rounded-full bg-[var(--color-accent)] shadow-[0_0_8px_rgba(245,166,35,0.7)] pulse-glow" />
          Live
        </span>
        <span className="hidden sm:inline text-[11px] tracking-[0.08em] uppercase text-[var(--color-muted)]">
          {formatRaceDay(raceStart)}
          {lastReplan ? ` · Letzte Planung ${formatWallTime(lastReplan)}` : ""}
        </span>
        {lastReplan && (
          <span className="sm:hidden text-[10px] tracking-[0.08em] uppercase text-[var(--color-muted)] tabular">
            {formatWallTime(lastReplan)}
          </span>
        )}
      </div>
    </header>
  );
}
