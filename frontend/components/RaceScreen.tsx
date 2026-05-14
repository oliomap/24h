"use client";

import { useCallback, useEffect, useState } from "react";
import { Header } from "./Header";
import { PitStrip } from "./PitStrip";
import { ScheduleTable } from "./ScheduleTable";
import {
  getSchedule,
  postFinish,
  postPlan,
  postReset,
} from "@/lib/api";
import type { ApiAssignment, ApiSchedule } from "@/lib/types";

export function RaceScreen() {
  const [schedule, setSchedule] = useState<ApiSchedule | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);

  const load = useCallback(async () => {
    try {
      const data = await getSchedule();
      setSchedule(data);
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const handleFinish = useCallback(
    async (a: ApiAssignment, minutes: number) => {
      setBusy(true);
      try {
        const next = await postFinish(a.runner_name, minutes);
        setSchedule(next);
        setError(null);
      } finally {
        setBusy(false);
      }
    },
    []
  );

  const handlePlan = useCallback(async () => {
    setBusy(true);
    try {
      const next = await postPlan(true);
      setSchedule(next);
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }, []);

  const handleReset = useCallback(async () => {
    if (!confirm("Plan wirklich löschen?")) return;
    setBusy(true);
    try {
      await postReset();
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }, [load]);

  // Global hotkeys: R = replan, ? = help, Esc = close help.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const target = e.target as HTMLElement | null;
      const inField =
        target instanceof HTMLInputElement ||
        target instanceof HTMLTextAreaElement;
      if (e.key === "?" && !inField) {
        e.preventDefault();
        setHelpOpen(true);
      } else if (e.key === "Escape") {
        setHelpOpen(false);
      } else if ((e.key === "r" || e.key === "R") && !inField) {
        if (schedule?.has_plan) {
          if (confirm("Neu planen — vorhandenen Plan überschreiben?")) {
            void handlePlan();
          }
        } else {
          void handlePlan();
        }
      } else if ((e.key === "p" || e.key === "P") && !inField && !schedule?.has_plan) {
        void handlePlan();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [handlePlan, schedule?.has_plan]);

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center text-[var(--color-muted)]">
        <span className="text-sm tracking-[0.12em] uppercase">Lade…</span>
      </div>
    );
  }

  if (error && !schedule) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center gap-3 px-6">
        <h1 className="text-lg font-medium">Verbindung zum Backend fehlgeschlagen</h1>
        <p className="text-sm text-[var(--color-muted)] max-w-lg text-center">
          {error}
        </p>
        <p className="text-xs text-[var(--color-muted)]">
          Starte das Backend im anderen Terminal: <span className="kbd">cd backend && .venv/bin/uvicorn api:app --port 8000</span>
        </p>
        <button
          onClick={load}
          className="mt-3 px-4 py-2 border border-[var(--color-border)] hover:border-[var(--color-accent)] rounded-md text-sm"
        >
          Erneut versuchen
        </button>
      </div>
    );
  }

  if (!schedule) return null;

  return (
    <div className="max-w-[1280px] w-full mx-auto px-9 pt-7 pb-20">
      <Header raceStart={schedule.race_start} lastReplan={schedule.last_finish} />

      <PitStrip
        raceStart={schedule.race_start}
        cutoff={schedule.cutoff}
        projectedCount={schedule.projected_count}
        totalCourses={schedule.total_courses}
        slackMin={schedule.slack_min}
        finishTime={schedule.last_finish}
        nextUp={schedule.next_up}
      />

      {schedule.has_plan ? (
        <ScheduleTable
          assignments={schedule.assignments}
          raceStart={schedule.race_start}
          cutoff={schedule.cutoff}
          activeCycle={schedule.next_up?.cycle ?? null}
          onFinish={handleFinish}
          pending={busy}
        />
      ) : (
        <section className="bg-[var(--color-panel)] border border-[var(--color-border)] rounded-[10px] py-16 px-8 text-center">
          <p className="text-sm text-[var(--color-muted)] mb-5 tracking-wide">
            Noch kein Plan erstellt.
          </p>
          <button
            onClick={handlePlan}
            disabled={busy}
            className="bg-[var(--color-accent)] text-black font-medium px-5 py-2 rounded-md hover:brightness-110 disabled:opacity-50 transition"
          >
            {busy ? "Plane…" : "Plan erstellen"}
          </button>
          <p className="text-[11px] tracking-[0.14em] uppercase text-[var(--color-muted)] mt-4">
            oder <span className="kbd">P</span> drücken
          </p>
        </section>
      )}

      <HintRow onReset={handleReset} />

      {helpOpen && <HelpOverlay onClose={() => setHelpOpen(false)} />}

      {error && schedule && (
        <div className="fixed bottom-6 right-6 bg-[var(--color-panel)] border border-[var(--color-bad)] rounded-md px-4 py-3 max-w-md">
          <p className="text-[11px] tracking-[0.14em] uppercase text-[var(--color-bad)] mb-1">Fehler</p>
          <p className="text-sm">{error}</p>
        </div>
      )}
    </div>
  );
}

function HintRow({ onReset }: { onReset: () => void }) {
  return (
    <div className="flex gap-6 mt-5 text-[11px] tracking-[0.06em] text-[var(--color-muted)]">
      <span>
        <span className="kbd">↵</span> Eintragen &amp; Neu planen
      </span>
      <span>
        <span className="kbd">R</span> Neu planen
      </span>
      <span>
        <span className="kbd">?</span> Tastenkürzel
      </span>
      <button
        onClick={onReset}
        className="ml-auto text-[var(--color-muted)] hover:text-[var(--color-bad)] transition"
      >
        Plan zurücksetzen
      </button>
    </div>
  );
}

function HelpOverlay({ onClose }: { onClose: () => void }) {
  const items: [string, string][] = [
    ["↵", "Ist-Zeit der aktiven Etappe eintragen und sofort neu planen"],
    ["R", "Kompletten Plan neu rechnen (überschreibt geplante Etappen)"],
    ["P", "Wenn kein Plan existiert: Plan erstellen"],
    ["Esc", "Eingabe leeren / Overlay schließen"],
    ["?", "Diese Übersicht öffnen"],
  ];
  return (
    <div
      className="fixed inset-0 bg-black/70 backdrop-blur-sm flex items-center justify-center z-50"
      onClick={onClose}
    >
      <div
        className="bg-[var(--color-panel)] border border-[var(--color-border)] rounded-xl p-7 max-w-md w-full"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="text-[11px] tracking-[0.14em] uppercase text-[var(--color-muted)] mb-4">
          Tastenkürzel
        </h2>
        <dl className="space-y-3">
          {items.map(([k, v]) => (
            <div key={k} className="flex items-start gap-4">
              <dt className="w-12 shrink-0">
                <span className="kbd">{k}</span>
              </dt>
              <dd className="text-sm">{v}</dd>
            </div>
          ))}
        </dl>
      </div>
    </div>
  );
}
