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
    assert app.title[0].value == "Limitless PTCGL Online Tournament Meta Analyzer"
    assert all(checkbox.label != "Debug mode" for checkbox in app.checkbox)
