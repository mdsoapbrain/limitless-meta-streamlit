from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_dashboard_starts_against_generated_database() -> None:
    project_root = Path(__file__).resolve().parents[1]
    database = project_root / "data" / "meta.duckdb"
    if not database.exists():
        return
    app = AppTest.from_file(project_root / "dashboard" / "app.py", default_timeout=15)
    app.run()
    assert not app.exception
    assert app.title[0].value == "PTCGL Standard Meta Analyzer"
    assert all(checkbox.label != "Debug mode" for checkbox in app.checkbox)


def test_dashboard_uses_simplified_navigation_and_fixed_matrix() -> None:
    project_root = Path(__file__).resolve().parents[1]
    database = project_root / "data" / "meta.duckdb"
    if not database.exists():
        return
    app = AppTest.from_file(project_root / "dashboard" / "app.py", default_timeout=30)
    app.run()

    assert not app.exception
    assert [tab.label for tab in app.tabs] == [
        "Meta overview",
        "Deck explorer",
        "Matchup matrix",
        "Period change",
    ]
    assert all(
        slider.label != "Archetypes in matrix" for slider in app.slider
    )
    assert all(
        subheader.value != "Observed matchup impact"
        for subheader in app.subheader
    )


def test_deck_selection_persists_after_filter_interaction() -> None:
    project_root = Path(__file__).resolve().parents[1]
    database = project_root / "data" / "meta.duckdb"
    if not database.exists():
        return
    app = AppTest.from_file(project_root / "dashboard" / "app.py", default_timeout=30)
    app.run()

    deck = next(selectbox for selectbox in app.selectbox if selectbox.label == "Select deck")
    assert len(deck.options) > 1
    deck.set_value(deck.options[1]).run()
    selected_deck = next(
        selectbox for selectbox in app.selectbox if selectbox.label == "Select deck"
    ).value

    minimum_n = next(
        number_input
        for number_input in app.number_input
        if number_input.label == "Minimum matchup N"
    )
    minimum_n.set_value(minimum_n.value + 1).run()

    deck_after_filter = next(
        selectbox for selectbox in app.selectbox if selectbox.label == "Select deck"
    )
    assert not app.exception
    assert deck_after_filter.value == selected_deck


def test_dashboard_can_switch_to_approved_player_scope() -> None:
    project_root = Path(__file__).resolve().parents[1]
    database = project_root / "data" / "meta.duckdb"
    if not database.exists():
        return
    app = AppTest.from_file(project_root / "dashboard" / "app.py", default_timeout=30)
    app.run()
    player_scope = next(radio for radio in app.radio if radio.label == "Player scope")
    player_scope.set_value("Approved player").run()

    assert not app.exception
    player = next(selectbox for selectbox in app.selectbox if selectbox.label == "Player")
    assert len(player.options) == 7
    assert any("Azul Garcia Griego" in option for option in player.options)
    assert any(metric.label == "Tournaments entered" for metric in app.metric)
    assert any(
        "matchup views retain every loaded opponent" in info.value for info in app.info
    )


def test_dashboard_can_analyze_the_approved_player_group() -> None:
    project_root = Path(__file__).resolve().parents[1]
    database = project_root / "data" / "meta.duckdb"
    if not database.exists():
        return
    app = AppTest.from_file(project_root / "dashboard" / "app.py", default_timeout=30)
    app.run()
    player_scope = next(radio for radio in app.radio if radio.label == "Player scope")
    player_scope.set_value("Approved player group").run()

    assert not app.exception
    assert any(metric.label == "Cohort entries" for metric in app.metric)
    assert any("Cohort view: Approved players (7)" in info.value for info in app.info)
