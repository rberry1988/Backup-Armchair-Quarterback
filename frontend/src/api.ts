import type {
  LeagueSummary,
  RosterResponse,
  StartSitResponse,
  TradeResponse,
  User,
  WaiverResponse,
} from "./types";

const BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";
const TOKEN_KEY = "authToken";

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(`${BASE_URL}${path}`, {
    headers,
    ...options,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const message = Array.isArray(body.detail)
      ? body.detail.map((d: { msg?: string }) => d.msg).join(", ")
      : body.detail || `Request failed: ${res.status}`;
    throw new ApiError(message, res.status);
  }
  return res.json();
}

export const api = {
  register: (email: string, password: string) =>
    request<{ access_token: string }>("/api/auth/register", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),
  login: (email: string, password: string) =>
    request<{ access_token: string }>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),
  me: () => request<User>("/api/auth/me"),

  listLeagues: () => request<LeagueSummary[]>("/api/leagues"),
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
