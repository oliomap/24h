"use client";

import { useEffect, useMemo, useState } from "react";
import {
  formatHM,
  formatRaceTime,
  formatSlack,
  typeLabel,
} from "@/lib/format";
import type { ApiNextUp } from "@/lib/types";

interface PitStripProps {
  raceStart: string;
  cutoff: string;
  projectedCount: number;
  totalCourses: number;
  slackMin: number | null;
  finishTime: string | null;
  nextUp: ApiNextUp | null;
}

function useTick(intervalMs = 1000) {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return now;
}

function Card({
  label,
  value,
  sub,
  valueClass,
}: {
  label: string;
  value: React.ReactNode;
  sub?: React.ReactNode;
  valueClass?: string;
}) {
  return (
    <div className="bg-[var(--color-panel)] border border-[var(--color-border)] rounded-[10px] px-6 py-5">
      <div className="text-[10px] tracking-[0.16em] uppercase text-[var(--color-muted)] font-medium mb-2.5">
        {label}
      </div>
      <div
        className={`text-[36px] font-medium tracking-[-0.02em] leading-[1.05] tabular ${valueClass ?? ""}`}
      >
        {value}
      </div>
      {sub && (
        <div className="text-[12px] text-[var(--color-muted)] mt-1.5 tabular">
          {sub}
        </div>
      )}
    </div>
  );
}

export function PitStrip({
  raceStart,
  cutoff,
  projectedCount,
  totalCourses,
  slackMin,
  finishTime,
  nextUp,
}: PitStripProps) {
  const now = useTick(1000);
  // Parse once per prop-change, not once per tick. The ISO strings change only
  // when the schedule reloads, so we avoid 60+ wasted allocations per minute.
  const start = useMemo(() => new Date(raceStart), [raceStart]);
  const end = useMemo(() => new Date(cutoff), [cutoff]);
  const beforeStart = now < start;
  const elapsedMs = Math.max(0, now.getTime() - start.getTime());
  const remainingMs = Math.max(0, end.getTime() - now.getTime());
  const clock = beforeStart
    ? `−${formatHM((start.getTime() - now.getTime()) / 1000 / 60)}`
    : formatClock(elapsedMs);

  const slackClass =
    slackMin == null
      ? "text-[var(--color-muted)]"
      : slackMin >= 0
      ? "text-[var(--color-good)]"
      : "text-[var(--color-bad)]";

  return (
    <section className="grid grid-cols-[1.3fr_1fr_1fr_1.3fr] gap-[18px] mb-7">
      <Card
        label="Rennzeit"
        value={<span className="font-mono">{clock}</span>}
        sub={
          beforeStart
            ? `${formatHM((start.getTime() - now.getTime()) / 60000)} bis Start`
            : `${formatHM(remainingMs / 60000)} verbleibend`
        }
      />
      <Card
        label="Bahnen"
        value={
          <>
            <span className="font-mono">{projectedCount}</span>
            <span className="text-[var(--color-muted)] font-normal">/{totalCourses}</span>
          </>
        }
        sub="Prognose"
      />
      <Card
        label="Puffer bis Ziel"
        value={
          slackMin == null ? (
            <span className="font-mono text-[var(--color-muted)]">—</span>
          ) : (
            <span className="font-mono">{formatSlack(slackMin)}</span>
          )
        }
        sub={finishTime ? `Ziel ${formatRaceTime(finishTime, raceStart)}` : "kein Plan"}
        valueClass={slackClass}
      />
      <Card
        label="Als nächstes"
        value={
          nextUp ? (
            <span className="text-[24px]">
              <span className="text-[var(--color-accent)]">{nextUp.runner_name}</span>{" "}
              <span className="text-[var(--color-text)]">·</span>{" "}
              <span className="font-mono">{nextUp.course_code}</span>
            </span>
          ) : (
            <span className="text-[24px] text-[var(--color-muted)]">—</span>
          )
        }
        sub={
          nextUp
            ? `${formatRaceTime(nextUp.planned_start, raceStart)} Start · ${Math.round(
                nextUp.planned_duration_min
              )} Min Prognose · ${typeLabel(nextUp.course_type)}`
            : "Plan erstellen"
        }
      />
    </section>
  );
}

function formatClock(ms: number) {
  const totalSeconds = Math.floor(ms / 1000);
  const h = Math.floor(totalSeconds / 3600);
  const m = Math.floor((totalSeconds % 3600) / 60);
  const s = totalSeconds % 60;
  return `${h.toString().padStart(2, "0")}:${m
    .toString()
    .padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
}
