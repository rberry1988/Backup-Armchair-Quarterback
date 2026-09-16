import { useEffect, useState } from "react";
import type { ActivityResponse, ActivityTransaction, ManagerSpending } from "../types";
import { api } from "../api";

function names(players: { name: string }[]): string {
  return players.length ? players.map((p) => p.name).join(", ") : "-";
}

function when(iso: string | null): string {
  if (!iso) return "-";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "-" : d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

/** How each manager actually behaves at auction. Remaining budget says what
 * someone *can* spend; this says what they *do* — which is the better guide
 * to whether they'll outbid you. */
function SpendingTable({ spending, usesFaab }: { spending: ManagerSpending[]; usesFaab: boolean }) {
  return (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            <th>Manager</th>
            <th className="num">Moves</th>
            {usesFaab && (
              <>
                <th className="num">Spent</th>
                <th className="num">Claims Won</th>
                <th className="num">Avg Bid</th>
                <th className="num">Biggest</th>
              </>
            )}
          </tr>
        </thead>
        <tbody>
          {spending.map((s) => (
            <tr key={s.team_id}>
              <td>{s.team}</td>
              <td className="num">{s.moves}</td>
              {usesFaab && (
                <>
                  <td className="num">${s.spent}</td>
                  <td className="num">{s.winning_claims}</td>
                  <td className="num">{s.average_bid ? `$${s.average_bid}` : "-"}</td>
                  <td className="num">{s.biggest_bid ? `$${s.biggest_bid}` : "-"}</td>
                </>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function TransactionTable({ transactions }: { transactions: ActivityTransaction[] }) {
  return (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            <th className="num">Wk</th>
            <th>Date</th>
            <th>Manager</th>
            <th>Move</th>
            <th>In</th>
            <th>Out</th>
            <th className="num">Paid</th>
          </tr>
        </thead>
        <tbody>
          {transactions.map((t) => (
            <tr key={t.id}>
              <td className="num">{t.scoring_period_id ?? "-"}</td>
              <td>{when(t.executed_at)}</td>
              <td>{t.team}</td>
              <td>{t.label}</td>
              <td>{names(t.adds)}</td>
              <td>{names(t.drops)}</td>
              <td className="num">{t.bid_amount != null ? `$${t.bid_amount}` : "-"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function ActivityTab({ leagueId }: { leagueId: number }) {
  const [data, setData] = useState<ActivityResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let ignore = false;
    api
      .getActivity(leagueId)
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

  if (error) return <p className="error">{error}</p>;
  if (!data) return <p>Loading...</p>;

  if (data.transactions.length === 0) {
    return (
      <div className="panel">
        <h2>League Activity</h2>
        <p>
          No transaction history yet. It's pulled during a league sync &mdash; sync this league again (or turn on
          auto-sync in Settings) to populate it.
        </p>
      </div>
    );
  }

  return (
    <div className="panel">
      <h2>League Activity</h2>

      <h3>How Each Manager Spends</h3>
      <p className="hint">
        {data.uses_faab
          ? `Across the ${data.transactions.length} most recent moves. What someone has been willing to pay is a better guide to whether they'll outbid you than their remaining balance alone — a manager who wins claims at $3 is not the threat one who has dropped $70 is.`
          : `Across the ${data.transactions.length} most recent moves. This league doesn't use FAAB, so there's no bidding history — just who's most active.`}
      </p>
      <SpendingTable spending={data.spending} usesFaab={data.uses_faab} />

      <h3 style={{ marginTop: "1.5rem" }}>Recent Moves</h3>
      <TransactionTable transactions={data.transactions} />
    </div>
  );
}
