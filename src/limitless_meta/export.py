from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd


CSV_TABLES = {
    "deck_summary": "deck_summary.csv",
    "matchups_long": "matchups_long.csv",
    "tournaments": "tournaments.csv",
    "entries": "entries.csv",
    "matches": "matches.csv",
    "tournament_audit": "tournament_audit.csv",
    "topcut_diagnostics": "topcut_diagnostics.csv",
}


def export_analytics(
    analytics_dir: Path,
    tables: dict[str, pd.DataFrame],
    metadata: dict[str, Any],
    validation: dict[str, Any],
) -> dict[str, Path]:
    analytics_dir = Path(analytics_dir)
    analytics_dir.mkdir(parents=True, exist_ok=True)
    outputs: dict[str, Path] = {}
    for table_name, filename in CSV_TABLES.items():
        target = analytics_dir / filename
        tables.get(table_name, pd.DataFrame()).to_csv(target, index=False)
        outputs[table_name] = target

    metadata_target = analytics_dir / "metadata.json"
    metadata_target.write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )
    validation_target = analytics_dir / "validation.json"
    validation_target.write_text(
        json.dumps(validation, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )
    outputs["metadata"] = metadata_target
    outputs["validation"] = validation_target
    return outputs

