import { useEffect, useMemo, useState } from "react";
import type { RosterPickerPlayer, TeamWithRoster, TradeGradePlayer, TradeGradeResponse, TradeGradeSide } from "../types";
import { ApiError, api } from "../api";
import { PositionTag } from "./PositionTag";
import { formatPoints } from "../formatPoints";
import { byLineupOrder, starterSlotRank } from "../lineupSlotOrder";

export function TradeGraderTab({ leagueId, myTeamId }: { leagueId: number; myTeamId: number | null }) {
  const [teams, setTeams] = useState<TeamWithRoster[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [teamAId, setTeamAId] = useState<number | null>(null);
  const [teamBId, setTeamBId] = useState<number | null>(null);
  const [selectedA, setSelectedA] = useState<Set<number>>(new Set());
  const [selectedB, setSelectedB] = useState<Set<number>>(new Set());
  const [result, setResult] = useState<TradeGradeResponse | null>(null);
  const [grading, setGrading] = useState(false);

  useEffect(() => {
    let ignore = false;
    api
      .getTeamsWithRosters(leagueId)
      .then((data) => {
        if (ignore) return;
        setTeams(data);
        const defaultA = myTeamId ?? data[0]?.id ?? null;
        const defaultB = data.find((t) => t.id !== defaultA)?.id ?? null;
        setTeamAId(defaultA);
        setTeamBId(defaultB);
      })
      .catch((e) => {
        if (!ignore) setError(e.message);
      });
    return () => {
      ignore = true;
    };
  }, [leagueId, myTeamId]);

  const teamA = useMemo(() => teams?.find((t) => t.id === teamAId) ?? null, [teams, teamAId]);
  const teamB = useMemo(() => teams?.find((t) => t.id === teamBId) ?? null, [teams, teamBId]);

  function toggle(set: Set<number>, setSet: (s: Set<number>) => void, playerId: number) {
    const next = new Set(set);
    if (next.has(playerId)) next.delete(playerId);
    else next.add(playerId);
    setSet(next);
  }

  async function handleGrade() {
    if (!teamAId || !teamBId || selectedA.size === 0 || selectedB.size === 0) return;
    setGrading(true);
    setError(null);
    setResult(null);
    try {
      const res = await api.gradeTrade(leagueId, teamAId, Array.from(selectedA), teamBId, Array.from(selectedB));
      setResult(res);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to grade trade.");
    } finally {
      setGrading(false);
    }
  }

  if (error && !teams) return <p className="error">{error}</p>;
  if (!teams) return <p>Loading...</p>;

  return (
    <div className="panel">
      <h2>Trade Grader</h2>
      <p className="hint">
        Pick players each side would send. Values are each player's rest-of-season average projected points, so
        grades reflect more than a single week's projection.
      </p>

      <div className="trade-builder">
        <TeamSide
          label="Team A sends"
          teams={teams}
          selectedTeamId={teamAId}
          onTeamChange={(id) => {
            setTeamAId(id);
            setSelectedA(new Set());
          }}
          otherTeamId={teamBId}
          roster={teamA?.roster ?? []}
          selected={selectedA}
          onToggle={(pid) => toggle(selectedA, setSelectedA, pid)}
        />
        <TeamSide
          label="Team B sends"
          teams={teams}
          selectedTeamId={teamBId}
          onTeamChange={(id) => {
            setTeamBId(id);
            setSelectedB(new Set());
          }}
          otherTeamId={teamAId}
          roster={teamB?.roster ?? []}
          selected={selectedB}
          onToggle={(pid) => toggle(selectedB, setSelectedB, pid)}
        />
      </div>

      <button
        onClick={handleGrade}
        disabled={grading || !teamAId || !teamBId || teamAId === teamBId || selectedA.size === 0 || selectedB.size === 0}
      >
        {grading ? "Grading..." : "Grade This Trade"}
      </button>
      {error && <p className="error">{error}</p>}

      {result && (
        <div className="trade-result">
          <p className="verdict">{result.verdict}</p>
          <div className="trade-builder">
            <TradeResultSide side={result.team_a} />
            <TradeResultSide side={result.team_b} />
          </div>
        </div>
      )}
    </div>
  );
}

function TeamSide({
  label,
  teams,
  selectedTeamId,
  onTeamChange,
  otherTeamId,
  roster,
  selected,
  onToggle,
}: {
  label: string;
  teams: TeamWithRoster[];
  selectedTeamId: number | null;
  onTeamChange: (id: number) => void;
  otherTeamId: number | null;
  roster: RosterPickerPlayer[];
  selected: Set<number>;
  onToggle: (playerId: number) => void;
}) {
  // Same lineup order as the Roster and Start/Sit tabs, so a roster reads
  // the same way everywhere instead of in ESPN's raw order here.
  const orderedRoster = byLineupOrder(roster);
  return (
    <div className="trade-side">
      <label>
        {label}
        <select value={selectedTeamId ?? ""} onChange={(e) => onTeamChange(Number(e.target.value))}>
          {teams.map((t) => (
            <option key={t.id} value={t.id} disabled={t.id === otherTeamId}>
              {t.name}
            </option>
          ))}
        </select>
      </label>
      <ul className="player-checklist">
        {orderedRoster.map((p) => (
          <li key={p.espn_player_id}>
            <label>
              <input
                type="checkbox"
                checked={selected.has(p.espn_player_id)}
                onChange={() => onToggle(p.espn_player_id)}
              />
              {p.name} <PositionTag position={p.position} />{" "}
              <span className="hint">{formatPoints(p.projected_points)} pts</span>
            </label>
          </li>
        ))}
      </ul>
    </div>
  );
}

function TradeResultSide({ side }: { side: TradeGradeSide }) {
  return (
    <div className="trade-side">
      <h3>
        {side.name} <span className={`grade-badge grade-${side.grade}`}>{side.grade}</span>
      </h3>
      <p>
        Sends: <PlayerList players={side.sends} /> — total {side.value_sent}
      </p>
      <p>
        Receives: <PlayerList players={side.receives} /> — total {side.value_received}
      </p>
      {side.notes.length > 0 && (
        <ul>
          {side.notes.map((n, i) => (
            <li key={i}>{n}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

const ECR_ARROW: Record<string, string> = { up: "↑", down: "↓", steady: "→" };

function PlayerList({ players }: { players: TradeGradePlayer[] }) {
  // Graded players carry a position but no lineup slot (they're whoever was
  // picked, not a filled lineup), so order by position using the same rank
  // table — QB, RB, WR, TE, D/ST, K.
  const ordered = [...players].sort((a, b) => starterSlotRank(a.position) - starterSlotRank(b.position));
  return (
    <>
      {ordered.map((p, i) => (
        <span key={p.espn_player_id}>
          {i > 0 && ", "}
          {p.name} ({p.ros_value})
          {p.expert && (
            <span className="ecr-badge" title={`Expert range: ${p.expert.rank_min}-${p.expert.rank_max}`}>
              {" "}
              {p.expert.pos_rank} {ECR_ARROW[p.expert.trend]}
            </span>
          )}
          {p.fantasycalc && (
            <span className="fc-badge" title="FantasyCalc market trade value (consensus from real user trades)">
              {" "}
              FC {p.fantasycalc.value}
            </span>
          )}
        </span>
      ))}
    </>
  );
}
