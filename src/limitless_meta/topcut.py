from __future__ import annotations

from typing import Any, Iterable

from .models import TopCutResult


def is_elimination_phase(phase_type: Any) -> bool:
    normalized = str(phase_type or "").strip().upper()
    return any(token in normalized for token in ("ELIMINATION", "BRACKET", "KNOCKOUT"))


def detect_top_cut(
    details: dict[str, Any],
    pairings: Iterable[dict[str, Any]],
    known_players: set[str] | None = None,
) -> TopCutResult:
    """Detect cut entrants from every contiguous elimination phase.

    Limitless sometimes represents one logical cut as a short play-in phase followed
    by another elimination phase. A fully seeded player may therefore be absent from
    the first phase. The union prevents that bracket bye from shrinking the cut.
    """

    phases = details.get("phases") or []
    swiss_phase_numbers = {
        int(phase.get("phase") or 0)
        for phase in phases
        if str(phase.get("type") or "").strip().upper() == "SWISS"
    }
    all_elimination_phases = [
        phase for phase in phases if is_elimination_phase(phase.get("type"))
    ]
    if all_elimination_phases and not swiss_phase_numbers:
        phase_label = ", ".join(
            f"{phase.get('phase')}:{phase.get('type')}"
            for phase in sorted(
                all_elimination_phases, key=lambda phase: int(phase.get("phase") or 0)
            )
        )
        return TopCutResult(
            True,
            False,
            phase_label,
            frozenset(),
            False,
            "bracket-only event has no preceding Swiss phase",
        )
    last_swiss_phase = max(swiss_phase_numbers, default=0)
    elimination_phases = sorted(
        [
            phase
            for phase in all_elimination_phases
            if int(phase.get("phase") or 0) > last_swiss_phase
        ],
        key=lambda phase: int(phase.get("phase") or 0),
    )
    if not elimination_phases:
        return TopCutResult(False, False, None, frozenset(), False, None)

    phase_numbers = {int(phase["phase"]) for phase in elimination_phases}
    first_phase_number = min(phase_numbers)
    all_players: set[str] = set()
    first_phase_players: set[str] = set()
    for pairing in pairings:
        try:
            phase_number = int(pairing.get("phase"))
        except (TypeError, ValueError):
            continue
        if phase_number not in phase_numbers:
            continue
        for key in ("player1", "player2"):
            player = pairing.get(key)
            if isinstance(player, str) and player.strip():
                all_players.add(player)
                if phase_number == first_phase_number:
                    first_phase_players.add(player)

    total_players = int(details.get("players") or 0)
    reasons: list[str] = []
    if len(all_players) <= 1:
        reasons.append("elimination phase has fewer than two detected players")
    if total_players and len(all_players) > total_players:
        reasons.append("detected cut exceeds tournament player count")
    if known_players is not None:
        unknown = sorted(all_players - known_players)
        if unknown:
            reasons.append(f"{len(unknown)} cut player(s) missing from standings")

    phase_label = ", ".join(
        f"{phase.get('phase')}:{phase.get('type')}" for phase in elimination_phases
    )
    suspicious = bool(reasons)
    return TopCutResult(
        explicit_elimination_phase=True,
        detected=not suspicious,
        phase_label=phase_label,
        players=frozenset(all_players),
        suspicious=suspicious,
        reason="; ".join(reasons) if reasons else None,
        first_phase_player_count=len(first_phase_players),
    )
