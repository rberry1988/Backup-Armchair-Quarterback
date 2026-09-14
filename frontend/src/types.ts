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

export interface TradeGradePlayer {
  espn_player_id: number;
  name: string;
  position: string;
  ros_value: number;
  expert: ExpertContext | null;
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
