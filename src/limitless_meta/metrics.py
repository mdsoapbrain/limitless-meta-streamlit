from __future__ import annotations

from itertools import product
from datetime import date, timedelta
from typing import Any

import pandas as pd


DECK_SUMMARY_COLUMNS = [
    "deck_id",
    "deck_name",
    "entries",
    "representation_numerator",
    "representation_denominator",
    "representation",
    "wins",
    "losses",
    "ties",
    "n_decided",
    "overall_raw_win_rate",
    "top_cut_entries",
    "conversion_eligible_entries",
    "top_cut_rate",
    "tournament_count",
]

MATCHUP_COLUMNS = [
    "deck_a",
    "deck_a_name",
    "deck_b",
    "deck_b_name",
    "wins",
    "losses",
    "ties",
    "double_losses",
    "all_matches",
    "n_decided",
    "raw_win_rate",
    "opponent_representation",
    "opponent_representation_numerator",
    "opponent_representation_denominator",
    "weighted_impact",
    "opponent_top_cut_entries",
    "opponent_conversion_eligible_entries",
    "opponent_top_cut_rate",
]

REPRESENTATIVE_DECKLIST_COLUMNS = [
    "tournament_id",
    "tournament_name",
    "tournament_date",
    "players",
    "player_id",
    "player_name",
    "deck_id",
    "deck_name",
    "placing",
    "wins",
    "losses",
    "ties",
    "decklist_json",
]


def _canonical_names(entries: pd.DataFrame) -> dict[str, str]:
    counts = (
        entries.groupby(["deck_id", "deck_name"], dropna=False)
        .size()
        .reset_index(name="count")
        .sort_values(["deck_id", "count", "deck_name"], ascending=[True, False, True])
    )
    return (
        counts.drop_duplicates("deck_id")
        .set_index("deck_id")["deck_name"]
        .astype(str)
        .to_dict()
    )


def _directional_records(
    entries: pd.DataFrame, matches: pd.DataFrame, match_scope: str
) -> pd.DataFrame:
    columns = [
        "deck_a",
        "deck_b",
        "wins",
        "losses",
        "ties",
        "double_losses",
        "all_matches",
    ]
    if entries.empty or matches.empty:
        return pd.DataFrame(columns=columns)
    if match_scope not in {"all", "swiss"}:
        raise ValueError("match_scope must be 'all' or 'swiss'")

    scoped = matches
    if match_scope == "swiss":
        scoped = matches[matches["phase_type"].astype(str).str.upper() == "SWISS"]

    lookup = entries.set_index(["tournament_id", "player_id"])["deck_id"].to_dict()
    records: list[dict[str, Any]] = []
    for match in scoped.itertuples(index=False):
        if match.result not in {"A_WIN", "B_WIN", "TIE", "DOUBLE_LOSS"}:
            continue
        if not match.player_a or not match.player_b:
            continue
        deck_a = lookup.get((match.tournament_id, match.player_a))
        deck_b = lookup.get((match.tournament_id, match.player_b))
        if deck_a is None or deck_b is None:
            continue

        first = dict(wins=0, losses=0, ties=0, double_losses=0, all_matches=1)
        second = dict(first)
        if match.result == "A_WIN":
            first["wins"] = 1
            second["losses"] = 1
        elif match.result == "B_WIN":
            first["losses"] = 1
            second["wins"] = 1
        elif match.result == "TIE":
            first["ties"] = 1
            second["ties"] = 1
        else:
            first["double_losses"] = 1
            second["double_losses"] = 1
        records.append({"deck_a": deck_a, "deck_b": deck_b, **first})
        records.append({"deck_a": deck_b, "deck_b": deck_a, **second})
    return pd.DataFrame(records, columns=columns)


def compute_metrics(
    tournaments: pd.DataFrame,
    entries: pd.DataFrame,
    matches: pd.DataFrame,
    *,
    match_scope: str = "all",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if entries.empty:
        return (
            pd.DataFrame(columns=DECK_SUMMARY_COLUMNS),
            pd.DataFrame(columns=MATCHUP_COLUMNS),
        )

    names = _canonical_names(entries)
    total_entries = len(entries)
    base = (
        entries.groupby("deck_id")
        .agg(entries=("player_id", "size"), tournament_count=("tournament_id", "nunique"))
        .reset_index()
    )
    base["deck_name"] = base["deck_id"].map(names)
    base["representation_numerator"] = base["entries"]
    base["representation_denominator"] = total_entries
    base["representation"] = base["entries"] / total_entries

    conversion_eligible = entries[entries["top_cut"].notna()]
    eligible_counts = conversion_eligible.groupby("deck_id").size().to_dict()
    cut_counts = (
        conversion_eligible[conversion_eligible["top_cut"].astype(bool)]
        .groupby("deck_id")
        .size()
        .to_dict()
    )
    base["conversion_eligible_entries"] = base["deck_id"].map(eligible_counts).fillna(0).astype(int)
    base["top_cut_entries"] = base["deck_id"].map(cut_counts).fillna(0).astype(int)
    base["top_cut_rate"] = base.apply(
        lambda row: row["top_cut_entries"] / row["conversion_eligible_entries"]
        if row["conversion_eligible_entries"]
        else None,
        axis=1,
    )

    directional = _directional_records(entries, matches, match_scope)
    if directional.empty:
        overall = pd.DataFrame(columns=["deck_id", "wins", "losses", "ties"])
    else:
        overall = (
            directional.groupby("deck_a")[["wins", "losses", "ties"]]
            .sum()
            .reset_index()
            .rename(columns={"deck_a": "deck_id"})
        )
    base = base.merge(overall, how="left", on="deck_id")
    for column in ("wins", "losses", "ties"):
        base[column] = base[column].fillna(0).astype(int)
    base["n_decided"] = base["wins"] + base["losses"]
    base["overall_raw_win_rate"] = base.apply(
        lambda row: row["wins"] / row["n_decided"] if row["n_decided"] else None,
        axis=1,
    )
    deck_summary = base[DECK_SUMMARY_COLUMNS].sort_values(
        ["entries", "deck_name"], ascending=[False, True]
    ).reset_index(drop=True)

    if directional.empty:
        matchup_counts: dict[tuple[str, str], dict[str, int]] = {}
    else:
        grouped = (
            directional.groupby(["deck_a", "deck_b"])[
                ["wins", "losses", "ties", "double_losses", "all_matches"]
            ]
            .sum()
            .reset_index()
        )
        matchup_counts = {
            (row.deck_a, row.deck_b): {
                "wins": int(row.wins),
                "losses": int(row.losses),
                "ties": int(row.ties),
                "double_losses": int(row.double_losses),
                "all_matches": int(row.all_matches),
            }
            for row in grouped.itertuples(index=False)
        }

    summary_lookup = deck_summary.set_index("deck_id").to_dict("index")
    matchup_rows: list[dict[str, Any]] = []
    deck_ids = deck_summary["deck_id"].tolist()
    for deck_a, deck_b in product(deck_ids, repeat=2):
        counts = matchup_counts.get(
            (deck_a, deck_b),
            {"wins": 0, "losses": 0, "ties": 0, "double_losses": 0, "all_matches": 0},
        )
        n_decided = counts["wins"] + counts["losses"]
        raw_win_rate = counts["wins"] / n_decided if n_decided else None
        opponent = summary_lookup[deck_b]
        weighted_impact = (
            opponent["representation"] * (raw_win_rate - 0.5)
            if raw_win_rate is not None
            else None
        )
        matchup_rows.append(
            {
                "deck_a": deck_a,
                "deck_a_name": names[deck_a],
                "deck_b": deck_b,
                "deck_b_name": names[deck_b],
                **counts,
                "n_decided": n_decided,
                "raw_win_rate": raw_win_rate,
                "opponent_representation": opponent["representation"],
                "opponent_representation_numerator": opponent["representation_numerator"],
                "opponent_representation_denominator": opponent["representation_denominator"],
                "weighted_impact": weighted_impact,
                "opponent_top_cut_entries": opponent["top_cut_entries"],
                "opponent_conversion_eligible_entries": opponent[
                    "conversion_eligible_entries"
                ],
                "opponent_top_cut_rate": opponent["top_cut_rate"],
            }
        )
    matchups = pd.DataFrame(matchup_rows, columns=MATCHUP_COLUMNS)
    return deck_summary, matchups


def filter_observed_window(
    tournaments: pd.DataFrame,
    entries: pd.DataFrame,
    matches: pd.DataFrame,
    *,
    start_date: date,
    end_date: date,
    minimum_players: int,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    dated = tournaments.copy()
    dated["date"] = pd.to_datetime(dated["date"]).dt.date
    selected_tournaments = dated[
        (dated["date"] >= start_date)
        & (dated["date"] <= end_date)
        & (dated["players"] >= minimum_players)
    ].copy()
    tournament_ids = set(selected_tournaments["tournament_id"])
    selected_entries = (
        entries[entries["tournament_id"].isin(tournament_ids)].copy()
        if "tournament_id" in entries.columns
        else entries.copy()
    )
    selected_matches = (
        matches[matches["tournament_id"].isin(tournament_ids)].copy()
        if "tournament_id" in matches.columns
        else matches.copy()
    )
    return (
        selected_tournaments,
        selected_entries,
        selected_matches,
    )


def select_representative_decklists(
    tournaments: pd.DataFrame,
    entries: pd.DataFrame,
    decklists: pd.DataFrame,
    *,
    deck_id: str,
    limit: int = 3,
) -> pd.DataFrame:
    """Pick one best-finishing list per event, then prefer the largest events."""
    if limit <= 0:
        return pd.DataFrame(columns=REPRESENTATIVE_DECKLIST_COLUMNS)
    if tournaments.empty or entries.empty or decklists.empty:
        return pd.DataFrame(columns=REPRESENTATIVE_DECKLIST_COLUMNS)

    selected_entries = entries[entries["deck_id"] == deck_id].copy()
    if selected_entries.empty:
        return pd.DataFrame(columns=REPRESENTATIVE_DECKLIST_COLUMNS)

    available = selected_entries.merge(
        decklists[["tournament_id", "player_id", "player_name", "decklist_json"]],
        on=["tournament_id", "player_id"],
        how="inner",
    )
    event_data = tournaments[
        ["tournament_id", "name", "date", "players"]
    ].rename(columns={"name": "tournament_name", "date": "tournament_date"})
    available = available.merge(event_data, on="tournament_id", how="inner")
    if available.empty:
        return pd.DataFrame(columns=REPRESENTATIVE_DECKLIST_COLUMNS)

    available["_placing_missing"] = available["placing"].isna()
    available["_placing_sort"] = pd.to_numeric(
        available["placing"], errors="coerce"
    ).astype("float64").fillna(float("inf"))
    for column in ("wins", "losses", "ties", "players"):
        available[column] = pd.to_numeric(available[column], errors="coerce").fillna(0)

    best_per_event = (
        available.sort_values(
            [
                "tournament_id",
                "_placing_missing",
                "_placing_sort",
                "wins",
                "losses",
                "ties",
                "player_id",
            ],
            ascending=[True, True, True, False, True, True, True],
        )
        .drop_duplicates("tournament_id", keep="first")
        .sort_values(
            [
                "players",
                "tournament_date",
                "_placing_missing",
                "_placing_sort",
                "wins",
                "tournament_id",
            ],
            ascending=[False, False, True, True, False, True],
        )
        .head(limit)
    )
    return best_per_event[REPRESENTATIVE_DECKLIST_COLUMNS].reset_index(drop=True)


def compute_deck_period_series(
    tournaments: pd.DataFrame,
    entries: pd.DataFrame,
    matches: pd.DataFrame,
    *,
    deck_id: str,
    start_date: date,
    end_date: date,
    minimum_players: int,
    match_scope: str,
    bucket_days: int = 7,
) -> pd.DataFrame:
    if bucket_days <= 0:
        raise ValueError("bucket_days must be positive")
    rows: list[dict[str, Any]] = []
    bucket_start = start_date
    while bucket_start <= end_date:
        bucket_end = min(end_date, bucket_start + timedelta(days=bucket_days - 1))
        period_tournaments, period_entries, period_matches = filter_observed_window(
            tournaments,
            entries,
            matches,
            start_date=bucket_start,
            end_date=bucket_end,
            minimum_players=minimum_players,
        )
        summary, _ = compute_metrics(
            period_tournaments,
            period_entries,
            period_matches,
            match_scope=match_scope,
        )
        selected = summary[summary["deck_id"] == deck_id]
        if selected.empty:
            values = {
                "entries": 0,
                "representation": 0.0 if len(period_entries) else None,
                "overall_raw_win_rate": None,
                "top_cut_rate": None,
                "wins": 0,
                "losses": 0,
            }
        else:
            row = selected.iloc[0]
            values = {key: row[key] for key in (
                "entries",
                "representation",
                "overall_raw_win_rate",
                "top_cut_rate",
                "wins",
                "losses",
            )}
        rows.append(
            {
                "period_start": bucket_start,
                "period_end": bucket_end,
                "period": f"{bucket_start.isoformat()} – {bucket_end.isoformat()}",
                "eligible_tournaments": len(period_tournaments),
                "eligible_entries": len(period_entries),
                **values,
            }
        )
        bucket_start = bucket_end + timedelta(days=1)
    return pd.DataFrame(rows)
