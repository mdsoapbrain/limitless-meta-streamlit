from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


UNKNOWN_DECK_ID = "UNKNOWN"
UNKNOWN_DECK_NAME = "Unknown / Uncategorized"


def parse_api_date(value: str | date | datetime) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.fromisoformat(value.replace("Z", "+00:00")).date()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class AnalysisConfig:
    start_date: date
    end_date: date
    minimum_tournament_players: int = 60
    game: str = "PTCG"
    format: str = "STANDARD"
    platform: str = "PTCGL"
    online_only: bool = True
    decklists_required: bool = True
    match_scope: str = "all"
    request_timeout_seconds: float = 30.0
    request_retries: int = 5
    minimum_request_interval_seconds: float = 0.2
    incomplete_cache_ttl_minutes: int = 15
    incomplete_refresh_days: int = 3
    discovery_cache_ttl_minutes: int = 15
    excluded_tournaments: dict[str, str] = field(default_factory=dict)
    data_dir: Path = Path("data")

    def __post_init__(self) -> None:
        if self.start_date > self.end_date:
            raise ValueError("start_date must be on or before end_date")
        if self.minimum_tournament_players < 0:
            raise ValueError("minimum_tournament_players cannot be negative")
        if self.match_scope not in {"all", "swiss"}:
            raise ValueError("match_scope must be 'all' or 'swiss'")
        if self.incomplete_cache_ttl_minutes < 0:
            raise ValueError("incomplete_cache_ttl_minutes cannot be negative")
        if self.incomplete_refresh_days < 0:
            raise ValueError("incomplete_refresh_days cannot be negative")
        if self.discovery_cache_ttl_minutes < 0:
            raise ValueError("discovery_cache_ttl_minutes cannot be negative")

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def analytics_dir(self) -> Path:
        return self.data_dir / "analytics"

    @property
    def database_path(self) -> Path:
        return self.data_dir / "meta.duckdb"

    def metadata(self) -> dict[str, Any]:
        return {
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "game": self.game,
            "format": self.format,
            "platform": self.platform,
            "minimum_tournament_players": self.minimum_tournament_players,
            "match_scope": self.match_scope,
            "excluded_tournament_count": len(self.excluded_tournaments),
        }


@dataclass
class FetchResult:
    tournaments: list[dict[str, Any]] = field(default_factory=list)
    audit: list[dict[str, Any]] = field(default_factory=list)
    network_requests: int = 0
    cache_hits: int = 0


@dataclass(frozen=True)
class TopCutResult:
    explicit_elimination_phase: bool
    detected: bool
    phase_label: str | None
    players: frozenset[str]
    suspicious: bool
    reason: str | None
    first_phase_player_count: int = 0

    @property
    def size(self) -> int:
        return len(self.players)
