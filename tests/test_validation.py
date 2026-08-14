from __future__ import annotations

import pandas as pd

from limitless_meta.metrics import compute_metrics
from limitless_meta.validation import validate_analytics


def test_directional_matchup_symmetry_passes() -> None:
    entries = pd.DataFrame(
        [
            {"tournament_id": "t", "player_id": "a", "deck_id": "A", "deck_name": "A", "top_cut": None},
            {"tournament_id": "t", "player_id": "b", "deck_id": "B", "deck_name": "B", "top_cut": None},
        ]
    )
    matches = pd.DataFrame(
        [
            {
                "match_id": "m",
                "tournament_id": "t",
                "phase": 1,
                "phase_type": "SWISS",
                "round": 1,
                "table_or_match": "1",
                "player_a": "a",
                "player_b": "b",
                "winner": "a",
                "result": "A_WIN",
            }
        ]
    )
    tournaments = pd.DataFrame(
        [{"tournament_id": "t", "players": 2, "top_cut_detected": False, "top_cut_size": None}]
    )
    summary, matchups = compute_metrics(tournaments, entries, matches)
    assert validate_analytics(tournaments, entries, matches, summary, matchups) == []

