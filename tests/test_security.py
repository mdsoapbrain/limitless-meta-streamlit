from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from limitless_meta.api import LimitlessAPI, LimitlessAPIError
from limitless_meta.cache import JsonCache
from limitless_meta.database import (
    read_decklists_for_deck,
    read_tables,
    write_database,
)
from limitless_meta.security import dataframe_to_safe_csv_bytes, escape_markdown


def test_csv_export_neutralizes_spreadsheet_formulas() -> None:
    frame = pd.DataFrame(
        {
            "Player": ["=HYPERLINK(\"https://example.com\")", "+cmd", "safe"],
            "Wins": [1, -2, 3],
        }
    )

    exported = dataframe_to_safe_csv_bytes(frame).decode("utf-8")

    assert "'=HYPERLINK" in exported
    assert "\n'+cmd,-2\n" in exported
    assert "\nsafe,3\n" in exported
    assert frame.iloc[0]["Player"].startswith("=")


def test_markdown_escape_neutralizes_links_and_emphasis() -> None:
    assert escape_markdown("**[click](https://example.com)**") == (
        r"\*\*\[click\]\(https://example\.com\)\*\*"
    )


def test_cache_rejects_paths_outside_root(tmp_path: Path) -> None:
    cache = JsonCache(tmp_path / "raw")
    cache.write("details/event-1.json", {"ok": True}, url="https://example.com")
    assert cache.read("details/event-1.json") == {"ok": True}
    assert cache.metadata_path("details/event-1.json").is_file()

    with pytest.raises(ValueError):
        cache.path("../outside.json")
    with pytest.raises(ValueError):
        cache.path(tmp_path / "absolute.json")


def test_api_rejects_invalid_tournament_id(tmp_path: Path) -> None:
    api = LimitlessAPI(tmp_path)
    with pytest.raises(LimitlessAPIError, match="Invalid tournament ID"):
        api.tournament_details("../escape")


def test_database_table_allowlist_and_lazy_decklist_query(tmp_path: Path) -> None:
    database = tmp_path / "test.duckdb"
    write_database(
        database,
        {
            "entries": pd.DataFrame(
                [
                    {
                        "tournament_id": "event-1",
                        "player_id": "alice",
                        "deck_id": "deck-a",
                    },
                    {
                        "tournament_id": "event-1",
                        "player_id": "bob",
                        "deck_id": "deck-b",
                    },
                ]
            ),
            "decklists": pd.DataFrame(
                [
                    {
                        "tournament_id": "event-1",
                        "player_id": "alice",
                        "player_name": "Alice",
                        "decklist_json": '{"pokemon":[]}',
                    },
                    {
                        "tournament_id": "event-1",
                        "player_id": "bob",
                        "player_name": "Bob",
                        "decklist_json": '{"pokemon":[]}',
                    },
                ]
            ),
        },
    )

    selected = read_decklists_for_deck(database, "deck-a", ["event-1"])
    assert selected["player_id"].tolist() == ["alice"]

    with pytest.raises(KeyError, match="Unknown table"):
        read_tables(database, ['entries"; DROP TABLE entries; --'])
