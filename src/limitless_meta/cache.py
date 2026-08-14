from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import utc_now_iso


class JsonCache:
    """A transparent on-disk cache that keeps raw API bodies audit-friendly."""

    def __init__(self, root: Path):
        self.root = Path(root).resolve()

    def path(self, relative: str | Path) -> Path:
        relative_path = Path(relative)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise ValueError(f"Cache path must stay below {self.root}: {relative}")
        target = (self.root / relative_path).resolve()
        if target != self.root and self.root not in target.parents:
            raise ValueError(f"Cache path must stay below {self.root}: {relative}")
        return target

    def metadata_path(self, relative: str | Path) -> Path:
        return self.path(Path("_metadata") / Path(relative))

    def exists(self, relative: str | Path) -> bool:
        return self.path(relative).is_file()

    def read(self, relative: str | Path) -> Any:
        with self.path(relative).open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def age_seconds(self, relative: str | Path) -> float | None:
        """Return cache age using sidecar time, falling back to file mtime."""

        target = self.path(relative)
        if not target.is_file():
            return None
        metadata_target = self.metadata_path(relative)
        if metadata_target.is_file():
            try:
                metadata = json.loads(metadata_target.read_text(encoding="utf-8"))
                fetched_at = datetime.fromisoformat(
                    str(metadata["fetched_at"]).replace("Z", "+00:00")
                )
                return max(
                    0.0, (datetime.now(timezone.utc) - fetched_at).total_seconds()
                )
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                pass
        return max(0.0, datetime.now(timezone.utc).timestamp() - target.stat().st_mtime)

    def write(
        self,
        relative: str | Path,
        payload: Any,
        *,
        url: str,
        headers: dict[str, str] | None = None,
    ) -> Path:
        target = self.path(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        self._atomic_json(target, payload)

        metadata_target = self.metadata_path(relative)
        metadata = {
            "fetched_at": utc_now_iso(),
            "url": url,
            "etag": (headers or {}).get("etag"),
            "ratelimit": (headers or {}).get("ratelimit"),
            "ratelimit_policy": (headers or {}).get("ratelimit-policy"),
        }
        metadata_target.parent.mkdir(parents=True, exist_ok=True)
        self._atomic_json(metadata_target, metadata)
        return target

    @staticmethod
    def _atomic_json(target: Path, payload: Any) -> None:
        fd, temporary_name = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
                handle.write("\n")
            os.replace(temporary_name, target)
        except Exception:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
            raise
