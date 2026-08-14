from __future__ import annotations

import re

import pandas as pd


SPREADSHEET_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r", "\n")
MARKDOWN_SPECIALS = re.compile(r"([\\`*_{}\[\]()<>#+\-.!|>])")


def escape_spreadsheet_cell(value: object) -> object:
    """Prevent untrusted strings from becoming formulas in downloaded CSV files."""
    if isinstance(value, str) and value.startswith(SPREADSHEET_FORMULA_PREFIXES):
        return f"'{value}"
    return value


def dataframe_to_safe_csv_bytes(frame: pd.DataFrame) -> bytes:
    safe = frame.copy()
    for column in safe.select_dtypes(include=["object", "string"]).columns:
        safe[column] = safe[column].map(escape_spreadsheet_cell)
    return safe.to_csv(index=False).encode("utf-8")


def escape_markdown(value: object) -> str:
    """Render externally sourced text without interpreting Markdown syntax."""
    return MARKDOWN_SPECIALS.sub(r"\\\1", str(value))
