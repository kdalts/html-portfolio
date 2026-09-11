// Typed client for the backend read API (backend/app/api/). Every call
// fetches fresh (`cache: "no-store"`) since this dashboard shows
// frequently-changing prediction/ranking data - never something we want
// a stale build-time or ISR snapshot of. The API base URL is a
// server-only env var (no NEXT_PUBLIC_ prefix): nothing about the
// backend's location or credentials is ever bundled into client-side
// JavaScript, matching the platform's rule that secrets never reach
// frontend code.

import type {
  BacktestRunSummary,
  ChecklistResponse,
  DailyRankingResponse,
  FixtureDetailResponse,
  LeaguePerformanceEntry,
  ModelPerformanceEntry,
  SystemHealthResponse,
} from "./types";

const API_BASE_URL = process.env.API_BASE_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function apiFetch<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, { cache: "no-store" });
  if (!response.ok) {
    throw new ApiError(response.status, `${path} returned ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export function getDailyRanking(date: string): Promise<DailyRankingResponse> {
  return apiFetch(`/api/rankings/daily?ranking_date=${date}`);
}

export function getFixtureDetail(fixtureId: number): Promise<FixtureDetailResponse> {
  return apiFetch(`/api/fixtures/${fixtureId}`);
}

export function getLeaguePerformance(): Promise<LeaguePerformanceEntry[]> {
  return apiFetch(`/api/leagues/performance`);
}

export function getModelPerformance(): Promise<ModelPerformanceEntry[]> {
  return apiFetch(`/api/models/performance`);
}

export function getBacktestRuns(): Promise<BacktestRunSummary[]> {
  return apiFetch(`/api/backtest/runs`);
}

export function getSystemHealth(): Promise<SystemHealthResponse> {
  return apiFetch(`/api/system/health`);
}

export function getDailyChecklist(date: string): Promise<ChecklistResponse> {
  return apiFetch(`/api/checklist/daily?checklist_date=${date}`);
}
