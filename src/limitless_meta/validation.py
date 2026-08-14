from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class ValidationIssue:
    check: str
    message: str
    severity: str = "error"

    def as_dict(self) -> dict[str, str]:
        return {"check": self.check, "message": self.message, "severity": self.severity}


def validate_analytics(
    tournaments: pd.DataFrame,
    entries: pd.DataFrame,
    matches: pd.DataFrame,
    deck_summary: pd.DataFrame,
    matchups: pd.DataFrame,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    if not deck_summary.empty:
        representation_sum = float(deck_summary["representation"].sum())
        if not math.isclose(representation_sum, 1.0, rel_tol=0, abs_tol=1e-10):
            issues.append(
                ValidationIssue("representation", f"representations sum to {representation_sum}")
            )
        invalid_cut = deck_summary[
            deck_summary["top_cut_entries"] > deck_summary["conversion_eligible_entries"]
        ]
        if not invalid_cut.empty:
            issues.append(
                ValidationIssue("top_cut", f"{len(invalid_cut)} deck(s) have top cuts above denominator")
            )

    matchup_lookup = {
        (row.deck_a, row.deck_b): row for row in matchups.itertuples(index=False)
    }
    symmetry_failures = 0
    win_rate_failures = 0
    for key, row in matchup_lookup.items():
        reverse = matchup_lookup.get((key[1], key[0]))
        if reverse is None:
            symmetry_failures += 1
            continue
        if row.wins != reverse.losses or row.losses != reverse.wins:
            symmetry_failures += 1
        if row.n_decided != reverse.n_decided:
            symmetry_failures += 1
        if row.n_decided and not math.isclose(
            float(row.raw_win_rate) + float(reverse.raw_win_rate),
            1.0,
            rel_tol=0,
            abs_tol=1e-10,
        ):
            win_rate_failures += 1
    if symmetry_failures:
        issues.append(ValidationIssue("matchup_symmetry", f"{symmetry_failures} symmetry failure(s)"))
    if win_rate_failures:
        issues.append(ValidationIssue("win_rate_symmetry", f"{win_rate_failures} WR failure(s)"))

    if not tournaments.empty:
        invalid_tournaments = tournaments[
            tournaments["top_cut_detected"].fillna(False)
            & (tournaments["top_cut_size"] > tournaments["players"])
        ]
        if not invalid_tournaments.empty:
            issues.append(
                ValidationIssue("top_cut_size", f"{len(invalid_tournaments)} cut(s) exceed players")
            )

    if not matches.empty:
        decided = matches[matches["result"].isin(["A_WIN", "B_WIN"])]
        decided = decided[decided["player_a"].notna() & decided["player_b"].notna()]
        total_wins = int(deck_summary["wins"].sum()) if not deck_summary.empty else 0
        total_losses = int(deck_summary["losses"].sum()) if not deck_summary.empty else 0
        if total_wins != total_losses:
            issues.append(
                ValidationIssue(
                    "decided_match_contribution",
                    f"directional totals are {total_wins} wins and {total_losses} losses",
                )
            )
        duplicate_columns = [
            "tournament_id",
            "phase",
            "round",
            "table_or_match",
            "player_a",
            "player_b",
        ]
        duplicate_count = int(matches.duplicated(duplicate_columns, keep=False).sum())
        if duplicate_count:
            issues.append(
                ValidationIssue("duplicate_matches", f"{duplicate_count} normalized rows look duplicated")
            )
        matchup_total = int(matchups["wins"].sum()) if not matchups.empty else 0
        if matchup_total != total_wins:
            issues.append(
                ValidationIssue(
                    "bye_exclusion",
                    f"matchup wins {matchup_total} do not equal deck-summary wins {total_wins}",
                )
            )

    return issues


def validation_report(issues: list[ValidationIssue]) -> dict[str, Any]:
    return {
        "passed": not any(issue.severity == "error" for issue in issues),
        "error_count": sum(issue.severity == "error" for issue in issues),
        "warning_count": sum(issue.severity == "warning" for issue in issues),
        "issues": [issue.as_dict() for issue in issues],
    }

