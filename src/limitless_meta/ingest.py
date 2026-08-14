from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

import pandas as pd

from .api import LimitlessAPI
from .filters import detail_exclusion_reason, summary_exclusion_reason
from .models import (
    AnalysisConfig,
    FetchResult,
    UNKNOWN_DECK_ID,
    UNKNOWN_DECK_NAME,
    parse_api_date,
    utc_now_iso,
)
from .topcut import detect_top_cut


def _audit_row(source: dict[str, Any]) -> dict[str, Any]:
    organizer = source.get("organizer") or {}
    return {
        "tournament_id": str(source.get("id") or ""),
        "name": source.get("name"),
        "date": parse_api_date(source["date"]),
        "players": int(source.get("players") or 0),
        "organizer": organizer.get("name") if isinstance(organizer, dict) else None,
        "game": source.get("game"),
        "format": source.get("format"),
        "platform": source.get("platform"),
        "included": False,
        "exclusion_reason": None,
        "top_cut_detected": None,
        "top_cut_size": None,
        "is_complete": None,
    }


def tournament_is_complete(
    standings: list[dict[str, Any]], expected_players: int | None = None
) -> bool:
    if not standings:
        return False
    if expected_players and len(standings) < expected_players:
        return False
    return all(row.get("placing") is not None for row in standings)


def _report(api: Any, message: str) -> None:
    reporter = getattr(api, "report_progress", None)
    if reporter is not None:
        reporter(message)


def _refresh_incomplete_cache(
    api: LimitlessAPI,
    tournament_id: str,
    tournament_date: date,
    expected_players: int,
    ttl_minutes: int,
    refresh_days: int,
) -> bool:
    if tournament_date < date.today() - timedelta(days=refresh_days):
        return False
    cache = getattr(api, "cache", None)
    relative = f"standings/{tournament_id}.json"
    if cache is None or not cache.exists(relative):
        return False
    cached_standings = cache.read(relative)
    if not isinstance(cached_standings, list):
        return True
    if tournament_is_complete(cached_standings, expected_players):
        return False
    age = cache.age_seconds(relative)
    return age is None or age >= ttl_minutes * 60


def _refresh_discovery_cache(
    api: LimitlessAPI, config: AnalysisConfig, page: int
) -> bool:
    if config.end_date < date.today() - timedelta(days=config.incomplete_refresh_days):
        return False
    safe_game = config.game.lower()
    safe_format = config.format.lower()
    relative = f"tournaments/{safe_game}_{safe_format}_page_{page}.json"
    cache = getattr(api, "cache", None)
    if cache is None or not cache.exists(relative):
        return False
    age = cache.age_seconds(relative)
    return age is None or age >= config.discovery_cache_ttl_minutes * 60


def fetch_dataset(api: LimitlessAPI, config: AnalysisConfig) -> FetchResult:
    included: list[dict[str, Any]] = []
    audit: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    page = 0
    while True:
        summaries = api.tournaments(
            config.game,
            config.format,
            page,
            force_refresh=_refresh_discovery_cache(api, config, page),
        )
        _report(api, f"discovery page {page}: {len(summaries)} tournament(s)")
        if not summaries:
            break
        oldest_date = min(parse_api_date(row["date"]) for row in summaries)
        for position, summary in enumerate(summaries, start=1):
            tournament_id = str(summary.get("id") or "")
            if not tournament_id or tournament_id in seen_ids:
                continue
            seen_ids.add(tournament_id)
            row = _audit_row(summary)
            if tournament_id in config.excluded_tournaments:
                note = config.excluded_tournaments[tournament_id].strip()
                row["exclusion_reason"] = (
                    f"manual exclusion: {note}" if note else "manual exclusion"
                )
                audit.append(row)
                _report(
                    api,
                    f"page {page} item {position}/{len(summaries)}: excluded {tournament_id}",
                )
                continue
            summary_reason = summary_exclusion_reason(summary, config)
            if summary_reason:
                row["exclusion_reason"] = summary_reason
                audit.append(row)
                continue

            refresh_payloads = _refresh_incomplete_cache(
                api,
                tournament_id,
                parse_api_date(summary["date"]),
                int(summary.get("players") or 0),
                config.incomplete_cache_ttl_minutes,
                config.incomplete_refresh_days,
            )
            if refresh_payloads:
                _report(api, f"refreshing incomplete tournament {tournament_id}")
            details = api.tournament_details(
                tournament_id, force_refresh=refresh_payloads
            )
            row.update(_audit_row(details))
            reason = detail_exclusion_reason(details, config)
            if reason:
                row["exclusion_reason"] = reason
                audit.append(row)
                continue

            standings = api.tournament_standings(
                tournament_id, force_refresh=refresh_payloads
            )
            pairings = api.tournament_pairings(
                tournament_id, force_refresh=refresh_payloads
            )
            row["is_complete"] = tournament_is_complete(
                standings, int(details.get("players") or 0)
            )
            included.append(
                {"details": details, "standings": standings, "pairings": pairings}
            )
            row["included"] = True
            audit.append(row)
            _report(
                api,
                f"page {page} item {position}/{len(summaries)}: included "
                f"{details.get('name', tournament_id)}",
            )

        # Continue if the page ends exactly on the requested start date; another
        # page can contain more tournaments from that same date.
        if oldest_date < config.start_date:
            break
        page += 1
        if page >= 500:
            raise RuntimeError("Tournament discovery exceeded 500 pages")

    result = FetchResult(
        tournaments=included,
        audit=audit,
        network_requests=api.network_requests,
        cache_hits=api.cache_hits,
    )
    _write_manifest(config, result)
    return result


def _write_manifest(config: AnalysisConfig, result: FetchResult) -> None:
    config.raw_dir.mkdir(parents=True, exist_ok=True)
    target = config.raw_dir / "fetch_manifest.json"
    payload = {
        "generated_at": utc_now_iso(),
        "config": config.metadata(),
        "included_tournament_ids": [
            item["details"]["id"] for item in result.tournaments
        ],
        "audit": [
            {**row, "date": row["date"].isoformat() if row.get("date") else None}
            for row in result.audit
        ],
        "network_requests": result.network_requests,
        "cache_hits": result.cache_hits,
    }
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def normalize_pairing(pairing: dict[str, Any]) -> str:
    player_a = pairing.get("player1")
    player_b = pairing.get("player2")
    winner = pairing.get("winner")
    if not player_a:
        return "INVALID"
    if not player_b:
        return "BYE" if winner == player_a else "INVALID"
    if winner == player_a:
        return "A_WIN"
    if winner == player_b:
        return "B_WIN"
    if winner == 0 or winner == "0":
        return "TIE"
    if winner == -1 or winner == "-1":
        return "DOUBLE_LOSS"
    return "INVALID"


def normalize_dataset(
    fetched: FetchResult,
) -> dict[str, pd.DataFrame]:
    tournament_rows: list[dict[str, Any]] = []
    entry_rows: list[dict[str, Any]] = []
    decklist_rows: list[dict[str, Any]] = []
    match_rows: list[dict[str, Any]] = []
    diagnostic_rows: list[dict[str, Any]] = []
    audit_by_id = {row["tournament_id"]: dict(row) for row in fetched.audit}

    for item in fetched.tournaments:
        details = item["details"]
        standings = item["standings"]
        pairings = item["pairings"]
        tournament_id = str(details["id"])
        known_players = {
            str(row["player"]) for row in standings if row.get("player") is not None
        }
        top_cut = detect_top_cut(details, pairings, known_players)
        valid_cut_players = top_cut.players if top_cut.detected else frozenset()
        is_complete = tournament_is_complete(
            standings, int(details.get("players") or 0)
        )

        organizer = details.get("organizer") or {}
        tournament_rows.append(
            {
                "tournament_id": tournament_id,
                "name": details.get("name"),
                "date": parse_api_date(details["date"]),
                "game": details.get("game"),
                "format": details.get("format"),
                "platform": details.get("platform"),
                "players": int(details.get("players") or 0),
                "organizer_id": str(organizer.get("id")) if organizer.get("id") is not None else None,
                "organizer_name": organizer.get("name"),
                "is_online": details.get("isOnline") is True,
                "has_decklists": details.get("decklists") is True,
                "phase_json": json.dumps(details.get("phases") or [], separators=(",", ":")),
                "top_cut_detected": top_cut.detected,
                "top_cut_size": top_cut.size if top_cut.detected else None,
                "is_complete": is_complete,
            }
        )

        audit_row = audit_by_id[tournament_id]
        audit_row["top_cut_detected"] = top_cut.detected
        audit_row["top_cut_size"] = top_cut.size if top_cut.detected else None
        audit_row["is_complete"] = is_complete

        diagnostic_rows.append(
            {
                "tournament_id": tournament_id,
                "tournament_name": details.get("name"),
                "total_players": int(details.get("players") or 0),
                "bracket_phase": top_cut.phase_label,
                "explicit_elimination_phase": top_cut.explicit_elimination_phase,
                "detected_top_cut_size": top_cut.size if top_cut.explicit_elimination_phase else None,
                "detected_top_cut_players": ",".join(sorted(top_cut.players)),
                "first_elimination_phase_players": top_cut.first_phase_player_count,
                "suspicious": top_cut.suspicious,
                "diagnostic_reason": top_cut.reason,
            }
        )

        for standing in standings:
            player_id = standing.get("player")
            if player_id is None:
                continue
            deck = standing.get("deck") or {}
            deck_id = str(deck.get("id") or UNKNOWN_DECK_ID)
            deck_name = str(deck.get("name") or UNKNOWN_DECK_NAME)
            record = standing.get("record") or {}
            if top_cut.detected:
                entry_top_cut: bool | None = str(player_id) in valid_cut_players
            else:
                entry_top_cut = None
            entry_rows.append(
                {
                    "tournament_id": tournament_id,
                    "player_id": str(player_id),
                    "deck_id": deck_id,
                    "deck_name": deck_name,
                    "placing": standing.get("placing"),
                    "wins": int(record.get("wins") or 0),
                    "losses": int(record.get("losses") or 0),
                    "ties": int(record.get("ties") or 0),
                    "drop_round": standing.get("drop"),
                    "top_cut": entry_top_cut,
                }
            )
            decklist = standing.get("decklist")
            if isinstance(decklist, dict) and any(
                decklist.get(category) for category in ("pokemon", "trainer", "energy")
            ):
                decklist_rows.append(
                    {
                        "tournament_id": tournament_id,
                        "player_id": str(player_id),
                        "player_name": standing.get("name") or str(player_id),
                        "decklist_json": json.dumps(
                            decklist, ensure_ascii=False, separators=(",", ":")
                        ),
                    }
                )

        phase_types = {
            int(phase.get("phase")): str(phase.get("type") or "UNKNOWN").upper()
            for phase in details.get("phases") or []
            if phase.get("phase") is not None
        }
        for index, pairing in enumerate(pairings):
            phase = pairing.get("phase")
            try:
                phase_number = int(phase)
            except (TypeError, ValueError):
                phase_number = None
            winner = pairing.get("winner")
            match_rows.append(
                {
                    "match_id": f"{tournament_id}:{index}",
                    "tournament_id": tournament_id,
                    "phase": phase_number,
                    "phase_type": phase_types.get(phase_number, "UNKNOWN"),
                    "round": pairing.get("round"),
                    "table_or_match": (
                        str(pairing["table"])
                        if pairing.get("table") is not None
                        else str(pairing["match"])
                        if pairing.get("match") is not None
                        else None
                    ),
                    "player_a": str(pairing["player1"]) if pairing.get("player1") is not None else None,
                    "player_b": str(pairing["player2"]) if pairing.get("player2") is not None else None,
                    "winner": str(winner) if winner is not None else None,
                    "result": normalize_pairing(pairing),
                }
            )

    return {
        "tournaments": pd.DataFrame(tournament_rows),
        "entries": pd.DataFrame(entry_rows),
        "decklists": pd.DataFrame(decklist_rows),
        "matches": pd.DataFrame(match_rows),
        "tournament_audit": pd.DataFrame(list(audit_by_id.values())),
        "topcut_diagnostics": pd.DataFrame(diagnostic_rows),
    }
