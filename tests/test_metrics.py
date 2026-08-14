from __future__ import annotations

import math

import pandas as pd

from limitless_meta.metrics import (
    compute_deck_period_series,
    compute_metrics,
    select_representative_decklists,
)


def _synthetic_entries() -> pd.DataFrame:
    rows = []
    for deck_id, count in (("A", 20), ("B", 10), ("C", 1), ("OTHER", 69)):
        for index in range(count):
            rows.append(
                {
                    "tournament_id": "t1",
                    "player_id": f"{deck_id}_{index}",
                    "deck_id": deck_id,
                    "deck_name": deck_id,
                    "top_cut": None,
                }
            )
    return pd.DataFrame(rows)


def _match(match_id: int, player_a: str, player_b: str, result: str) -> dict:
    return {
        "match_id": str(match_id),
        "tournament_id": "t1",
        "phase_type": "SWISS",
        "player_a": player_a,
        "player_b": player_b,
        "result": result,
    }


def test_weighted_impact_uses_observed_opponent_representation() -> None:
    entries = _synthetic_entries()
    matches = []
    match_id = 0
    for index in range(43):
        matches.append(_match(match_id, f"A_{index % 20}", f"B_{index % 10}", "A_WIN"))
        match_id += 1
    for index in range(57):
        matches.append(_match(match_id, f"A_{index % 20}", f"B_{index % 10}", "B_WIN"))
        match_id += 1
    for index in range(3):
        matches.append(_match(match_id, f"A_{index}", "C_0", "A_WIN"))
        match_id += 1
    for index in range(7):
        matches.append(_match(match_id, f"A_{index}", "C_0", "B_WIN"))
        match_id += 1

    summary, matchups = compute_metrics(
        pd.DataFrame([{"tournament_id": "t1"}]),
        entries,
        pd.DataFrame(matches),
    )
    a_vs_b = matchups[(matchups.deck_a == "A") & (matchups.deck_b == "B")].iloc[0]
    a_vs_c = matchups[(matchups.deck_a == "A") & (matchups.deck_b == "C")].iloc[0]
    assert math.isclose(a_vs_b.raw_win_rate, 0.43)
    assert math.isclose(a_vs_b.weighted_impact, -0.007)
    assert math.isclose(a_vs_b.weighted_impact * 100, -0.70)
    assert math.isclose(a_vs_c.raw_win_rate, 0.30)
    assert math.isclose(a_vs_c.weighted_impact * 100, -0.20)
    assert abs(a_vs_b.weighted_impact) > abs(a_vs_c.weighted_impact)
    assert math.isclose(summary.representation.sum(), 1.0)


def test_ties_are_retained_but_excluded_from_n_and_raw_wr() -> None:
    entries = _synthetic_entries().iloc[:30]
    matches = pd.DataFrame(
        [
            _match(1, "A_0", "B_0", "A_WIN"),
            _match(2, "A_1", "B_1", "TIE"),
            _match(3, "A_2", "B_2", "DOUBLE_LOSS"),
            _match(4, "A_3", None, "BYE"),
        ]
    )
    _, matchups = compute_metrics(pd.DataFrame(), entries, matches)
    row = matchups[(matchups.deck_a == "A") & (matchups.deck_b == "B")].iloc[0]
    assert row.wins == 1
    assert row.losses == 0
    assert row.ties == 1
    assert row.double_losses == 1
    assert row.all_matches == 3
    assert row.n_decided == 1
    assert row.raw_win_rate == 1.0


def test_top_cut_denominator_excludes_swiss_only_tournament_entries() -> None:
    rows = []
    for index in range(12):
        rows.append(
            {
                "tournament_id": "cut",
                "player_id": f"a{index}",
                "deck_id": "A",
                "deck_name": "A",
                "top_cut": index < 3,
            }
        )
    for index in range(20):
        rows.append(
            {
                "tournament_id": "cut",
                "player_id": f"b{index}",
                "deck_id": "B",
                "deck_name": "B",
                "top_cut": index < 1,
            }
        )
    rows.append(
        {
            "tournament_id": "swiss",
            "player_id": "a_swiss",
            "deck_id": "A",
            "deck_name": "A",
            "top_cut": None,
        }
    )
    summary, _ = compute_metrics(pd.DataFrame(), pd.DataFrame(rows), pd.DataFrame())
    deck_a = summary[summary.deck_id == "A"].iloc[0]
    deck_b = summary[summary.deck_id == "B"].iloc[0]
    assert deck_a.top_cut_entries == 3
    assert deck_a.conversion_eligible_entries == 12
    assert deck_a.top_cut_rate == 0.25
    assert deck_b.top_cut_rate == 0.05


def test_period_series_uses_independent_observed_denominators() -> None:
    tournaments = pd.DataFrame(
        [
            {"tournament_id": "w1", "date": "2026-08-01", "players": 2},
            {"tournament_id": "w2", "date": "2026-08-08", "players": 4},
        ]
    )
    entries = pd.DataFrame(
        [
            {"tournament_id": "w1", "player_id": "a1", "deck_id": "A", "deck_name": "A", "top_cut": None},
            {"tournament_id": "w1", "player_id": "b1", "deck_id": "B", "deck_name": "B", "top_cut": None},
            {"tournament_id": "w2", "player_id": "a2", "deck_id": "A", "deck_name": "A", "top_cut": None},
            {"tournament_id": "w2", "player_id": "b2", "deck_id": "B", "deck_name": "B", "top_cut": None},
            {"tournament_id": "w2", "player_id": "b3", "deck_id": "B", "deck_name": "B", "top_cut": None},
            {"tournament_id": "w2", "player_id": "b4", "deck_id": "B", "deck_name": "B", "top_cut": None},
        ]
    )
    series = compute_deck_period_series(
        tournaments,
        entries,
        pd.DataFrame(),
        deck_id="A",
        start_date=pd.Timestamp("2026-08-01").date(),
        end_date=pd.Timestamp("2026-08-14").date(),
        minimum_players=0,
        match_scope="all",
    )
    assert series["representation"].tolist() == [0.5, 0.25]


def test_representative_decklists_pick_best_entry_then_largest_events() -> None:
    tournaments = pd.DataFrame(
        [
            {"tournament_id": "large", "name": "Large", "date": "2026-08-10", "players": 200},
            {"tournament_id": "medium", "name": "Medium", "date": "2026-08-11", "players": 120},
            {"tournament_id": "small", "name": "Small", "date": "2026-08-12", "players": 80},
        ]
    )
    entries = pd.DataFrame(
        [
            {
                "tournament_id": "large", "player_id": "large_worse", "deck_id": "A",
                "deck_name": "Deck A", "placing": 9, "wins": 8, "losses": 2, "ties": 0,
            },
            {
                "tournament_id": "large", "player_id": "large_best", "deck_id": "A",
                "deck_name": "Deck A", "placing": 2, "wins": 10, "losses": 1, "ties": 0,
            },
            {
                "tournament_id": "medium", "player_id": "medium_best", "deck_id": "A",
                "deck_name": "Deck A", "placing": 1, "wins": 9, "losses": 0, "ties": 0,
            },
            {
                "tournament_id": "small", "player_id": "small_best", "deck_id": "A",
                "deck_name": "Deck A", "placing": None, "wins": 8, "losses": 0, "ties": 0,
            },
        ]
    )
    decklists = pd.DataFrame(
        [
            {
                "tournament_id": row["tournament_id"],
                "player_id": row["player_id"],
                "player_name": row["player_id"],
                "decklist_json": '{"pokemon":[]}',
            }
            for row in entries.to_dict("records")
        ]
    )

    selected = select_representative_decklists(
        tournaments, entries, decklists, deck_id="A", limit=2
    )

    assert selected["tournament_id"].tolist() == ["large", "medium"]
    assert selected["player_id"].tolist() == ["large_best", "medium_best"]
