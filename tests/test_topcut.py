from __future__ import annotations

from limitless_meta.topcut import detect_top_cut


def test_detects_actual_top_16_instead_of_assuming_top_8() -> None:
    details = {
        "players": 128,
        "phases": [
            {"phase": 1, "type": "SWISS"},
            {"phase": 2, "type": "SINGLE_ELIMINATION"},
        ],
    }
    pairings = [
        {"phase": 2, "player1": f"p{index * 2}", "player2": f"p{index * 2 + 1}"}
        for index in range(8)
    ]
    result = detect_top_cut(details, pairings, {f"p{index}" for index in range(128)})
    assert result.detected
    assert result.size == 16
    assert not result.suspicious


def test_unions_split_elimination_phases_for_full_phase_bye() -> None:
    details = {
        "players": 497,
        "phases": [
            {"phase": 1, "type": "SWISS"},
            {"phase": 2, "type": "SINGLE_ELIMINATION"},
            {"phase": 3, "type": "SINGLE_ELIMINATION"},
        ],
    }
    phase_two = [
        {"phase": 2, "player1": f"p{index * 2}", "player2": f"p{index * 2 + 1}"}
        for index in range(7)
    ] + [{"phase": 2, "player1": "p14"}]
    phase_three = [
        {"phase": 3, "player1": "p0", "player2": "direct_seed"},
        {"phase": 3, "player1": "p2", "player2": "p4"},
    ]
    known = {f"p{index}" for index in range(15)} | {"direct_seed"}
    result = detect_top_cut(details, phase_two + phase_three, known)
    assert result.first_phase_player_count == 15
    assert result.size == 16
    assert result.detected


def test_swiss_only_is_not_conversion_eligible() -> None:
    result = detect_top_cut(
        {"players": 64, "phases": [{"phase": 1, "type": "SWISS"}]},
        [],
        set(),
    )
    assert not result.explicit_elimination_phase
    assert not result.detected
    assert result.size == 0


def test_bracket_only_event_is_not_mislabeled_as_top_cut() -> None:
    result = detect_top_cut(
        {"players": 4, "phases": [{"phase": 1, "type": "DOUBLE_BRACKET"}]},
        [
            {"phase": 1, "player1": "a", "player2": "b"},
            {"phase": 1, "player1": "c", "player2": "d"},
        ],
        {"a", "b", "c", "d"},
    )
    assert result.explicit_elimination_phase
    assert not result.detected
    assert result.size == 0
    assert "no preceding Swiss" in (result.reason or "")
