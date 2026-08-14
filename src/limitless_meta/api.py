from __future__ import annotations

import random
import re
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode

import requests

from .cache import JsonCache


class LimitlessAPIError(RuntimeError):
    pass


class LimitlessAPI:
    BASE_URL = "https://play.limitlesstcg.com/api"

    def __init__(
        self,
        raw_cache_dir: Path,
        *,
        refresh: bool = False,
        timeout: float = 30.0,
        retries: int = 5,
        minimum_interval: float = 0.2,
        session: requests.Session | None = None,
        progress: Callable[[str], None] | None = None,
    ) -> None:
        self.cache = JsonCache(raw_cache_dir)
        self.refresh = refresh
        self.timeout = timeout
        self.retries = retries
        self.minimum_interval = minimum_interval
        self.session = session or requests.Session()
        self.progress = progress
        self.session.headers.update({"User-Agent": "limitless-meta/0.1 (local analytics)"})
        self._last_request_at = 0.0
        self.network_requests = 0
        self.cache_hits = 0
        self.last_rate_limit: dict[str, int | str | None] = {}

    def get_json(
        self,
        endpoint: str,
        *,
        params: dict[str, Any] | None,
        cache_relative: str,
        force_refresh: bool = False,
    ) -> Any:
        if not self.refresh and not force_refresh and self.cache.exists(cache_relative):
            self.cache_hits += 1
            self.report_progress(f"cache hit  {cache_relative}")
            return self.cache.read(cache_relative)

        query = f"?{urlencode(params)}" if params else ""
        url = f"{self.BASE_URL}{endpoint}{query}"
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            self._pace()
            try:
                action = "refresh" if force_refresh or self.refresh else "request"
                self.report_progress(f"{action:<9} {endpoint}{query}")
                response = self.session.get(url, timeout=self.timeout)
                self.network_requests += 1
                self._last_request_at = time.monotonic()
                self._capture_rate_limit(response.headers)

                if response.status_code == 429:
                    if attempt >= self.retries:
                        raise LimitlessAPIError(
                            f"Limitless rate limit remained active after {self.retries} retries"
                        )
                    delay = self._retry_delay(response, attempt)
                    self.report_progress(
                        f"rate limit reached; waiting {delay:.0f}s before retry"
                    )
                    time.sleep(delay)
                    continue
                if 500 <= response.status_code < 600:
                    if attempt >= self.retries:
                        response.raise_for_status()
                    delay = self._backoff(attempt)
                    self.report_progress(
                        f"HTTP {response.status_code}; retrying in {delay:.1f}s"
                    )
                    time.sleep(delay)
                    continue
                response.raise_for_status()
                payload = response.json()
                self.cache.write(
                    cache_relative,
                    payload,
                    url=url,
                    headers={key.lower(): value for key, value in response.headers.items()},
                )
                return payload
            except (requests.Timeout, requests.ConnectionError) as exc:
                last_error = exc
                if attempt >= self.retries:
                    break
                delay = self._backoff(attempt)
                self.report_progress(f"connection error; retrying in {delay:.1f}s")
                time.sleep(delay)
            except requests.RequestException as exc:
                raise LimitlessAPIError(f"Limitless request failed: {url}: {exc}") from exc
            except ValueError as exc:
                raise LimitlessAPIError(f"Limitless returned non-JSON content: {url}") from exc
        raise LimitlessAPIError(f"Limitless request failed after retries: {url}") from last_error

    def tournaments(
        self,
        game: str,
        format_name: str,
        page: int,
        *,
        force_refresh: bool = False,
    ) -> list[dict[str, Any]]:
        safe_game = game.lower()
        safe_format = format_name.lower()
        payload = self.get_json(
            "/tournaments",
            params={"game": game, "format": format_name, "page": page},
            cache_relative=f"tournaments/{safe_game}_{safe_format}_page_{page}.json",
            force_refresh=force_refresh,
        )
        if not isinstance(payload, list):
            raise LimitlessAPIError("GET /tournaments did not return a JSON list")
        return payload

    def tournament_details(
        self, tournament_id: str, *, force_refresh: bool = False
    ) -> dict[str, Any]:
        payload = self.get_json(
            f"/tournaments/{tournament_id}/details",
            params=None,
            cache_relative=f"details/{tournament_id}.json",
            force_refresh=force_refresh,
        )
        if not isinstance(payload, dict):
            raise LimitlessAPIError(f"details for {tournament_id} were not a JSON object")
        return payload

    def tournament_standings(
        self, tournament_id: str, *, force_refresh: bool = False
    ) -> list[dict[str, Any]]:
        payload = self.get_json(
            f"/tournaments/{tournament_id}/standings",
            params=None,
            cache_relative=f"standings/{tournament_id}.json",
            force_refresh=force_refresh,
        )
        if not isinstance(payload, list):
            raise LimitlessAPIError(f"standings for {tournament_id} were not a JSON list")
        return payload

    def tournament_pairings(
        self, tournament_id: str, *, force_refresh: bool = False
    ) -> list[dict[str, Any]]:
        payload = self.get_json(
            f"/tournaments/{tournament_id}/pairings",
            params=None,
            cache_relative=f"pairings/{tournament_id}.json",
            force_refresh=force_refresh,
        )
        if not isinstance(payload, list):
            raise LimitlessAPIError(f"pairings for {tournament_id} were not a JSON list")
        return payload

    def _pace(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self.minimum_interval:
            time.sleep(self.minimum_interval - elapsed)

    def report_progress(self, message: str) -> None:
        if self.progress is not None:
            self.progress(message)

    @staticmethod
    def _backoff(attempt: int) -> float:
        return min(30.0, (2**attempt) + random.uniform(0.0, 0.5))

    def _retry_delay(self, response: requests.Response, attempt: int) -> float:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return min(300.0, max(1.0, float(retry_after)))
            except ValueError:
                pass
        reset = self.last_rate_limit.get("reset_seconds")
        if isinstance(reset, int) and reset > 0:
            return min(300.0, reset + 1.0)
        return self._backoff(attempt)

    def _capture_rate_limit(self, headers: requests.structures.CaseInsensitiveDict) -> None:
        raw = headers.get("RateLimit", "")
        remaining_match = re.search(r"(?:^|;)\s*r=(\d+)", raw)
        reset_match = re.search(r"(?:^|;)\s*t=(\d+)", raw)
        self.last_rate_limit = {
            "raw": raw or None,
            "policy": headers.get("RateLimit-Policy"),
            "remaining": int(remaining_match.group(1)) if remaining_match else None,
            "reset_seconds": int(reset_match.group(1)) if reset_match else None,
        }
