"""Best possible lineup from a set of players and slots.

Filling fantasy slots optimally is an assignment problem, not a sort: a
FLEX-eligible WR might be worth more in FLEX than the RB who'd otherwise
take it, and greedy "fill the most restrictive slot first" can miss that.
For a tracker whose whole output is "you left N points on the bench", the
answer has to actually be the optimum, so this solves it exactly with the
Hungarian algorithm (sizes here are tiny — ~10 slots, ~20 players).
"""

from __future__ import annotations

# Any cost above this means "this pairing isn't allowed" — used instead of
# infinity so the algorithm's arithmetic stays finite.
INELIGIBLE = 1e9


def _hungarian(cost: list[list[float]]) -> list[int]:
    """Minimum-cost assignment of every row to a distinct column.

    Standard O(n^2 m) shortest-augmenting-path formulation with potentials.
    Requires rows <= cols; returns assignment[row] = col.
    """
    n = len(cost)
    m = len(cost[0])
    INF = float("inf")

    u = [0.0] * (n + 1)
    v = [0.0] * (m + 1)
    parent = [0] * (m + 1)  # parent[col] = row currently matched to col
    way = [0] * (m + 1)

    for row in range(1, n + 1):
        parent[0] = row
        col0 = 0
        min_cost = [INF] * (m + 1)
        used = [False] * (m + 1)

        while True:
            used[col0] = True
            row0 = parent[col0]
            delta = INF
            col1 = 0
            for col in range(1, m + 1):
                if used[col]:
                    continue
                current = cost[row0 - 1][col - 1] - u[row0] - v[col]
                if current < min_cost[col]:
                    min_cost[col] = current
                    way[col] = col0
                if min_cost[col] < delta:
                    delta = min_cost[col]
                    col1 = col
            for col in range(m + 1):
                if used[col]:
                    u[parent[col]] += delta
                    v[col] -= delta
                else:
                    min_cost[col] -= delta
            col0 = col1
            if parent[col0] == 0:
                break

        while col0:
            col1 = way[col0]
            parent[col0] = parent[col1]
            col0 = col1

    assignment = [-1] * n
    for col in range(1, m + 1):
        if parent[col] > 0:
            assignment[parent[col] - 1] = col - 1
    return assignment


def optimal_assignment(slot_ids: list[int], players: list[dict]) -> list[int | None]:
    """Assign players to slots to maximize total points.

    `players` are dicts with "eligible_slots" and "points". Returns a list
    parallel to `slot_ids` holding the index of the player in each slot
    (None where no eligible player was available).
    """
    if not slot_ids or not players:
        return [None] * len(slot_ids)

    # Offsetting every score above zero makes filling one more slot always
    # beat leaving it empty, so negative scores (a bad D/ST, a QB with
    # three picks) can't make "start nobody" look optimal.
    offset = max((abs(p["points"] or 0.0) for p in players), default=0.0) + 1.0

    n_slots = len(slot_ids)
    n_players = len(players)
    width = max(n_slots, n_players)

    cost = [[INELIGIBLE] * width for _ in range(n_slots)]
    for i, slot_id in enumerate(slot_ids):
        for j, player in enumerate(players):
            if slot_id in (player.get("eligible_slots") or []):
                cost[i][j] = -((player["points"] or 0.0) + offset)

    assignment = _hungarian(cost)

    result: list[int | None] = []
    for i, j in enumerate(assignment):
        if j < 0 or j >= n_players or cost[i][j] >= INELIGIBLE:
            result.append(None)
        else:
            result.append(j)
    return result


def optimal_lineup(slot_ids: list[int], players: list[dict]) -> tuple[list[tuple[int, dict | None]], float]:
    """Convenience wrapper: (slot_id, player or None) pairs plus the total
    points that lineup would have scored."""
    assignment = optimal_assignment(slot_ids, players)
    pairs = [
        (slot_id, players[player_index] if player_index is not None else None)
        for slot_id, player_index in zip(slot_ids, assignment)
    ]
    total = sum((player["points"] or 0.0) for _, player in pairs if player is not None)
    return pairs, total
