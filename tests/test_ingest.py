from __future__ import annotations

from datetime import date

from limitless_meta.ingest import (
    fetch_dataset,
    normalize_dataset,
    normalize_pairing,
    tournament_is_complete,
)
from limitless_meta.models import AnalysisConfig, FetchResult


def test_pairing_result_normalization() -> None:
    assert normalize_pairing({"player1": "a", "player2": "b", "winner": "a"}) == "A_WIN"
    assert normalize_pairing({"player1": "a", "player2": "b", "winner": "b"}) == "B_WIN"
    assert normalize_pairing({"player1": "a", "player2": "b", "winner": 0}) == "TIE"
    assert normalize_pairing({"player1": "a", "player2": "b", "winner": -1}) == "DOUBLE_LOSS"
    assert normalize_pairing({"player1": "a", "winner": "a"}) == "BYE"
    assert normalize_pairing({"player1": "a", "winner": -1}) == "INVALID"


class FakeAPI:
    network_requests = 0
    cache_hits = 0

    def tournaments(
        self, game: str, format_name: str, page: int, *, force_refresh: bool = False
    ):
        if page:
            return []
        return [
            {
                "id": "eligible",
                "name": "Eligible",
                "date": "2026-08-10T00:00:00.000Z",
                "game": game,
                "format": format_name,
                "players": 64,
            },
            {
                "id": "small",
                "name": "Small",
                "date": "2026-08-10T00:00:00.000Z",
                "game": game,
                "format": format_name,
                "players": 8,
            },
        ]

    def tournament_details(self, tournament_id: str, *, force_refresh: bool = False):
        return {
            "id": tournament_id,
            "name": "Eligible",
            "date": "2026-08-10T00:00:00.000Z",
            "game": "PTCG",
            "format": "STANDARD",
            "players": 64,
            "organizer": {"id": 1, "name": "Org"},
            "platform": "PTCGL",
            "decklists": True,
            "isOnline": True,
            "phases": [{"phase": 1, "type": "SWISS"}],
        }

    def tournament_standings(self, tournament_id: str, *, force_refresh: bool = False):
        return []

    def tournament_pairings(self, tournament_id: str, *, force_refresh: bool = False):
        return []


def test_discovery_filters_before_large_payload_download(tmp_path) -> None:
    config = AnalysisConfig(
        start_date=date(2026, 8, 10),
        end_date=date(2026, 8, 10),
        data_dir=tmp_path,
    )
    result = fetch_dataset(FakeAPI(), config)
    assert len(result.tournaments) == 1
    reasons = {row["tournament_id"]: row["exclusion_reason"] for row in result.audit}
    assert reasons["eligible"] is None
    assert reasons["small"] == "too few players"


def test_manual_exclusion_is_auditable_and_skips_payloads(tmp_path) -> None:
    config = AnalysisConfig(
        start_date=date(2026, 8, 10),
        end_date=date(2026, 8, 10),
        excluded_tournaments={"eligible": "special rules"},
        data_dir=tmp_path,
    )
    result = fetch_dataset(FakeAPI(), config)
    assert result.tournaments == []
    audit = {row["tournament_id"]: row for row in result.audit}
    assert audit["eligible"]["exclusion_reason"] == "manual exclusion: special rules"
    assert not audit["eligible"]["included"]


def test_completion_requires_every_entry_and_placing() -> None:
    completed = [{"placing": 1}, {"placing": 2}]
    incomplete = [{"placing": 1}, {"placing": None}]
    assert tournament_is_complete(completed, 2)
    assert not tournament_is_complete(completed, 3)
    assert not tournament_is_complete(incomplete, 2)


def test_double_bracket_match_identifier_is_preserved() -> None:
    fetched = FetchResult(
        tournaments=[
            {
                "details": {
                    "id": "bracket",
                    "name": "Bracket",
                    "date": "2026-08-10T00:00:00Z",
                    "game": "PTCG",
                    "format": "STANDARD",
                    "platform": "PTCGL",
                    "players": 2,
                    "organizer": {},
                    "isOnline": True,
                    "decklists": True,
                    "phases": [{"phase": 1, "type": "DOUBLE_BRACKET"}],
                },
                "standings": [
                    {
                        "player": "a",
                        "name": "Alice",
                        "placing": 1,
                        "deck": {"id": "A", "name": "A"},
                        "decklist": {
                            "pokemon": [
                                {"count": 4, "set": "TST", "number": "1", "name": "Testmon"}
                            ],
                            "trainer": [],
                            "energy": [],
                        },
                    },
                    {"player": "b", "placing": 2, "deck": {"id": "B", "name": "B"}},
                ],
                "pairings": [
                    {
                        "phase": 1,
                        "round": 1,
                        "match": "W1-1",
                        "player1": "a",
                        "player2": "b",
                        "winner": "a",
                    }
                ],
            }
        ],
        audit=[
            {
                "tournament_id": "bracket",
                "name": "Bracket",
                "date": date(2026, 8, 10),
                "players": 2,
                "included": True,
            }
        ],
    )
    tables = normalize_dataset(fetched)
    assert tables["matches"].iloc[0]["table_or_match"] == "W1-1"
    assert tables["entries"]["top_cut"].isna().all()
    assert len(tables["decklists"]) == 1
    assert tables["decklists"].iloc[0]["player_name"] == "Alice"
    assert '"name":"Testmon"' in tables["decklists"].iloc[0]["decklist_json"]
