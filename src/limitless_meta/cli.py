from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from .models import AnalysisConfig, parse_api_date
from .pipeline import run_analysis, run_fetch


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"Config must contain a mapping: {path}")
    return payload


def build_config(args: argparse.Namespace) -> AnalysisConfig:
    values = _load_yaml(Path(args.config))
    start_value = args.start or values.get("start_date")
    end_value = args.end or values.get("end_date")
    if not start_value or not end_value:
        raise ValueError("A start and end date are required in arguments or config.yaml")

    def choose(argument_name: str, config_name: str, default: Any) -> Any:
        argument_value = getattr(args, argument_name, None)
        return argument_value if argument_value is not None else values.get(config_name, default)

    configured_exclusions = values.get("excluded_tournaments") or {}
    if isinstance(configured_exclusions, list):
        configured_exclusions = {str(item): "" for item in configured_exclusions}
    if not isinstance(configured_exclusions, dict):
        raise ValueError("excluded_tournaments must be a mapping or list")
    exclusions = {
        str(tournament_id): str(reason or "")
        for tournament_id, reason in configured_exclusions.items()
    }
    for value in args.exclude_tournament or []:
        tournament_id, separator, reason = value.partition(":")
        if not tournament_id.strip():
            raise ValueError("--exclude-tournament requires an ID")
        exclusions[tournament_id.strip()] = reason.strip() if separator else "CLI exclusion"

    return AnalysisConfig(
        start_date=parse_api_date(start_value),
        end_date=parse_api_date(end_value),
        minimum_tournament_players=int(
            choose("min_players", "minimum_tournament_players", 60)
        ),
        game=str(choose("game", "game", "PTCG")),
        format=str(choose("format_name", "format", "STANDARD")),
        platform=str(choose("platform", "platform", "PTCGL")),
        online_only=bool(values.get("online_only", True)),
        decklists_required=bool(values.get("decklists_required", True)),
        match_scope=str(choose("match_scope", "match_scope", "all")).lower(),
        request_timeout_seconds=float(values.get("request_timeout_seconds", 30)),
        request_retries=int(values.get("request_retries", 5)),
        minimum_request_interval_seconds=float(
            values.get("minimum_request_interval_seconds", 0.2)
        ),
        incomplete_cache_ttl_minutes=int(
            values.get("incomplete_cache_ttl_minutes", 15)
        ),
        incomplete_refresh_days=int(values.get("incomplete_refresh_days", 3)),
        discovery_cache_ttl_minutes=int(
            values.get("discovery_cache_ttl_minutes", 15)
        ),
        excluded_tournaments=exclusions,
        data_dir=Path(choose("data_dir", "data_dir", "data")),
    )


def _add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--start", help="Start date, inclusive (YYYY-MM-DD)")
    parser.add_argument("--end", help="End date, inclusive (YYYY-MM-DD)")
    parser.add_argument("--min-players", type=int, help="Minimum tournament player count")
    parser.add_argument("--game", help="Limitless game code")
    parser.add_argument("--format", dest="format_name", help="Tournament format")
    parser.add_argument("--platform", help="Required online platform")
    parser.add_argument("--match-scope", choices=["all", "swiss"], help="Matches to analyze")
    parser.add_argument("--data-dir", help="Cache, database, and export directory")
    parser.add_argument("--config", default="config.yaml", help="YAML config path")
    parser.add_argument("--refresh", action="store_true", help="Force API re-download")
    parser.add_argument(
        "--exclude-tournament",
        action="append",
        metavar="ID[:REASON]",
        help="Exclude one tournament from analytics; repeat as needed",
    )
    parser.add_argument(
        "--quiet", action="store_true", help="Suppress fetch progress messages"
    )


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="limitless-meta",
        description="Observed Limitless PTCGL tournament metagame analytics",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    fetch_parser = subparsers.add_parser("fetch", help="Discover and cache eligible tournaments")
    _add_common_arguments(fetch_parser)
    analyze_parser = subparsers.add_parser(
        "analyze", help="Fetch/cache, normalize, validate, and export analytics"
    )
    _add_common_arguments(analyze_parser)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = make_parser()
    args = parser.parse_args(argv)
    try:
        config = build_config(args)
        if args.command == "fetch":
            progress = None if args.quiet else lambda message: print(message, file=sys.stderr, flush=True)
            result = run_fetch(config, refresh=args.refresh, progress=progress)
            summary = {
                "eligible_tournament_count": len(result.tournaments),
                "network_requests": result.network_requests,
                "cache_hits": result.cache_hits,
                "raw_cache": str(config.raw_dir),
            }
        else:
            progress = None if args.quiet else lambda message: print(message, file=sys.stderr, flush=True)
            result = run_analysis(config, refresh=args.refresh, progress=progress)
            summary = {
                **result.metadata,
                "database": str(config.database_path),
                "analytics_dir": str(config.analytics_dir),
                "validation_passed": result.validation["passed"],
                "validation_errors": result.validation["error_count"],
            }
        print(json.dumps(summary, indent=2, default=str))
        return 0
    except (ValueError, RuntimeError) as exc:
        parser.exit(1, f"error: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
