import { useEffect, useState } from "react";
import type {
  BudgetContext,
  PendingClaim,
  PendingClaimsResponse,
  PlannedMove,
  RestOfSeasonSuggestion,
  WaiverGroup,
  WaiverResponse,
  WaiverSuggestion,
} from "../types";
import { ApiError, api } from "../api";
import { formatPoints } from "../formatPoints";
import { MatchupTag } from "./MatchupTag";
import { TrendTag } from "./TrendTag";
import { InjuryBadge } from "./InjuryBadge";

type Lens = "this-week" | "rest-of-season";

/** Adds a "Plan" button to a suggestion row when the viewer can use it —
 * null for basic accounts, so the column simply isn't there for them. */
type PlanHandler = ((s: WaiverSuggestion | RestOfSeasonSuggestion) => void) | null;

function PlanCell({
  suggestion,
  onPlan,
  planned,
  busy,
}: {
  suggestion: WaiverSuggestion | RestOfSeasonSuggestion;
  onPlan: PlanHandler;
  planned: boolean;
  busy: boolean;
}) {
  if (!onPlan) return null;
  return (
    <td>
      {planned ? (
        <span className="hint">Planned</span>
      ) : (
        <button onClick={() => onPlan(suggestion)} disabled={busy}>
          Plan
        </button>
      )}
    </td>
  );
}

function ThisWeekTable({
  group,
  budget,
  onPlan,
  plannedIds,
  busy,
}: {
  group: WaiverGroup<WaiverSuggestion> & { budget?: BudgetContext | null };
  budget: BudgetContext | null;
  onPlan: PlanHandler;
  plannedIds: Set<number>;
  busy: boolean;
}) {
  return (
    <div className="waiver-group">
      <h3>{group.position}</h3>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Add</th>
              <th className="num">Proj.</th>
              <th>Matchup</th>
              <th className="num">% Owned</th>
              <th>Drop</th>
              <th className="num">Net Gain</th>
              <th className="num">{budget?.type === "faab" ? "Suggested Bid" : "Suggested FAAB"}</th>
              <th>Usage Trend</th>
              {onPlan && <th></th>}
            </tr>
          </thead>
          <tbody>
            {group.suggestions.map((s, i) => (
              <tr key={i}>
                <td>
                  {s.add.name}
                  <InjuryBadge status={s.add.injury_status} />
                </td>
                <td className="num">{formatPoints(s.add.projected_points)}</td>
                <td>
                  <MatchupTag matchup={s.add.matchup} />
                </td>
                <td className="num">{s.add.percent_owned}%</td>
                <td>{s.drop_candidate ? s.drop_candidate.name : "-"}</td>
                <td className="num">+{s.point_upgrade}</td>
                <td className="num">
                  {s.suggested_bid != null ? `$${s.suggested_bid}` : `${s.suggested_faab_pct}%`}
                </td>
                <td>
                  <TrendTag trend={s.add.trend} />
                </td>
                <PlanCell
                  suggestion={s}
                  onPlan={onPlan}
                  planned={plannedIds.has(s.add.espn_player_id)}
                  busy={busy}
                />
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function RestOfSeasonTable({
  group,
  onPlan,
  plannedIds,
  busy,
}: {
  group: WaiverGroup<RestOfSeasonSuggestion>;
  onPlan: PlanHandler;
  plannedIds: Set<number>;
  busy: boolean;
}) {
  return (
    <div className="waiver-group">
      <h3>{group.position}</h3>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Add</th>
              <th className="num">Value</th>
              <th className="num">Pos. Rank</th>
              <th className="num">30d Trend</th>
              <th className="num">Proj.</th>
              <th className="num">% Owned</th>
              <th>Drop</th>
              <th className="num">Value Gain</th>
              {onPlan && <th></th>}
            </tr>
          </thead>
          <tbody>
            {group.suggestions.map((s, i) => (
              <tr key={i}>
                <td>
                  {s.add.name}
                  <InjuryBadge status={s.add.injury_status} />
                </td>
                <td className="num">{s.add.fantasycalc?.value ?? "—"}</td>
                <td className="num">
                  {s.add.fantasycalc?.position_rank != null ? `${group.position}${s.add.fantasycalc.position_rank}` : "—"}
                </td>
                <td className={`num${(s.add.fantasycalc?.trend_30_day ?? 0) < 0 ? " trend-down" : " trend-up"}`}>
                  {s.add.fantasycalc?.trend_30_day != null
                    ? `${s.add.fantasycalc.trend_30_day > 0 ? "+" : ""}${s.add.fantasycalc.trend_30_day}`
                    : "—"}
                </td>
                <td className="num">{formatPoints(s.add.projected_points)}</td>
                <td className="num">{s.add.percent_owned}%</td>
                <td>{s.drop_candidate ? s.drop_candidate.name : "-"}</td>
                <td className="num">+{s.value_upgrade}</td>
                <PlanCell
                  suggestion={s}
                  onPlan={onPlan}
                  planned={plannedIds.has(s.add.espn_player_id)}
                  busy={busy}
                />
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/** What everyone can actually still spend. The bid suggestions above are
 * meaningless without it: the number that decides a claim is whether you
 * can outbid the richest rival, not what a heuristic says in the abstract. */
function BudgetPanel({ budget }: { budget: BudgetContext }) {
  if (budget.type === "priority") {
    return (
      <div className="budget-panel">
        <h4>Waiver Order</h4>
        <p className="hint">
          {budget.my_rank != null ? (
            <>
              You're <strong>#{budget.my_rank}</strong> of {budget.teams_ranked}. Anyone above you can take a player
              first, so a claim only lands if they all pass.
            </>
          ) : (
            <>This league runs on waiver priority, but ESPN didn't report your position.</>
          )}
        </p>
        <div className="budget-bars">
          {budget.order.slice(0, 6).map((t) => (
            <span key={t.team} className="budget-chip">
              #{t.rank} {t.team}
            </span>
          ))}
        </div>
      </div>
    );
  }

  const mine = budget.my_remaining;
  const top = budget.top_rival_remaining;
  // Only the richest rival can outbid you, so that's the comparison worth
  // leading with rather than the whole table.
  const outgunned = mine != null && top != null && top > mine;
  return (
    <div className="budget-panel">
      <h4>FAAB Budgets</h4>
      <p className="hint">
        {mine != null ? (
          <>
            You have <strong>${mine}</strong> of ${budget.budget} left.{" "}
            {top != null &&
              (outgunned ? (
                <>
                  The richest rival still has <strong>${top}</strong> &mdash; they can outbid anything you put up.
                </>
              ) : (
                <>
                  No one can outbid you: the richest rival has <strong>${top}</strong>.
                </>
              ))}
          </>
        ) : (
          <>ESPN didn't report your remaining budget.</>
        )}
      </p>
      <div className="budget-bars">
        {budget.rivals.slice(0, 8).map((r) => (
          <span key={r.team} className={`budget-chip${mine != null && r.remaining > mine ? " budget-threat" : ""}`}>
            {r.team} ${r.remaining}
          </span>
        ))}
      </div>
    </div>
  );
}

function claimPlayers(players: { name: string; position: string }[]): string {
  if (players.length === 0) return "-";
  return players.map((p) => (p.position ? `${p.name} (${p.position})` : p.name)).join(", ");
}

/** Real, submitted-in-ESPN moves waiting to be processed. Separate from the
 * local shortlist below it: this is what ESPN will actually act on. */
function EspnClaims({ claims }: { claims: PendingClaim[] }) {
  return (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            <th>Move</th>
            <th>Add</th>
            <th>Drop</th>
            <th className="num">Bid</th>
            <th className="num">Week</th>
          </tr>
        </thead>
        <tbody>
          {claims.map((c) => (
            <tr key={c.id}>
              <td>{c.label}</td>
              <td>{claimPlayers(c.adds)}</td>
              <td>{claimPlayers(c.drops)}</td>
              <td className="num">{c.bid_amount != null ? `$${c.bid_amount}` : "-"}</td>
              <td className="num">{c.scoring_period_id ?? "-"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function WaiversTab({ leagueId, isPremium }: { leagueId: number; isPremium: boolean }) {
  const [data, setData] = useState<WaiverResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lens, setLens] = useState<Lens>("this-week");
  const [claims, setClaims] = useState<PendingClaimsResponse | null>(null);
  const [claimsBusy, setClaimsBusy] = useState(false);
  const [claimsCheckedAt, setClaimsCheckedAt] = useState<Date | null>(null);
  const [planned, setPlanned] = useState<PlannedMove[]>([]);
  const [planError, setPlanError] = useState<string | null>(null);
  const [planBusy, setPlanBusy] = useState(false);

  useEffect(() => {
    let ignore = false;
    api
      .getWaivers(leagueId)
      .then((d) => {
        if (!ignore) setData(d);
      })
      .catch((e) => {
        if (!ignore) setError(e.message);
      });
    return () => {
      ignore = true;
    };
  }, [leagueId]);

  useEffect(() => {
    if (!isPremium) {
      setPlanned([]);
      setClaims(null);
      return;
    }
    let ignore = false;
    api
      .getPlannedMoves(leagueId)
      .then((moves) => {
        if (!ignore) setPlanned(moves);
      })
      .catch(() => {
        // Non-critical panel — leave it empty rather than blocking the
        // recommendations behind an error banner.
      });
    // Fetched separately from the shortlist: this one goes out to ESPN, so
    // it's the slower of the two and shouldn't hold the other up.
    loadClaims(() => ignore);
    return () => {
      ignore = true;
    };
    // loadClaims is stable for a given leagueId and only read here.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [leagueId, isPremium]);

  /** Re-read pending claims straight from ESPN. `cancelled` lets the
   * mount-time call drop a response that arrived after a league switch;
   * the Refresh button passes nothing, since a click is never stale. */
  function loadClaims(cancelled: () => boolean = () => false) {
    setClaimsBusy(true);
    return api
      .getPendingClaims(leagueId)
      .then((res) => {
        if (cancelled()) return;
        setClaims(res);
        setClaimsCheckedAt(new Date());
      })
      .catch((e) => {
        if (cancelled()) return;
        // Shown in place of the table rather than thrown away: a refresh
        // that silently does nothing is worse than one that says why.
        setClaims({
          connected: true,
          claims: [],
          error: e instanceof ApiError ? e.message : "Couldn't reach the server to check ESPN.",
        });
      })
      .finally(() => {
        if (!cancelled()) setClaimsBusy(false);
      });
  }

  async function handlePlan(s: WaiverSuggestion | RestOfSeasonSuggestion) {
    setPlanError(null);
    setPlanBusy(true);
    try {
      const created = await api.addPlannedMove(leagueId, {
        add_espn_player_id: s.add.espn_player_id,
        add_name: s.add.name,
        add_position: currentPosition(s) ?? "",
        drop_espn_player_id: s.drop_candidate?.espn_player_id ?? null,
        drop_name: s.drop_candidate?.name ?? null,
        // Prefer the real dollar bid; the percentage is the fallback for a
        // league with no FAAB budget to convert against.
        faab_bid: "suggested_bid" in s && s.suggested_bid != null
          ? s.suggested_bid
          : "suggested_faab_pct" in s
            ? s.suggested_faab_pct
            : null,
      });
      setPlanned((prev) => [...prev, created]);
    } catch (e) {
      setPlanError(e instanceof ApiError ? e.message : "Failed to save that planned move.");
    } finally {
      setPlanBusy(false);
    }
  }

  async function handleRemovePlan(moveId: number) {
    setPlanError(null);
    setPlanBusy(true);
    try {
      await api.deletePlannedMove(leagueId, moveId);
      setPlanned((prev) => prev.filter((m) => m.id !== moveId));
    } catch (e) {
      setPlanError(e instanceof ApiError ? e.message : "Failed to remove that planned move.");
    } finally {
      setPlanBusy(false);
    }
  }

  if (error) return <p className="error">{error}</p>;
  if (!data) return <p>Loading...</p>;

  const groups = lens === "this-week" ? data.this_week : data.rest_of_season;
  const plannedIds = new Set(planned.map((m) => m.add_espn_player_id));
  // The position isn't on the suggestion itself, only on the group that
  // contains it, so it's resolved from whichever group the row came from.
  function currentPosition(s: WaiverSuggestion | RestOfSeasonSuggestion): string | null {
    for (const g of [...data!.this_week, ...data!.rest_of_season]) {
      if (g.suggestions.some((x) => x.add.espn_player_id === s.add.espn_player_id)) return g.position;
    }
    return null;
  }
  const onPlan: PlanHandler = isPremium ? handlePlan : null;

  return (
    <div className="panel">
      <h2>Waiver Wire Targets</h2>

      {isPremium && (
        <div className="planned-moves">
          <h3>Pending Moves</h3>

          <div className="claims-head">
            <h4>Submitted in ESPN</h4>
            <button onClick={() => loadClaims()} disabled={claimsBusy}>
              {claimsBusy ? "Checking ESPN..." : "Refresh"}
            </button>
            {claimsCheckedAt && !claimsBusy && (
              <span className="hint">
                Checked {claimsCheckedAt.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}
              </span>
            )}
          </div>
          {claims === null ? (
            <p className="hint">Checking ESPN&hellip;</p>
          ) : !claims.connected ? (
            <p className="hint">
              Connect your ESPN account under <strong>Settings &rarr; Account</strong> to see the waiver claims and
              trade offers you've genuinely submitted, straight from ESPN.
            </p>
          ) : claims.error ? (
            <p className="error">{claims.error}</p>
          ) : claims.claims.length === 0 ? (
            <p className="hint">
              No moves are pending in ESPN right now &mdash; anything you submit there shows up here until it
              processes.
            </p>
          ) : (
            <EspnClaims claims={claims.claims} />
          )}

          <h4>Your shortlist</h4>
          {planned.length === 0 ? (
            <p className="hint">
              Nothing planned yet. Use <strong>Plan</strong> on any target below to build your claim list for this
              week &mdash; it's your own shortlist, kept here alongside the recommendations. Submitting a claim
              still happens in ESPN; anything you submit there appears above.
            </p>
          ) : (
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Add</th>
                    <th>Pos</th>
                    <th>Drop</th>
                    <th className="num">Planned FAAB</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {planned.map((m) => (
                    <tr key={m.id}>
                      <td>{m.add_name}</td>
                      <td>{m.add_position || "-"}</td>
                      <td>{m.drop_name ?? "-"}</td>
                      <td className="num">{m.faab_bid != null ? `${m.faab_bid}%` : "-"}</td>
                      <td>
                        <button onClick={() => handleRemovePlan(m.id)} disabled={planBusy}>
                          Remove
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {planError && <p className="error">{planError}</p>}
        </div>
      )}

      {data.budget && <BudgetPanel budget={data.budget} />}

      <div className="lens-toggle">
        <button className={lens === "this-week" ? "active" : ""} onClick={() => setLens("this-week")}>
          This Week
        </button>
        <button className={lens === "rest-of-season" ? "active" : ""} onClick={() => setLens("rest-of-season")}>
          Rest of Season
        </button>
      </div>

      {lens === "this-week" ? (
        <p className="hint">
          Ranked by who helps you win <em>this week</em>. Net Gain factors in more than the raw projection &mdash; a
          rising usage trend or favorable matchup nudges a player up, a falling trend or tough matchup nudges them
          down. Suggested FAAB is a starting point (% of a 100-point budget) scaled off that net gain over your
          weakest rostered player at the position; ignore it if your league uses waiver priority.
        </p>
      ) : (
        <p className="hint">
          Ranked by FantasyCalc market value &mdash; a consensus read on what a player is worth for the{" "}
          <em>remainder of the season</em>, from real trades in leagues like yours. These deliberately differ from the
          weekly list: the best streamer this week often isn't the best asset to hold. Players who are currently out
          are included here, since an injured stash is frequently the point of a rest-of-season pickup.
        </p>
      )}

      {groups.length === 0 ? (
        lens === "rest-of-season" && !data.fantasycalc_available ? (
          <p>
            No market values available yet &mdash; they're pulled during a league sync. Sync this league again (or
            turn on auto-sync in Settings) to populate them.
          </p>
        ) : (
          <p>No upgrades found on the waiver wire right now &mdash; your roster looks solid.</p>
        )
      ) : (
        groups.map((group) =>
          lens === "this-week" ? (
            <ThisWeekTable
              key={group.position}
              group={group as WaiverGroup<WaiverSuggestion>}
              budget={data.budget}
              onPlan={onPlan}
              plannedIds={plannedIds}
              busy={planBusy}
            />
          ) : (
            <RestOfSeasonTable
              key={group.position}
              group={group as WaiverGroup<RestOfSeasonSuggestion>}
              onPlan={onPlan}
              plannedIds={plannedIds}
              busy={planBusy}
            />
          )
        )
      )}
    </div>
  );
}
