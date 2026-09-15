import type {
  AdminUser,
  AlertsResponse,
  BenchPointsResponse,
  ChangesResponse,
  DepthChartsResponse,
  ExpertRankingsResponse,
  HandcuffsResponse,
  ScheduleOutlookResponse,
  LeagueSummary,
  RosterResponse,
  StartSitResponse,
  TeamWithRoster,
  TradeGradeResponse,
  TradeResponse,
  UpdateResult,
  User,
  WaiverResponse,
} from "./types";

// ?? (not ||) so an explicitly empty VITE_API_BASE_URL — the production
// build's setting, meaning "same origin, call /api/... directly" — is
// respected instead of falling back to the dev default.
const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";
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
  if (res.status === 204) return undefined as T;
  try {
    return await res.json();
  } catch {
    // A 200 with a malformed/empty body (e.g. a proxy returning HTML on a
    // transient upstream error) would otherwise throw a raw SyntaxError
    // that callers' `instanceof ApiError` checks don't recognize.
    throw new ApiError("Received an invalid response from the server.", res.status);
  }
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
  changePassword: (currentPassword: string, newPassword: string) =>
    request<void>("/api/auth/change-password", {
      method: "POST",
      body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
    }),

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
  getTeamsWithRosters: (leagueId: number) =>
    request<TeamWithRoster[]>(`/api/league/${leagueId}/teams-with-rosters`),
  gradeTrade: (
    leagueId: number,
    teamAId: number,
    teamASends: number[],
    teamBId: number,
    teamBSends: number[]
  ) =>
    request<TradeGradeResponse>(`/api/league/${leagueId}/trade-grade`, {
      method: "POST",
      body: JSON.stringify({
        team_a_id: teamAId,
        team_a_sends: teamASends,
        team_b_id: teamBId,
        team_b_sends: teamBSends,
      }),
    }),
  getExpertRankings: (leagueId: number) =>
    request<ExpertRankingsResponse>(`/api/league/${leagueId}/expert-rankings`),
  getDepthCharts: (leagueId: number) => request<DepthChartsResponse>(`/api/league/${leagueId}/depth-charts`),
  getHandcuffs: (leagueId: number) => request<HandcuffsResponse>(`/api/league/${leagueId}/handcuffs`),
  getChanges: (leagueId: number) => request<ChangesResponse>(`/api/league/${leagueId}/changes`),
  getAlerts: (leagueId: number) => request<AlertsResponse>(`/api/league/${leagueId}/alerts`),
  getScheduleOutlook: (leagueId: number) =>
    request<ScheduleOutlookResponse>(`/api/league/${leagueId}/schedule-outlook`),
  getBenchPoints: (leagueId: number) => request<BenchPointsResponse>(`/api/league/${leagueId}/bench-points`),

  adminListUsers: () => request<AdminUser[]>("/api/admin/users"),
  adminCreateUser: (email: string, password: string) =>
    request<AdminUser>("/api/admin/users", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),
  adminDeleteUser: (userId: number) =>
    request<void>(`/api/admin/users/${userId}`, { method: "DELETE" }),
  adminResetPassword: (userId: number, newPassword: string) =>
    request<void>(`/api/admin/users/${userId}/reset-password`, {
      method: "POST",
      body: JSON.stringify({ new_password: newPassword }),
    }),
  adminSetAdmin: (userId: number, isAdmin: boolean) =>
    request<AdminUser>(`/api/admin/users/${userId}/admin`, {
      method: "POST",
      body: JSON.stringify({ is_admin: isAdmin }),
    }),
  adminUpdate: () => request<UpdateResult>("/api/admin/update", { method: "POST" }),
};
