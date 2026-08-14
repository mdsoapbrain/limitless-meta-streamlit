from __future__ import annotations

from typing import Any

from .models import AnalysisConfig, parse_api_date


def detail_exclusion_reason(details: dict[str, Any], config: AnalysisConfig) -> str | None:
    tournament_date = parse_api_date(details["date"])
    if tournament_date < config.start_date or tournament_date > config.end_date:
        return "outside date range"
    if str(details.get("game", "")).upper() != config.game.upper():
        return "wrong game"
    if str(details.get("format", "")).upper() != config.format.upper():
        return "wrong format"
    if config.online_only and details.get("isOnline") is not True:
        return "not online"
    if str(details.get("platform", "")).upper() != config.platform.upper():
        return "wrong platform"
    if config.decklists_required and details.get("decklists") is not True:
        return "no decklists"
    if int(details.get("players") or 0) < config.minimum_tournament_players:
        return "too few players"
    return None


def summary_exclusion_reason(summary: dict[str, Any], config: AnalysisConfig) -> str | None:
    tournament_date = parse_api_date(summary["date"])
    if tournament_date < config.start_date or tournament_date > config.end_date:
        return "outside date range"
    if str(summary.get("game", "")).upper() != config.game.upper():
        return "wrong game"
    if str(summary.get("format", "")).upper() != config.format.upper():
        return "wrong format"
    if int(summary.get("players") or 0) < config.minimum_tournament_players:
        return "too few players"
    return None

