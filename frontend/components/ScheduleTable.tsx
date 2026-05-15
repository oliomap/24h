"use client";

import { useEffect, useRef, useState } from "react";
import {
  formatDurationMin,
  formatRaceTime,
  statusLabel,
  typeLabel,
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
  const empty = assignments.length === 0;

  return (
    <>
      {/* Mobile + tablet portrait: vertical card stack.
          The desktop table needs ~1000 px to breathe, so we keep cards
          all the way up to the lg breakpoint (1024 px). */}
      <section className="lg:hidden flex flex-col gap-2.5">
        {empty ? (
          <EmptyHint />
        ) : (
          assignments.map((a) => (
            <MobileCard
              key={a.cycle}
              assignment={a}
              raceStart={raceStart}
              cutoff={cutoff}
              isActive={a.cycle === activeCycle}
              onFinish={onFinish}
              pending={pending}
              cumulative={cumulativeAt(assignments, a.cycle)}
            />
          ))
        )}
      </section>

      {/* Desktop: the original dense table, unchanged. */}
      <section className="hidden lg:block bg-[var(--color-panel)] border border-[var(--color-border)] rounded-[10px] overflow-hidden">
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
            {empty && (
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
    </>
  );
}

function EmptyHint() {
  return (
    <div className="bg-[var(--color-panel)] border border-[var(--color-border)] rounded-[10px] text-center py-10 px-4 text-[var(--color-muted)] text-sm">
      Kein Plan vorhanden — Button oben antippen, um einen Plan zu erstellen.
    </div>
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

  // Keep focus on the active input — this component only renders at lg+
  // (≥1024 px), where a physical keyboard is overwhelmingly likely.
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

/* ─── Mobile card view ─────────────────────────────────────────────────── */

function MobileCard({
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
  const cardRef = useRef<HTMLDivElement>(null);

  // Auto-scroll the active card into view (centered) when it becomes active
  // or when the page first loads with an active row. Race-day ergonomics:
  // the operator should never hunt for the input.
  useEffect(() => {
    if (isActive && cardRef.current) {
      cardRef.current.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, [isActive]);

  const tone = isActive
    ? "border-[var(--color-accent)] bg-[var(--color-active-bg)] shadow-[0_0_0_1px_rgba(245,166,35,0.25),0_0_24px_rgba(245,166,35,0.08)]"
    : isDone
    ? "border-[var(--color-border-soft)] bg-[var(--color-panel)] opacity-70"
    : "border-[var(--color-border)] bg-[var(--color-panel)]";

  return (
    <article
      ref={cardRef}
      className={`relative rounded-[10px] border ${tone} px-3.5 py-3 transition-colors`}
    >
      {isActive && (
        <span className="absolute left-0 top-3 bottom-3 w-[3px] rounded-r bg-[var(--color-accent)]" />
      )}

      {/* Top row: cycle # · runner · status pill */}
      <div className="flex items-center justify-between gap-2 mb-2">
        <div className="flex items-baseline gap-2 min-w-0">
          <span className="text-[11px] tabular text-[var(--color-muted)] font-mono">
            #{a.cycle.toString().padStart(2, "0")}
          </span>
          <span
            className={`text-[15px] font-medium truncate ${
              isDone ? "text-[var(--color-dim)]" : "text-[var(--color-text)]"
            }`}
          >
            {a.runner_name}
          </span>
        </div>
        <MobileStatusBadge status={a.status} cumulative={cumulative} />
      </div>

      {/* Course + type + time facts */}
      <div className="flex items-center justify-between gap-3 mb-2">
        <div className="flex items-baseline gap-2 min-w-0">
          <span
            className={`font-mono font-semibold text-[20px] tracking-[0.02em] ${
              isDone ? "text-[var(--color-dim)]" : "text-[var(--color-text)]"
            }`}
          >
            {a.course_code}
          </span>
          <span className="text-[10px] tracking-[0.14em] uppercase text-[var(--color-muted)]">
            {typeLabel(a.course_type)}
          </span>
        </div>
      </div>

      {/* Fact strip: Start · Soll · Ziel */}
      <div className="grid grid-cols-3 gap-2 text-[12px]">
        <Fact label="Start" value={formatRaceTime(a.planned_start, raceStart)} dim={isDone} />
        <Fact
          label="Soll"
          value={`${Math.round(a.planned_duration_min)} Min`}
          dim={isDone}
        />
        <Fact
          label="Ziel"
          value={formatRaceTime(a.planned_finish, raceStart)}
          valueClass={overCutoff && !isDone ? "text-[var(--color-bad)]" : undefined}
          dim={isDone}
        />
      </div>

      {/* Footer — varies by status */}
      {isActive && (
        <div className="mt-3 pt-3 border-t border-[rgba(245,166,35,0.25)]">
          <MobileActiveInput
            assignment={a}
            onFinish={onFinish}
            pending={pending}
          />
        </div>
      )}
      {isDone && a.actual_duration_min != null && (
        <div className="mt-2.5 pt-2.5 border-t border-[var(--color-border-soft)] flex items-baseline justify-between">
          <span className="text-[10px] tracking-[0.14em] uppercase text-[var(--color-muted)]">
            Ist
          </span>
          <span className="font-mono text-[var(--color-good)] font-medium tabular text-[15px]">
            {formatDurationMin(a.actual_duration_min)} Min
          </span>
        </div>
      )}
    </article>
  );
}

function Fact({
  label,
  value,
  valueClass,
  dim,
}: {
  label: string;
  value: string;
  valueClass?: string;
  dim?: boolean;
}) {
  return (
    <div>
      <div className="text-[9px] tracking-[0.14em] uppercase text-[var(--color-muted)] mb-0.5">
        {label}
      </div>
      <div
        className={`font-mono tabular ${
          dim ? "text-[var(--color-dim)]" : "text-[var(--color-text)]"
        } ${valueClass ?? ""}`}
      >
        {value}
      </div>
    </div>
  );
}

function MobileStatusBadge({
  status,
  cumulative,
}: {
  status: AssignmentStatus;
  cumulative: number | null;
}) {
  const config =
    status === "done"
      ? {
          dot: "bg-[var(--color-good)]",
          text: "text-[var(--color-good)]",
          label: cumulative != null ? `#${cumulative} fertig` : statusLabel(status),
        }
      : status === "in_progress"
      ? {
          dot: "bg-[var(--color-accent)] shadow-[0_0_8px_rgba(245,166,35,0.7)]",
          text: "text-[var(--color-accent)]",
          label: "läuft",
        }
      : {
          dot: "bg-[var(--color-muted)]",
          text: "text-[var(--color-muted)]",
          label: statusLabel(status),
        };
  return (
    <span
      className={`inline-flex items-center gap-1.5 text-[10px] tracking-[0.12em] uppercase font-medium shrink-0 ${config.text}`}
    >
      <span className={`w-1.5 h-1.5 rounded-full ${config.dot}`} />
      {config.label}
    </span>
  );
}

function MobileActiveInput({
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
      inputRef.current?.blur();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  const canSubmit = value.trim().length > 0 && !pending;

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-stretch gap-2 min-w-0">
        <label className="flex-1 min-w-0 flex items-center gap-2 bg-[#1d1408] border border-[var(--color-accent)] rounded-md px-3 glow-ring min-h-[48px]">
          <input
            ref={inputRef}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                if (canSubmit) void submit();
              }
            }}
            inputMode="decimal"
            placeholder="Ist-Zeit"
            aria-label={`Ist-Zeit für ${assignment.runner_name} auf ${assignment.course_code}`}
            size={1}
            className="flex-1 min-w-0 w-full bg-transparent border-none outline-none font-mono font-medium tabular text-[18px] text-[var(--color-text)] placeholder:text-[var(--color-muted)] placeholder:text-[14px]"
            disabled={pending}
          />
          <span className="text-[12px] tracking-[0.06em] text-[var(--color-muted)] shrink-0">
            Min
          </span>
        </label>
        <button
          type="button"
          onClick={() => void submit()}
          disabled={!canSubmit}
          className="bg-[var(--color-accent)] text-black font-medium px-4 rounded-md hover:brightness-110 disabled:opacity-40 disabled:cursor-not-allowed transition min-h-[48px] text-[13px] tracking-[0.08em] uppercase shrink-0"
        >
          {pending ? "Plane…" : "Eintragen"}
        </button>
      </div>
      {error && (
        <span className="text-[11px] text-[var(--color-bad)]">{error}</span>
      )}
    </div>
  );
}
