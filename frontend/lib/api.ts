import type { ApiSchedule } from "./types";

const BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    cache: "no-store",
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`${res.status} ${res.statusText} — ${body}`);
  }
  return (await res.json()) as T;
}

export function getSchedule(): Promise<ApiSchedule> {
  return request<ApiSchedule>("/api/schedule");
}

export function postPlan(force = false): Promise<ApiSchedule> {
  return request<ApiSchedule>("/api/plan", {
    method: "POST",
    body: JSON.stringify({ force }),
  });
}

export function postFinish(
  runnerName: string,
  actualMinutes: number
): Promise<ApiSchedule> {
  return request<ApiSchedule>("/api/finish", {
    method: "POST",
    body: JSON.stringify({
      runner_name: runnerName,
      actual_minutes: actualMinutes,
    }),
  });
}

export async function postReset(): Promise<void> {
  await request<{ ok: boolean }>("/api/reset", { method: "POST" });
}
