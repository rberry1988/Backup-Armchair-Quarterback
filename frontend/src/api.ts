import type {
  LeagueSummary,
  RosterResponse,
  StartSitResponse,
  TradeResponse,
  WaiverResponse,
} from "./types";

const BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

class ApiError extends Error {}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new ApiError(body.detail || `Request failed: ${res.status}`);
  }
  return res.json();
}

export const api = {
  sync: (leagueId: number, season: number) =>
    request<LeagueSummary>("/api/sync", {
      method: "POST",
      body: JSON.stringify({ league_id: leagueId, season }),
    }),
  getLeague: (leagueId: number) => request<LeagueSummary>(`/api/league/${leagueId}`),
  setMyTeam: (leagueId: number, teamId: number) =>
    request<LeagueSummary>(`/api/league/${leagueId}/my-team`, {
      method: "POST",
      body: JSON.stringify({ team_id: teamId }),
    }),
  getRoster: (leagueId: number) => request<RosterResponse>(`/api/league/${leagueId}/roster`),
  getStartSit: (leagueId: number) => request<StartSitResponse>(`/api/league/${leagueId}/start-sit`),
  getWaivers: (leagueId: number) => request<WaiverResponse>(`/api/league/${leagueId}/waivers`),
  getTrades: (leagueId: number) => request<TradeResponse>(`/api/league/${leagueId}/trades`),
};

export { ApiError };
