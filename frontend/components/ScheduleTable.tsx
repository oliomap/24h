"use client";

import { useEffect, useRef, useState } from "react";
import {
  formatDurationMin,
  formatRaceTime,
  statusLabel,
} from "@/lib/format";
import type { ApiAssignment, AssignmentStatus } from "@/lib/types";

interface ScheduleTableProps {
  assignments: ApiAssignment[];
  raceStart: string;
  cutoff: string;
  /** Cycle number of the next-up (planned) leg. */
  activeCycle: number | null;
  /** Called when the user submits an actual time for the active row. */
  onFinish: (assignment: ApiAssignment, actualMinutes: number) => Promise<void>;
  /** True while a finish request is in flight. */
  pending: boolean;
}

export function ScheduleTable({
  assignments,
  raceStart,
  cutoff,
  activeCycle,
  onFinish,
  pending,
}: ScheduleTableProps) {
  return (
    <section className="bg-[var(--color-panel)] border border-[var(--color-border)] rounded-[10px] overflow-hidden">
      <table className="w-full border-collapse">
        <thead>
          <tr className="text-left">
            {[
              ["#", "w-[52px]"],
              ["Läufer", "w-[120px]"],
              ["Bahn", "w-[80px]"],
              ["Typ", "w-[80px]"],
              ["Start", "w-[88px]"],
              ["Soll", "w-[68px]"],
              ["Ziel", "w-[88px]"],
              ["Ist", "w-[200px]"],
              ["Status", "w-[100px]"],
              ["∑", "w-[60px] text-right"],
            ].map(([h, cls]) => (
              <th
                key={h}
                className={`px-[18px] py-[14px] text-[10px] tracking-[0.14em] uppercase text-[var(--color-muted)] font-medium border-b border-[var(--color-border)] ${cls}`}
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {assignments.map((a) => (
            <Row
              key={a.cycle}
              assignment={a}
              raceStart={raceStart}
              cutoff={cutoff}
              isActive={a.cycle === activeCycle}
              onFinish={onFinish}
              pending={pending}
              cumulative={cumulativeAt(assignments, a.cycle)}
            />
          ))}
          {assignments.length === 0 && (
            <tr>
              <td
                colSpan={10}
                className="text-center py-12 text-[var(--color-muted)] text-sm"
              >
                Kein Plan vorhanden — drücke{" "}
                <span className="kbd">P</span> oder den Button oben, um einen
                Plan zu erstellen.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </section>
  );
}

function cumulativeAt(all: ApiAssignment[], cycle: number): number | null {
  let n = 0;
  for (const a of all) {
    if (a.status === "done") {
      n += 1;
      if (a.cycle === cycle) return n;
    }
  }
  return null;
}

function Row({
  assignment,
  raceStart,
  cutoff,
  isActive,
  onFinish,
  pending,
  cumulative,
}: {
  assignment: ApiAssignment;
  raceStart: string;
  cutoff: string;
  isActive: boolean;
  onFinish: ScheduleTableProps["onFinish"];
  pending: boolean;
  cumulative: number | null;
}) {
  const a = assignment;
  const isDone = a.status === "done";
  const overCutoff = new Date(a.planned_finish) > new Date(cutoff);

  return (
    <tr
      className={[
        "border-b border-[var(--color-border-soft)] last:border-b-0",
        isDone ? "text-[var(--color-dim)]" : "text-[var(--color-text)]",
        isActive ? "bg-[var(--color-active-bg)] font-medium" : "",
      ].join(" ")}
    >
      <td
        className={`px-[18px] py-[14px] text-[12px] text-[var(--color-muted)] tabular ${
          isActive
            ? "shadow-[inset_3px_0_0_0_var(--color-accent)]"
            : ""
        }`}
      >
        {a.cycle.toString().padStart(2, "0")}
      </td>
      <td className="px-[18px] py-[14px] font-medium">{a.runner_name}</td>
      <td className="px-[18px] py-[14px] font-mono font-semibold tracking-[0.02em]">
        {a.course_code}
      </td>
      <td className="px-[18px] py-[14px] text-[12px] tracking-[0.06em] text-[var(--color-muted)]">
        {a.course_type}
      </td>
      <td className="px-[18px] py-[14px] font-mono tabular">
        {formatRaceTime(a.planned_start, raceStart)}
      </td>
      <td className="px-[18px] py-[14px] font-mono tabular">
        {Math.round(a.planned_duration_min)}
      </td>
      <td
        className={`px-[18px] py-[14px] font-mono tabular ${
          overCutoff ? "text-[var(--color-bad)]" : ""
        }`}
      >
        {formatRaceTime(a.planned_finish, raceStart)}
      </td>
      <td className="px-[18px] py-[14px]">
        {isActive ? (
          <ActiveInput assignment={a} onFinish={onFinish} pending={pending} />
        ) : isDone ? (
          <span className="font-mono text-[var(--color-good)] font-medium tabular">
            {formatDurationMin(a.actual_duration_min)}
          </span>
        ) : (
          <span className="font-mono tabular text-[var(--color-muted)]">—</span>
        )}
      </td>
      <td>
        <StatusBadge status={a.status} />
      </td>
      <td className="px-[18px] py-[14px] text-right text-[var(--color-muted)] tabular">
        {cumulative ?? "—"}
      </td>
    </tr>
  );
}

function StatusBadge({ status }: { status: AssignmentStatus }) {
  const cls =
    status === "done"
      ? "text-[var(--color-good)]"
      : status === "in_progress"
      ? "text-[var(--color-accent)]"
      : "text-[var(--color-muted)]";
  return (
    <span
      className={`px-[18px] py-[14px] text-[10px] tracking-[0.12em] uppercase font-medium ${cls}`}
    >
      {statusLabel(status)}
    </span>
  );
}

function ActiveInput({
  assignment,
  onFinish,
  pending,
}: {
  assignment: ApiAssignment;
  onFinish: ScheduleTableProps["onFinish"];
  pending: boolean;
}) {
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Always keep focus on the active input (the operator types and hits Enter).
  useEffect(() => {
    inputRef.current?.focus();
  }, [assignment.cycle]);

  async function submit() {
    const cleaned = value.replace(",", ".").trim();
    const minutes = Number(cleaned);
    if (!Number.isFinite(minutes) || minutes <= 0) {
      setError("Bitte eine Zahl > 0 eingeben");
      return;
    }
    setError(null);
    try {
      await onFinish(assignment, minutes);
      setValue("");
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <div className="flex items-center gap-2.5">
      <span className="inline-flex items-center gap-2 bg-[#1d1408] border border-[var(--color-accent)] rounded-md px-2.5 py-1 glow-ring">
        <input
          ref={inputRef}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              if (!pending) void submit();
            }
            if (e.key === "Escape") {
              setValue("");
              setError(null);
            }
          }}
          inputMode="decimal"
          placeholder="—"
          aria-label={`Ist-Zeit für ${assignment.runner_name} auf ${assignment.course_code}`}
          className="w-[60px] bg-transparent border-none outline-none font-mono font-medium text-right tabular text-[var(--color-text)]"
          disabled={pending}
        />
        <span className="text-[12px] text-[var(--color-muted)]">Min</span>
      </span>
      <span className="text-[10px] tracking-[0.12em] uppercase text-[var(--color-accent)] border border-[rgba(245,166,35,0.25)] bg-[rgba(245,166,35,0.12)] rounded px-2 py-0.5">
        {pending ? "Plane…" : "Enter ↵"}
      </span>
      {error && (
        <span className="text-[11px] text-[var(--color-bad)]">{error}</span>
      )}
    </div>
  );
}
