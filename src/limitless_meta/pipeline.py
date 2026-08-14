from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from .api import LimitlessAPI
from .database import write_database
from .export import export_analytics
from .ingest import fetch_dataset, normalize_dataset
from .metrics import compute_metrics
from .models import AnalysisConfig, FetchResult, utc_now_iso
from .validation import validate_analytics, validation_report


@dataclass
class PipelineResult:
    fetch: FetchResult
    metadata: dict[str, Any]
    validation: dict[str, Any]
    outputs: dict[str, Path]


def make_api(
    config: AnalysisConfig,
    refresh: bool = False,
    progress: Callable[[str], None] | None = None,
) -> LimitlessAPI:
    return LimitlessAPI(
        config.raw_dir,
        refresh=refresh,
        timeout=config.request_timeout_seconds,
        retries=config.request_retries,
        minimum_interval=config.minimum_request_interval_seconds,
        progress=progress,
    )


def run_fetch(
    config: AnalysisConfig,
    *,
    refresh: bool = False,
    progress: Callable[[str], None] | None = None,
) -> FetchResult:
    return fetch_dataset(make_api(config, refresh=refresh, progress=progress), config)


def _count_valid_matches(
    matches: pd.DataFrame, entries: pd.DataFrame, match_scope: str
) -> int:
    scoped = matches
    if match_scope == "swiss" and not matches.empty:
        scoped = matches[matches["phase_type"].astype(str).str.upper() == "SWISS"]
    if scoped.empty or entries.empty:
        return 0
    entry_keys = set(zip(entries["tournament_id"], entries["player_id"]))
    valid = scoped[
        scoped["result"].isin(["A_WIN", "B_WIN"])
        & scoped["player_a"].notna()
        & scoped["player_b"].notna()
    ]
    return sum(
        (row.tournament_id, row.player_a) in entry_keys
        and (row.tournament_id, row.player_b) in entry_keys
        for row in valid.itertuples(index=False)
    )


def run_analysis(
    config: AnalysisConfig,
    *,
    refresh: bool = False,
    progress: Callable[[str], None] | None = None,
) -> PipelineResult:
    fetched = run_fetch(config, refresh=refresh, progress=progress)
    tables = normalize_dataset(fetched)
    deck_summary, matchups = compute_metrics(
        tables["tournaments"],
        tables["entries"],
        tables["matches"],
        match_scope=config.match_scope,
    )
    tables["deck_summary"] = deck_summary
    tables["matchups_long"] = matchups

    valid_match_count = _count_valid_matches(
        tables["matches"], tables["entries"], config.match_scope
    )
    conversion_eligible_tournament_count = int(
        tables["tournaments"]["top_cut_detected"].fillna(False).sum()
    ) if not tables["tournaments"].empty else 0
    metadata = {
        "generated_at": utc_now_iso(),
        **config.metadata(),
        "eligible_tournament_count": len(tables["tournaments"]),
        "eligible_entry_count": len(tables["entries"]),
        "valid_match_count": valid_match_count,
        "conversion_eligible_tournament_count": conversion_eligible_tournament_count,
        "network_requests": fetched.network_requests,
        "cache_hits": fetched.cache_hits,
    }
    tables["run_metadata"] = pd.DataFrame(
        [{key: metadata[key] for key in (
            "generated_at",
            "start_date",
            "end_date",
            "game",
            "format",
            "platform",
            "minimum_tournament_players",
            "match_scope",
            "eligible_tournament_count",
            "eligible_entry_count",
            "valid_match_count",
            "conversion_eligible_tournament_count",
        )}]
    )

    issues = validate_analytics(
        tables["tournaments"],
        tables["entries"],
        tables["matches"],
        deck_summary,
        matchups,
    )
    report = validation_report(issues)
    write_database(config.database_path, tables)
    outputs = export_analytics(config.analytics_dir, tables, metadata, report)
    return PipelineResult(fetched, metadata, report, outputs)
