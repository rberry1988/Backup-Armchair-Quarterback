import { useEffect, useState } from "react";
import type { AlertsResponse, ChangesResponse, RosterAlert, SyncChange } from "../types";
import { api } from "../api";
import { PositionTag } from "./PositionTag";
import { InjuryBadge } from "./InjuryBadge";
import { formatPoints } from "../formatPoints";

const KIND_LABEL: Record<SyncChange["kind"], string> = {
  injury: "Injury",
  roster_move: "Roster move",
  ownership: "Ownership",
  projection: "Projection",
};

const KIND_CLASS: Record<SyncChange["kind"], string> = {
  injury: "grade-D",
  roster_move: "grade-B",
  ownership: "grade-C",
  projection: "matchup-average",
};

const BACKUP_STATUS_LABEL: Record<string, string> = {
  free_agent: "on waivers",
  mine: "already yours",
  rostered: "rostered elsewhere",
};

export function AlertsTab({ leagueId }: { leagueId: number }) {
  const [alerts, setAlerts] = useState<AlertsResponse | null>(null);
  const [changes, setChanges] = useState<ChangesResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let ignore = false;
    Promise.all([api.getAlerts(leagueId), api.getChanges(leagueId)])
      .then(([a, c]) => {
        if (ignore) return;
        setAlerts(a);
        setChanges(c);
      })
      .catch((e) => {
        if (!ignore) setError(e.message);
      });
    return () => {
      ignore = true;
    };
  }, [leagueId]);

  if (error) return <p className="error">{error}</p>;
  if (!alerts || !changes) return <p>Loading...</p>;

  return (
    <>
      <div className="panel">
        <h2>Needs Attention {alerts.week ? `— Week ${alerts.week}` : ""}</h2>
        {alerts.alerts.length === 0 ? (
          <p>Nothing flagged. No injured or bye-week players in your lineup right now.</p>
        ) : (
          <>
            <p className="hint">
              Each injured or bye-week player on your roster, who'd absorb their role on their NFL team, and the
              best replacements sitting on your waiver wire.
            </p>
            {alerts.alerts.map((alert) => (
              <AlertCard key={alert.player.espn_player_id} alert={alert} />
            ))}
          </>
        )}
      </div>

      <div className="panel" style={{ marginTop: "1.25rem" }}>
        <h2>Since Your Last Sync</h2>
        {!changes.available || !changes.items || changes.items.length === 0 ? (
          <p className="hint">
            No changes recorded yet — this fills in once you've synced at least twice, comparing the two most
            recent syncs.
          </p>
        ) : (
          <>
            <p className="hint">
              Comparing {formatWhen(changes.since)} to {formatWhen(changes.at)}.
            </p>
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>What</th>
                    <th>Player</th>
                    <th>Pos</th>
                    <th>Change</th>
                    <th>Team</th>
                  </tr>
                </thead>
                <tbody>
                  {changes.items.map((item, i) => (
                    <tr key={`${item.espn_player_id}-${item.kind}-${i}`}>
                      <td>
                        <span className={`grade-badge ${KIND_CLASS[item.kind]}`}>{KIND_LABEL[item.kind]}</span>
                      </td>
                      <td>{item.name}</td>
                      <td>
                        <PositionTag position={item.position} />
                      </td>
                      <td>{item.detail}</td>
                      <td className="hint">{item.owner ?? "Free agent"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>
    </>
  );
}

function AlertCard({ alert }: { alert: RosterAlert }) {
  const { player, backup, replacements } = alert;
  return (
    <div className="partner-card">
      <h4>
        {player.name} <PositionTag position={player.position} /> <span className="pos-tag">{player.pro_team}</span>{" "}
        {alert.reason === "on bye" ? <span className="badge">BYE</span> : <InjuryBadge status={alert.reason} />}
        {player.is_starter && <span className="ecr-badge"> starting at {player.slot}</span>}
      </h4>

      {backup ? (
        <p className="hint">
          Next up on {player.pro_team}: <strong>{backup.name}</strong> — {BACKUP_STATUS_LABEL[backup.status]}
          {backup.status === "rostered" && backup.owner_team_name ? ` (${backup.owner_team_name})` : ""}
        </p>
      ) : (
        <p className="hint">No clear backup on their NFL team in the synced player pool.</p>
      )}

      {replacements.length > 0 && (
        <p className="hint">
          Best available {player.position}s:{" "}
          {replacements.map((r, i) => (
            <span key={r.espn_player_id}>
              {i > 0 && ", "}
              {r.name} ({formatPoints(r.projected_points)} proj)
            </span>
          ))}
        </p>
      )}
    </div>
  );
}

function formatWhen(value: string | null | undefined): string {
  if (!value) return "your previous sync";
  const parsed = new Date(value.endsWith("Z") ? value : `${value}Z`);
  if (Number.isNaN(parsed.getTime())) return "your previous sync";
  return parsed.toLocaleString();
}
