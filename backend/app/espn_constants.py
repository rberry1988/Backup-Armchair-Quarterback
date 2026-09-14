"""Lookup tables for ESPN's fantasy football numeric IDs.

ESPN's public API is undocumented; these mappings are the ones the
fantasy-football community has reverse engineered and are stable across
seasons. Only the fields this app actually uses are mapped.
"""

POSITION_MAP = {
    0: "QB",
    1: "QB",
    2: "RB",
    3: "WR",
    4: "TE",
    5: "K",
    16: "D/ST",
}

# lineupSlotId -> human label. Bench/IR are used to tell starters from bench.
LINEUP_SLOT_MAP = {
    0: "QB",
    2: "RB",
    3: "RB/WR",
    4: "WR",
    5: "WR/TE",
    6: "TE",
    7: "OP",
    16: "D/ST",
    17: "K",
    20: "BE",
    21: "IR",
    23: "FLEX",
    24: "EDR",
}

BENCH_SLOTS = {20, 21, 24}

# proTeamId -> NFL team abbreviation. Verified live against ESPN's public
# site scoreboard API (site.api.espn.com), which uses this same numeric
# id scheme — not officially documented, but stable.
PRO_TEAM_ABBREVIATIONS = {
    1: "ATL", 2: "BUF", 3: "CHI", 4: "CIN", 5: "CLE", 6: "DAL", 7: "DEN", 8: "DET",
    9: "GB", 10: "TEN", 11: "IND", 12: "KC", 13: "LV", 14: "LAR", 15: "MIA", 16: "MIN",
    17: "NE", 18: "NO", 19: "NYG", 20: "NYJ", 21: "PHI", 22: "ARI", 23: "PIT", 24: "LAC",
    25: "SF", 26: "SEA", 27: "TB", 28: "WSH", 29: "CAR", 30: "JAX", 33: "BAL", 34: "HOU",
}

INJURY_STATUS_MAP = {
    "ACTIVE": "Active",
    "QUESTIONABLE": "Questionable",
    "DOUBTFUL": "Doubtful",
    "OUT": "Out",
    "INJURY_RESERVE": "IR",
    "SUSPENSION": "Suspended",
}

# statId -> (label, is_per_reception_flag). Only the common statIds used in
# most standard/PPR scoring settings are included.
STAT_ID_MAP = {
    0: "Passing Attempts",
    1: "Passing Completions",
    3: "Passing Yards",
    4: "Passing TD",
    19: "Passing 50+ Yard TD Bonus",
    20: "Passing Interceptions",
    24: "Rushing Attempts",
    25: "Rushing Yards",
    26: "Rushing TD",
    42: "Receiving Yards",
    43: "Receiving TD",
    53: "Receiving Receptions",
    58: "Receiving Targets",
    72: "Fumbles Lost",
    74: "Field Goals Made 50+",
    77: "Field Goals Made 40-49",
    80: "Field Goals Made 0-39",
    85: "Extra Points Made",
    86: "Sacks",
    89: "Interceptions (Defense)",
    90: "Fumble Recoveries",
    95: "Defensive/Special Teams TD",
    96: "Safeties",
    98: "Blocked Kicks",
    99: "Kickoff Return TD",
    103: "Punt Return TD",
    123: "Points Allowed",
}


def position_from_id(default_position_id: int) -> str:
    return POSITION_MAP.get(default_position_id, f"POS{default_position_id}")


def lineup_slot_label(slot_id: int) -> str:
    return LINEUP_SLOT_MAP.get(slot_id, f"SLOT{slot_id}")


def is_bench_slot(slot_id: int) -> bool:
    return slot_id in BENCH_SLOTS


def pro_team_abbr(pro_team_id: int | None) -> str:
    return PRO_TEAM_ABBREVIATIONS.get(pro_team_id, "FA" if not pro_team_id else f"T{pro_team_id}")
