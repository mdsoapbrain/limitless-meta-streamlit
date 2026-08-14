from __future__ import annotations

from pathlib import Path

import duckdb


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATABASE_PATH = PROJECT_ROOT / "data" / "meta.duckdb"
REQUIRED_TABLES = {
    "tournaments",
    "entries",
    "decklists",
    "matches",
    "tournament_audit",
    "topcut_diagnostics",
    "run_metadata",
}


def main() -> None:
    if not DATABASE_PATH.is_file():
        raise SystemExit(f"Missing deploy database: {DATABASE_PATH}")

    connection = duckdb.connect(str(DATABASE_PATH), read_only=True)
    try:
        tables = {
            row[0]
            for row in connection.execute("SHOW TABLES").fetchall()
        }
        missing = REQUIRED_TABLES - tables
        if missing:
            raise SystemExit(f"Database is missing tables: {sorted(missing)}")

        metadata = connection.execute(
            """
            SELECT
                start_date,
                end_date,
                eligible_tournament_count,
                eligible_entry_count,
                valid_match_count
            FROM run_metadata
            LIMIT 1
            """
        ).fetchone()
        if metadata is None:
            raise SystemExit("Database has no run metadata")
    finally:
        connection.close()

    print(
        "Deployment database OK: "
        f"{metadata[0]} to {metadata[1]}, "
        f"{metadata[2]} tournaments, {metadata[3]} entries, "
        f"{metadata[4]} valid matches"
    )


if __name__ == "__main__":
    main()
