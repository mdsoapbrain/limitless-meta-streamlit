from __future__ import annotations

from pathlib import Path
from typing import Iterable

import duckdb
import pandas as pd


TABLE_SCHEMAS: dict[str, list[tuple[str, str]]] = {
    "tournaments": [
        ("tournament_id", "VARCHAR PRIMARY KEY"),
        ("name", "VARCHAR"),
        ("date", "DATE"),
        ("game", "VARCHAR"),
        ("format", "VARCHAR"),
        ("platform", "VARCHAR"),
        ("players", "INTEGER"),
        ("organizer_id", "VARCHAR"),
        ("organizer_name", "VARCHAR"),
        ("is_online", "BOOLEAN"),
        ("has_decklists", "BOOLEAN"),
        ("phase_json", "JSON"),
        ("top_cut_detected", "BOOLEAN"),
        ("top_cut_size", "INTEGER"),
        ("is_complete", "BOOLEAN"),
    ],
    "entries": [
        ("tournament_id", "VARCHAR"),
        ("player_id", "VARCHAR"),
        ("deck_id", "VARCHAR"),
        ("deck_name", "VARCHAR"),
        ("placing", "INTEGER"),
        ("wins", "INTEGER"),
        ("losses", "INTEGER"),
        ("ties", "INTEGER"),
        ("drop_round", "INTEGER"),
        ("top_cut", "BOOLEAN"),
        ("PRIMARY KEY (tournament_id, player_id)", ""),
    ],
    "decklists": [
        ("tournament_id", "VARCHAR"),
        ("player_id", "VARCHAR"),
        ("player_name", "VARCHAR"),
        ("decklist_json", "JSON"),
        ("PRIMARY KEY (tournament_id, player_id)", ""),
    ],
    "matches": [
        ("match_id", "VARCHAR PRIMARY KEY"),
        ("tournament_id", "VARCHAR"),
        ("phase", "INTEGER"),
        ("phase_type", "VARCHAR"),
        ("round", "INTEGER"),
        ("table_or_match", "VARCHAR"),
        ("player_a", "VARCHAR"),
        ("player_b", "VARCHAR"),
        ("winner", "VARCHAR"),
        ("result", "VARCHAR"),
    ],
    "tournament_audit": [
        ("tournament_id", "VARCHAR PRIMARY KEY"),
        ("name", "VARCHAR"),
        ("date", "DATE"),
        ("players", "INTEGER"),
        ("organizer", "VARCHAR"),
        ("game", "VARCHAR"),
        ("format", "VARCHAR"),
        ("platform", "VARCHAR"),
        ("included", "BOOLEAN"),
        ("exclusion_reason", "VARCHAR"),
        ("top_cut_detected", "BOOLEAN"),
        ("top_cut_size", "INTEGER"),
        ("is_complete", "BOOLEAN"),
    ],
    "topcut_diagnostics": [
        ("tournament_id", "VARCHAR PRIMARY KEY"),
        ("tournament_name", "VARCHAR"),
        ("total_players", "INTEGER"),
        ("bracket_phase", "VARCHAR"),
        ("explicit_elimination_phase", "BOOLEAN"),
        ("detected_top_cut_size", "INTEGER"),
        ("detected_top_cut_players", "VARCHAR"),
        ("first_elimination_phase_players", "INTEGER"),
        ("suspicious", "BOOLEAN"),
        ("diagnostic_reason", "VARCHAR"),
    ],
    "deck_summary": [
        ("deck_id", "VARCHAR PRIMARY KEY"),
        ("deck_name", "VARCHAR"),
        ("entries", "INTEGER"),
        ("representation_numerator", "INTEGER"),
        ("representation_denominator", "INTEGER"),
        ("representation", "DOUBLE"),
        ("wins", "INTEGER"),
        ("losses", "INTEGER"),
        ("ties", "INTEGER"),
        ("n_decided", "INTEGER"),
        ("overall_raw_win_rate", "DOUBLE"),
        ("top_cut_entries", "INTEGER"),
        ("conversion_eligible_entries", "INTEGER"),
        ("top_cut_rate", "DOUBLE"),
        ("tournament_count", "INTEGER"),
    ],
    "matchups_long": [
        ("deck_a", "VARCHAR"),
        ("deck_a_name", "VARCHAR"),
        ("deck_b", "VARCHAR"),
        ("deck_b_name", "VARCHAR"),
        ("wins", "INTEGER"),
        ("losses", "INTEGER"),
        ("ties", "INTEGER"),
        ("double_losses", "INTEGER"),
        ("all_matches", "INTEGER"),
        ("n_decided", "INTEGER"),
        ("raw_win_rate", "DOUBLE"),
        ("opponent_representation", "DOUBLE"),
        ("opponent_representation_numerator", "INTEGER"),
        ("opponent_representation_denominator", "INTEGER"),
        ("weighted_impact", "DOUBLE"),
        ("opponent_top_cut_entries", "INTEGER"),
        ("opponent_conversion_eligible_entries", "INTEGER"),
        ("opponent_top_cut_rate", "DOUBLE"),
        ("PRIMARY KEY (deck_a, deck_b)", ""),
    ],
    "run_metadata": [
        ("generated_at", "TIMESTAMP WITH TIME ZONE"),
        ("start_date", "DATE"),
        ("end_date", "DATE"),
        ("game", "VARCHAR"),
        ("format", "VARCHAR"),
        ("platform", "VARCHAR"),
        ("minimum_tournament_players", "INTEGER"),
        ("match_scope", "VARCHAR"),
        ("eligible_tournament_count", "INTEGER"),
        ("eligible_entry_count", "INTEGER"),
        ("valid_match_count", "INTEGER"),
        ("conversion_eligible_tournament_count", "INTEGER"),
    ],
}


def _column_names(table_name: str) -> list[str]:
    return [name for name, _ in TABLE_SCHEMAS[table_name] if not name.startswith("PRIMARY KEY")]


def _create_statement(table_name: str) -> str:
    definitions = [
        f'"{name}" {type_name}' if type_name else name
        for name, type_name in TABLE_SCHEMAS[table_name]
    ]
    return f'CREATE TABLE "{table_name}" ({", ".join(definitions)})'


def _prepare_frame(table_name: str, frame: pd.DataFrame) -> pd.DataFrame:
    expected = _column_names(table_name)
    prepared = frame.copy()
    for column in expected:
        if column not in prepared.columns:
            prepared[column] = None
    return prepared[expected]


def write_database(path: Path, tables: dict[str, pd.DataFrame]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(str(path))
    try:
        connection.execute("BEGIN TRANSACTION")
        for table_name in TABLE_SCHEMAS:
            frame = _prepare_frame(table_name, tables.get(table_name, pd.DataFrame()))
            connection.execute(f'DROP TABLE IF EXISTS "{table_name}"')
            connection.execute(_create_statement(table_name))
            if not frame.empty:
                view_name = f"_{table_name}_frame"
                connection.register(view_name, frame)
                columns = ", ".join(f'"{column}"' for column in _column_names(table_name))
                connection.execute(
                    # Identifiers come exclusively from the static TABLE_SCHEMAS allowlist.
                    f'INSERT INTO "{table_name}" ({columns}) SELECT {columns} FROM "{view_name}"'  # nosec B608
                )
                connection.unregister(view_name)
        connection.execute("COMMIT")
    except Exception:
        connection.execute("ROLLBACK")
        raise
    finally:
        connection.close()


def read_table(path: Path, table_name: str) -> pd.DataFrame:
    if table_name not in TABLE_SCHEMAS:
        raise KeyError(f"Unknown table: {table_name}")
    # table_name was validated against TABLE_SCHEMAS above.
    query = f'SELECT * FROM "{table_name}"'  # nosec B608
    connection = duckdb.connect(str(path), read_only=True)
    try:
        return connection.execute(query).fetchdf()
    finally:
        connection.close()


def read_tables(path: Path, names: Iterable[str]) -> dict[str, pd.DataFrame]:
    requested_names = list(names)
    unknown_names = [name for name in requested_names if name not in TABLE_SCHEMAS]
    if unknown_names:
        raise KeyError(f"Unknown table(s): {', '.join(unknown_names)}")
    connection = duckdb.connect(str(path), read_only=True)
    try:
        return {
            # Every name was validated against TABLE_SCHEMAS before connecting.
            name: connection.execute(f'SELECT * FROM "{name}"').fetchdf()  # nosec B608
            for name in requested_names
        }
    finally:
        connection.close()


def read_decklists_for_deck(
    path: Path, deck_id: str, tournament_ids: Iterable[str]
) -> pd.DataFrame:
    selected_ids = list(dict.fromkeys(str(value) for value in tournament_ids))
    columns = ["tournament_id", "player_id", "player_name", "decklist_json"]
    if not selected_ids:
        return pd.DataFrame(columns=columns)

    placeholders = ", ".join("?" for _ in selected_ids)
    # Only the number of parameter placeholders is interpolated; all values are bound.
    query = f"""
        SELECT d.tournament_id, d.player_id, d.player_name, d.decklist_json
        FROM decklists AS d
        INNER JOIN entries AS e
            ON e.tournament_id = d.tournament_id
            AND e.player_id = d.player_id
        WHERE e.deck_id = ?
          AND d.tournament_id IN ({placeholders})
    """  # nosec B608
    connection = duckdb.connect(str(path), read_only=True)
    try:
        return connection.execute(query, [str(deck_id), *selected_ids]).fetchdf()
    finally:
        connection.close()
