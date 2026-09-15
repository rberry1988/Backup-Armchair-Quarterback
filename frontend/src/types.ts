export interface TeamSummary {
  id: number;
  name: string;
  abbrev: string;
  wins: number;
  losses: number;
  ties: number;
  points_for: number;
  points_against: number;
}

export interface ScoringRule {
  stat_id: number;
  stat_name: string;
  points: number;
}

export interface User {
  id: number;
  email: string;
  is_admin: boolean;
  is_premium: boolean;
}

export interface AdminUser {
  id: number;
  email: string;
  created_at: string;
  league_count: number;
  is_admin: boolean;
  admin_locked: boolean;
  is_premium: boolean;
}

export interface FantasyProsKeyStatus {
  configured: boolean;
  source: "database" | "config" | null;
}

export interface UpdateStep {
  command: string;
  ok: boolean;
  output: string;
}

export interface UpdateResult {
  error?: string;
  detail?: string;
  changed?: boolean;
  restarting?: boolean;
  steps?: UpdateStep[];
}

export interface LeagueSummary {
  id: number;
  espn_league_id: number;
  season: number;
  name: string;
  current_week: number;
  scoring_rules: ScoringRule[];
  my_team_id: number | null;
  synced_at: string | null;
  teams: TeamSummary[];
}

export interface TrendStat {
  label: string;
  recent: number[];
  trend: "up" | "down" | "flat" | null;
}

export interface PlayerTrend {
  weeks_counted: number;
  stats: Record<string, TrendStat>;
}

export interface PlayerConsistency {
  weeks_counted: number;
  average: number;
  floor: number;
  ceiling: number;
  stdev: number;
  boom_rate: number;
  bust_rate: number;
  label: "steady" | "streaky" | "boom/bust" | "unrated";
}

export interface RosterPlayer {
  name: string;
  position: string;
  slot: string;
  is_starter: boolean;
  projected_points: number | null;
  actual_points: number | null;
  injury_status: string;
  percent_owned: number;
  trend: PlayerTrend | null;
  consistency: PlayerConsistency | null;
  fantasycalc: FantasyCalcValue | null;
}

export interface RosterResponse {
  team: string;
  week: number;
  roster: RosterPlayer[];
}

export interface MatchupContext {
  opponent: string;
  defense_rank: number;
  defense_teams_ranked: number;
  label: string;
}

export interface StartSitPlayer {
  name: string;
  position: string;
  projected_points: number | null;
  injury_status: string;
  matchup: MatchupContext | null;
}

export interface StartSitRow {
  slot: string;
  slot_id: number;
  current_starter: StartSitPlayer;
  recommended_starter: StartSitPlayer;
  swap_recommended: boolean;
  reason: string | null;
}

export interface StartSitResponse {
  team: string;
  week: number;
  lineup: StartSitRow[];
  swaps_recommended: number;
}

export interface WaiverSuggestion {
  add: {
    name: string;
    projected_points: number | null;
    percent_owned: number;
    injury_status: string;
    matchup: MatchupContext | null;
    trend: PlayerTrend | null;
  };
  drop_candidate: { name: string; projected_points: number | null } | null;
  point_upgrade: number;
  suggested_faab_pct: number;
}

export interface WaiverResponse {
  team: string;
  recommendations: { position: string; suggestions: WaiverSuggestion[] }[];
}

export interface TradeResponse {
  team: string;
  needs: { position: string; my_starting_strength: number; league_median: number }[];
  surplus_to_trade: { position: string; my_bench_depth: number }[];
  suggested_partners: {
    team: string;
    they_could_send: { position: string; their_bench_depth: number }[];
    they_might_want: { position: string }[];
  }[];
}

export interface RosterPickerPlayer {
  espn_player_id: number;
  name: string;
  position: string;
  projected_points: number | null;
}

export interface TeamWithRoster {
  id: number;
  name: string;
  roster: RosterPickerPlayer[];
}

export interface ExpertContext {
  ecr_rank: number;
  pos_rank: string;
  trend: "up" | "down" | "steady";
  rank_min: number | null;
  rank_max: number | null;
}

export interface FantasyCalcValue {
  value: number;
  position_rank: number | null;
  overall_rank: number | null;
  tier: number | null;
  trend_30_day: number | null;
}

export interface TradeGradePlayer {
  espn_player_id: number;
  name: string;
  position: string;
  ros_value: number;
  expert: ExpertContext | null;
  fantasycalc: FantasyCalcValue | null;
}

export interface TradeGradeSide {
  name: string;
  sends: TradeGradePlayer[];
  receives: TradeGradePlayer[];
  value_sent: number;
  value_received: number;
  grade: string;
  notes: string[];
}

export interface TradeGradeResponse {
  team_a: TradeGradeSide;
  team_b: TradeGradeSide;
  verdict: string;
}

export interface ExpertRankingPlayer {
  fantasypros_id: number;
  name: string;
  team: string;
  position: string;
  pos_rank: string;
  ecr_rank: number;
  ecr_delta: number | null;
  rank_min: number | null;
  rank_max: number | null;
  rank_std: number | null;
  page_url: string;
  espn_player_id: number | null;
}

export type ExpertRankingGroup = Record<string, ExpertRankingPlayer[]>;

export interface ExpertRankingsResponse {
  available: boolean;
  scoring?: string;
  week?: number;
  updated_at?: string;
  ros?: ExpertRankingGroup;
  weekly?: ExpertRankingGroup;
}

export interface DepthChartEntry {
  espn_player_id: number;
  name: string;
  position: string;
  pro_team: string;
  depth_rank: number;
  snap_pct: number | null;
  percent_started: number;
  projected_points: number | null;
  injury_status: string;
  is_free_agent: boolean;
  owner_team_id: number | null;
  owner_team_name: string | null;
}

export type DepthChartByPosition = Record<string, DepthChartEntry[]>;
export type DepthChartsResponse = { depth_charts: Record<string, DepthChartByPosition> };

export interface HandcuffEntry {
  rb: {
    espn_player_id: number;
    name: string;
    pro_team: string;
    depth_rank: number;
  };
  handcuff: DepthChartEntry;
  status: "free_agent" | "mine" | "rostered";
}

export interface HandcuffsResponse {
  handcuffs: HandcuffEntry[];
}

export interface SyncChange {
  espn_player_id: number;
  name: string;
  position: string;
  owner: string | null;
  kind: "injury" | "roster_move" | "ownership" | "projection";
  detail: string;
  magnitude: number;
}

export interface ChangesResponse {
  available: boolean;
  since?: string | null;
  at?: string;
  items?: SyncChange[];
  synced_at?: string | null;
}

export interface AlertReplacement {
  espn_player_id: number;
  name: string;
  position: string;
  pro_team: string;
  projected_points: number | null;
  percent_owned: number;
  injury_status: string;
}

export interface RosterAlert {
  player: {
    espn_player_id: number;
    name: string;
    position: string;
    pro_team: string;
    slot: string;
    is_starter: boolean;
    injury_status: string;
    projected_points: number | null;
  };
  reason: string;
  severity: number;
  backup: (DepthChartEntry & { status: "free_agent" | "mine" | "rostered" }) | null;
  replacements: AlertReplacement[];
}

export interface AlertsResponse {
  team?: string;
  week?: number;
  alerts: RosterAlert[];
  error?: string;
}

export interface OutlookWeek {
  week: number;
  is_bye: boolean;
  opponent: string | null;
  label: string | null;
  defense_rank?: number | null;
  defense_teams_ranked?: number | null;
}

export interface OutlookSummary {
  score: number | null;
  label: string | null;
  byes: number;
}

export interface PlayerOutlook {
  espn_player_id: number;
  name: string;
  position: string;
  pro_team: string;
  bye_week: number | null;
  upcoming: OutlookWeek[];
  upcoming_summary: OutlookSummary;
  playoffs: OutlookWeek[];
  playoff_summary: OutlookSummary;
}

export interface ByeWeekGroup {
  week: number;
  count: number;
  players: { espn_player_id: number; name: string; position: string; pro_team: string }[];
  warnings: string[];
}

export interface ScheduleOutlookResponse {
  team?: string;
  current_week?: number;
  weeks_ahead?: number;
  playoff_weeks?: number[];
  available?: boolean;
  outlook: PlayerOutlook[];
  byes: ByeWeekGroup[];
  error?: string;
}

export interface BenchWeek {
  week: number;
  actual_points: number;
  optimal_points: number;
  left_on_bench: number;
  missed: {
    slot: string;
    started: { name: string; points: number };
    should_have_started: { name: string; points: number };
    points_missed: number;
  }[];
}

export interface BenchPointsResponse {
  weeks: BenchWeek[];
  weeks_counted: number;
  total_left_on_bench: number;
  average_left_on_bench: number;
  total_actual: number;
  total_optimal: number;
  worst_week: BenchWeek | null;
  perfect_weeks: number;
}
