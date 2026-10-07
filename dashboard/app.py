from __future__ import annotations

import json
import sys
from datetime import timedelta
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from limitless_meta.database import read_decklists_for_deck, read_tables  # noqa: E402
from limitless_meta.metrics import (  # noqa: E402
    compute_cohort_metrics,
    compute_deck_period_series,
    compute_metrics,
    filter_observed_window,
    select_representative_decklists,
)
from limitless_meta.models import UNKNOWN_DECK_ID  # noqa: E402
from limitless_meta.security import dataframe_to_safe_csv_bytes, escape_markdown  # noqa: E402


DATABASE_PATH = PROJECT_ROOT / "data" / "meta.duckdb"
VERIFIED_PLAYERS_PATH = PROJECT_ROOT / "data" / "verified_players.csv"
SUPPORT_URL = "https://buymeacoffee.com/qmi0000011"
LOW_SAMPLE_N = 20
LOW_BLUE = "#3f7cac"
HIGH_RED = "#d26a5c"
NEUTRAL_GRAY = "#f3f4f6"
MAX_MATRIX_ARCHETYPES = 25


st.set_page_config(
    page_title="PTCGL Standard Meta Analyzer | Decks & Matchups",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)
st.title("PTCGL Standard Meta Analyzer")
st.caption(
    "Explore online Standard deck usage, win rates, matchups, trends, and public "
    "decklists from the selected observed period."
)


@st.cache_data(show_spinner=False)
def load_data(database_mtime: float) -> dict[str, pd.DataFrame]:
    del database_mtime
    return read_tables(
        DATABASE_PATH,
        [
            "tournaments",
            "entries",
            "matches",
            "run_metadata",
        ],
    )


@st.cache_data(show_spinner=False)
def load_decklists(
    database_mtime: float, deck_id: str, tournament_ids: tuple[str, ...]
) -> pd.DataFrame:
    del database_mtime
    return read_decklists_for_deck(DATABASE_PATH, deck_id, tournament_ids)


@st.cache_data(show_spinner=False)
def load_verified_players(file_mtime: float) -> pd.DataFrame:
    del file_mtime
    players = pd.read_csv(VERIFIED_PLAYERS_PATH, dtype=str).fillna("")
    required = {
        "real_name",
        "play_limitless_player_id",
        "verification_status",
        "manual_decision",
        "approval_basis",
        "source_url",
    }
    missing = required - set(players.columns)
    if missing:
        raise ValueError(
            "Verified player roster is missing columns: " + ", ".join(sorted(missing))
        )
    return players[
        players["verification_status"].str.strip().str.upper().eq("YES")
        & players["manual_decision"].str.strip().str.upper().eq("YES")
        & players["play_limitless_player_id"].str.strip().ne("")
    ].sort_values(["real_name", "play_limitless_player_id"]).copy()


def representation_chart(summary: pd.DataFrame, limit: int = 15) -> alt.Chart:
    source = summary.head(limit).copy()
    source["representation_label"] = source["representation"].map(lambda value: f"{value:.1%}")
    bars = (
        alt.Chart(source)
        .mark_bar()
        .encode(
            x=alt.X("representation:Q", title="Observed representation", axis=alt.Axis(format=".0%")),
            y=alt.Y("deck_name:N", title=None, sort="-x"),
            tooltip=[
                alt.Tooltip("deck_name:N", title="Deck"),
                alt.Tooltip("entries:Q", title="Entries", format=","),
                alt.Tooltip("representation:Q", title="Representation", format=".2%"),
            ],
        )
    )
    labels = bars.mark_text(
        align="right", baseline="middle", dx=-4, color="#111827"
    ).encode(
        text="representation_label:N"
    )
    return (bars + labels).properties(height=max(300, len(source) * 27))


def trend_chart(source: pd.DataFrame, column: str, title: str) -> alt.Chart:
    return (
        alt.Chart(source)
        .mark_line(point=True)
        .encode(
            x=alt.X("period_start:T", title=None),
            y=alt.Y(f"{column}:Q", title=title, axis=alt.Axis(format=".0%")),
            tooltip=[
                alt.Tooltip("period:N", title="Observed period"),
                alt.Tooltip(f"{column}:Q", title=title, format=".2%"),
                alt.Tooltip("entries:Q", title="Deck entries", format=","),
                alt.Tooltip("eligible_tournaments:Q", title="Tournaments", format=","),
            ],
        )
        .properties(height=230)
    )


def decklist_cards(decklist_json: str) -> dict[str, pd.DataFrame]:
    try:
        payload = json.loads(decklist_json)
    except (TypeError, json.JSONDecodeError):
        payload = {}
    sections: dict[str, pd.DataFrame] = {}
    for key, label in (
        ("pokemon", "Pokémon"),
        ("trainer", "Trainer"),
        ("energy", "Energy"),
    ):
        rows = []
        for card in payload.get(key) or []:
            rows.append(
                {
                    "Qty": int(card.get("count") or 0),
                    "Card": card.get("name") or "Unknown card",
                    "Set": card.get("set") or "",
                    "No.": card.get("number") or "",
                }
            )
        sections[label] = pd.DataFrame(rows, columns=["Qty", "Card", "Set", "No."])
    return sections


if not DATABASE_PATH.exists():
    st.error(f"No database found at {DATABASE_PATH}")
    st.code(
        ".venv/bin/python -m limitless_meta analyze --start 2026-07-01 "
        "--end 2026-08-13 --min-players 60"
    )
    st.stop()

data = load_data(DATABASE_PATH.stat().st_mtime)
tournaments = data["tournaments"].copy()
entries = data["entries"].copy()
matches = data["matches"].copy()
if tournaments.empty:
    st.warning("The database contains no eligible tournaments for its last analysis window.")
    st.stop()

tournaments["date"] = pd.to_datetime(tournaments["date"]).dt.date
available_start = tournaments["date"].min()
available_end = tournaments["date"].max()
run_metadata = data["run_metadata"]
if run_metadata.empty:
    generated_label = "unknown"
else:
    generated_at = pd.to_datetime(run_metadata.iloc[0]["generated_at"])
    generated_label = generated_at.strftime("%Y-%m-%d")
st.caption(
    f"Data coverage: {available_start.isoformat()} – {available_end.isoformat()} · "
    f"Snapshot generated: {generated_label} · "
    "Source: [Limitless Tournament Platform](https://play.limitlesstcg.com/)"
)

if not VERIFIED_PLAYERS_PATH.exists():
    st.error(f"No verified player roster found at {VERIFIED_PLAYERS_PATH}")
    st.stop()
verified_players = load_verified_players(VERIFIED_PLAYERS_PATH.stat().st_mtime)

with st.sidebar:
    st.header("Analysis population")
    player_scope = st.radio(
        "Player scope",
        ["All players", "Approved player group", "Approved player"],
    )
    analysis_player_ids: set[str] | None = None
    scope_label = "All players"
    scope_slug = "all_players"
    scope_is_group = False
    if player_scope != "All players":
        if verified_players.empty:
            st.error("The verified player roster does not contain an approved account.")
            st.stop()
    if player_scope == "Approved player group":
        analysis_player_ids = set(
            verified_players["play_limitless_player_id"].str.strip()
        )
        scope_label = f"Approved players ({len(analysis_player_ids)})"
        scope_slug = "manual_yes_group"
        scope_is_group = True
        st.caption(
            f"{len(analysis_player_ids)} manual-YES players with separately approved "
            "Play Limitless IDs and entries in this snapshot."
        )
    elif player_scope == "Approved player":
        player_options = {
            (
                f"{row.real_name} · {row.play_limitless_player_id}"
                + (
                    f" · 2026 WCS #{row.wcs_2026_placing}"
                    if getattr(row, "wcs_2026_placing", "")
                    else ""
                )
            ): row.Index
            for row in verified_players.itertuples()
        }
        player_label = st.selectbox("Player", list(player_options))
        selected_player = verified_players.loc[player_options[player_label]]
        player_id = selected_player["play_limitless_player_id"].strip()
        scope_label = selected_player["real_name"].strip()
        scope_slug = player_id
        analysis_player_ids = {player_id}
        st.caption(f"Verified Play Limitless ID: {player_id}")
        if selected_player["source_url"].strip():
            st.link_button(
                "Identity verification source",
                selected_player["source_url"].strip(),
                width="stretch",
            )
        if selected_player.get("social_profile_url", "").strip():
            st.link_button(
                "Public social profile",
                selected_player["social_profile_url"].strip(),
                width="stretch",
            )
    st.divider()
    st.header("Observed window")
    preset = st.selectbox(
        "Time window", ["Custom", "Last 7 days", "Last 14 days", "Last 30 days", "Last 60 days"]
    )
    if preset == "Custom":
        selected_start = st.date_input(
            "Start date", value=available_start, min_value=available_start, max_value=available_end
        )
        selected_end = st.date_input(
            "End date", value=available_end, min_value=available_start, max_value=available_end
        )
    else:
        days = int(preset.split()[1])
        selected_end = available_end
        selected_start = max(available_start, selected_end - timedelta(days=days - 1))
        st.caption(f"{selected_start.isoformat()} to {selected_end.isoformat()}")
    minimum_players = st.number_input(
        "Minimum tournament players", min_value=0, value=60, step=10
    )
    match_scope_label = st.selectbox("Match scope", ["All", "Swiss only"])
    match_scope = "all" if match_scope_label == "All" else "swiss"
    minimum_n = st.number_input(
        "Minimum matchup N",
        min_value=0,
        value=3 if analysis_player_ids else 10,
        step=1,
        key=f"minimum_matchup_n_{scope_slug}",
    )
    hide_unknown = st.checkbox("Hide UNKNOWN decks", value=True)

if selected_start > selected_end:
    st.error("Start date must be on or before end date.")
    st.stop()

observed_tournaments, observed_entries, observed_matches = filter_observed_window(
    tournaments,
    entries,
    matches,
    start_date=selected_start,
    end_date=selected_end,
    minimum_players=minimum_players,
)

if analysis_player_ids:
    filtered_entries = observed_entries[
        observed_entries["player_id"].astype(str).isin(analysis_player_ids)
    ].copy()
    included_ids = set(filtered_entries["tournament_id"])
    filtered_tournaments = observed_tournaments[
        observed_tournaments["tournament_id"].isin(included_ids)
    ].copy()
    field_entries = observed_entries[observed_entries["tournament_id"].isin(included_ids)].copy()
    field_matches = observed_matches[observed_matches["tournament_id"].isin(included_ids)].copy()
    filtered_matches = field_matches
    deck_summary, matchups = compute_cohort_metrics(
        filtered_tournaments,
        field_entries,
        field_matches,
        focus_player_ids=analysis_player_ids,
        match_scope=match_scope,
    )
    field_deck_summary, _ = compute_metrics(
        filtered_tournaments, field_entries, field_matches, match_scope=match_scope
    )
else:
    filtered_tournaments = observed_tournaments
    filtered_entries = observed_entries
    filtered_matches = observed_matches
    field_entries = filtered_entries
    field_matches = filtered_matches
    included_ids = set(filtered_tournaments["tournament_id"])
    deck_summary, matchups = compute_metrics(
        filtered_tournaments, filtered_entries, filtered_matches, match_scope=match_scope
    )
    field_deck_summary = deck_summary

if deck_summary.empty:
    st.warning(
        f"No entries for {scope_label} match these filters. "
        "Broaden the window or lower the player threshold."
    )
    st.stop()

if analysis_player_ids:
    population_label = "Cohort" if scope_is_group else "Player"
    st.info(
        f"{population_label} view: {scope_label}. Deck usage and overall records use the "
        "selected population's "
        "published standings; matchup views retain every loaded opponent and count pairings "
        "from the selected population's perspective."
    )

selector_summary = deck_summary
if hide_unknown:
    selector_summary = selector_summary[selector_summary["deck_id"] != UNKNOWN_DECK_ID]
selector_summary = selector_summary.sort_values(
    ["entries", "deck_name"], ascending=[False, True]
)
deck_options = selector_summary["deck_id"].tolist()
deck_labels = {
    row.deck_id: f"{row.deck_name} · {row.entries:,} entries"
    for row in selector_summary.sort_values(["entries", "deck_name"], ascending=[False, True]).itertuples()
}
if not deck_options:
    st.warning("No visible deck remains after the current filters.")
    st.stop()

with st.sidebar:
    st.markdown(
        f"""
        <a class="bmc-sidebar-link" href="{SUPPORT_URL}" target="_blank"
           rel="noopener noreferrer">☕ Buy me a coffee</a>
        <style>
        section[data-testid="stSidebar"] div[data-testid="stSidebarUserContent"] {{
            padding-bottom: 5rem;
        }}
        .bmc-sidebar-link {{
            position: fixed;
            left: 1.25rem;
            bottom: 1rem;
            z-index: 9999;
            width: 16rem;
            box-sizing: border-box;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 0.65rem 1rem;
            border: 1px solid rgba(235, 238, 238, 0.28);
            border-radius: 0.5rem;
            background: #d26a5c;
            color: #ffffff !important;
            font-weight: 600;
            text-decoration: none !important;
            box-shadow: 0 0.2rem 0.6rem rgba(0, 0, 0, 0.22);
        }}
        .bmc-sidebar-link:hover {{
            background: #df7a6d;
        }}
        @media (max-width: 767px) {{
            .bmc-sidebar-link {{
                position: static;
                width: 100%;
                margin-top: 1rem;
            }}
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )

tabs = st.tabs(
    [
        "Meta overview",
        "Deck explorer",
        "Matchup matrix",
        "Period change",
    ]
)

with tabs[0]:
    overview_metrics = st.columns(3)
    overview_metrics[0].metric(
        "Tournaments entered" if analysis_player_ids else "Eligible tournaments",
        f"{len(filtered_tournaments):,}",
    )
    overview_metrics[1].metric(
        (
            "Cohort entries"
            if scope_is_group
            else "Player entries" if analysis_player_ids else "Eligible entries"
        ),
        f"{len(filtered_entries):,}",
    )
    overview_metrics[2].metric(
        "Archetypes used" if analysis_player_ids else "Archetypes",
        f"{len(deck_summary):,}",
    )

    chart_summary = deck_summary
    if hide_unknown:
        chart_summary = chart_summary[chart_summary["deck_id"] != UNKNOWN_DECK_ID]
    st.subheader("Deck choice share" if analysis_player_ids else "Observed representation")
    st.altair_chart(representation_chart(chart_summary), width="stretch")
    if analysis_player_ids:
        st.caption(
            "Share of the selected population's tournament entries using each archetype; "
            "UNKNOWN remains in the denominator."
        )
    else:
        st.caption(
            "Top 15 archetypes by tournament-entry representation; "
            "UNKNOWN remains in the denominator."
        )

    table_source = chart_summary.copy()
    table_columns = [
        "deck_name", "deck_id", "entries", "representation", "wins", "losses",
        "n_decided", "overall_raw_win_rate", "top_cut_entries",
        "conversion_eligible_entries", "top_cut_rate",
    ]
    if analysis_player_ids:
        field_lookup = field_deck_summary.set_index("deck_id")
        table_source["field_representation"] = table_source["deck_id"].map(
            field_lookup["representation"]
        )
        table_source["representation_delta_pp"] = (
            table_source["representation"] - table_source["field_representation"]
        ) * 100
        table_source["field_raw_win_rate"] = table_source["deck_id"].map(
            field_lookup["overall_raw_win_rate"]
        )
        table_source["raw_wr_delta_pp"] = (
            table_source["overall_raw_win_rate"] - table_source["field_raw_win_rate"]
        ) * 100
        table_columns = [
            "deck_name", "deck_id", "entries", "representation", "field_representation",
            "representation_delta_pp", "wins", "losses", "n_decided",
            "overall_raw_win_rate", "field_raw_win_rate", "raw_wr_delta_pp",
            "top_cut_entries", "conversion_eligible_entries", "top_cut_rate",
        ]
    global_table = table_source[table_columns].rename(
        columns={
            "deck_name": "Deck", "deck_id": "Deck ID", "entries": "Entries",
            "representation": "Representation", "wins": "W", "losses": "L",
            "n_decided": "N", "overall_raw_win_rate": "Overall WR",
            "field_representation": "Field representation",
            "representation_delta_pp": "Usage Δ (pp)",
            "field_raw_win_rate": "Field WR",
            "raw_wr_delta_pp": "WR Δ (pp)",
            "top_cut_entries": "Top Cuts",
            "conversion_eligible_entries": "Conversion Eligible",
            "top_cut_rate": "Top Cut Rate",
        }
    )
    st.dataframe(
        global_table,
        width="stretch",
        hide_index=True,
        column_config={
            "Representation": st.column_config.NumberColumn(format="percent"),
            "Field representation": st.column_config.NumberColumn(format="percent"),
            "Usage Δ (pp)": st.column_config.NumberColumn(format="%+.2f pp"),
            "Overall WR": st.column_config.NumberColumn(format="percent"),
            "Field WR": st.column_config.NumberColumn(format="percent"),
            "WR Δ (pp)": st.column_config.NumberColumn(format="%+.2f pp"),
            "Top Cut Rate": st.column_config.NumberColumn(format="percent"),
        },
    )
    if analysis_player_ids:
        st.caption(
            "Selected-population WR uses published standings. Field WR and matchup "
            "breakdowns use "
            "the loaded pairing records."
        )
    st.download_button(
        "Export summary",
        dataframe_to_safe_csv_bytes(global_table),
        file_name=f"{scope_slug}_deck_summary.csv",
        mime="text/csv",
    )

with tabs[1]:
    st.subheader("Deck explorer")
    selection_column, context_column = st.columns([3, 2], vertical_alignment="bottom")
    deck_state_key = f"selected_deck_id_{scope_slug}"
    if st.session_state.get(deck_state_key) not in deck_options:
        st.session_state[deck_state_key] = deck_options[0]
    with selection_column:
        selected_id = st.selectbox(
            "Select deck",
            deck_options,
            format_func=lambda deck_id: deck_labels[deck_id],
            key=deck_state_key,
        )
    with context_column:
        st.caption(
            "Your deck selection stays fixed while you adjust matchup filters or open "
            "other sections."
        )
    selected = deck_summary[deck_summary["deck_id"] == selected_id].iloc[0]

    conversion_rate = (
        f"{selected.top_cut_rate:.1%}" if pd.notna(selected.top_cut_rate) else "NA"
    )
    conversion_detail = (
        f"{selected.top_cut_entries:,}/{selected.conversion_eligible_entries:,} eligible entries"
        if pd.notna(selected.top_cut_rate)
        else "not available"
    )
    metric_columns = st.columns(3)
    metric_columns[0].metric("Representation", f"{selected.representation:.1%}")
    metric_columns[1].metric(
        "Overall raw WR",
        (
            f"{selected.overall_raw_win_rate:.1%}"
            if pd.notna(selected.overall_raw_win_rate)
            else "NA"
        ),
        help="Wins / (wins + losses); ties and byes excluded.",
    )
    metric_columns[2].metric("Top Cut conversion", conversion_rate)
    st.caption(
        f"Record: {selected.wins:,} W · {selected.losses:,} L · {selected.ties:,} T · "
        f"Top Cut: {conversion_detail} · Observed in "
        f"{selected.tournament_count:,} tournament(s). "
        + (
            "Representation is this deck's share of the selected population's entries."
            if analysis_player_ids
            else "All figures follow the filters in the sidebar."
        )
    )

    selected_matchups = matchups[
        (matchups["deck_a"] == selected_id) & (matchups["n_decided"] >= minimum_n)
    ].copy()
    if hide_unknown:
        selected_matchups = selected_matchups[
            selected_matchups["deck_b"] != UNKNOWN_DECK_ID
        ]

    with st.container(border=True):
        st.subheader("Matchup record")
        st.caption(
            "Results are sorted by decided sample size. Click any table header to sort "
            "interactively."
        )
        if selected_matchups.empty:
            st.info("No matchups meet the current minimum N.")
        else:
            selected_matchups = selected_matchups.sort_values(
                ["n_decided", "raw_win_rate", "deck_b_name"],
                ascending=[False, False, True],
                na_position="last",
            )
            low_sample_count = int(
                (selected_matchups["n_decided"] < LOW_SAMPLE_N).sum()
            )
            if low_sample_count:
                st.warning(
                    f"{low_sample_count} displayed matchup(s) have fewer than "
                    f"{LOW_SAMPLE_N} decided games."
                )
            selected_matchups["tie_rate"] = selected_matchups["ties"].div(
                selected_matchups["all_matches"].where(
                    selected_matchups["all_matches"] > 0
                )
            )
            table = pd.DataFrame(
                {
                    "Opponent": selected_matchups["deck_b_name"],
                    "Opponent share": selected_matchups["opponent_representation"],
                    "Matches": selected_matchups["all_matches"],
                    "W": selected_matchups["wins"],
                    "L": selected_matchups["losses"],
                    "T": selected_matchups["ties"],
                    "Raw matchup WR": selected_matchups["raw_win_rate"],
                    "Tie rate": selected_matchups["tie_rate"],
                    "Top Cut conversion": selected_matchups.apply(
                        lambda row: (
                            f"{row.opponent_top_cut_entries}/"
                            f"{row.opponent_conversion_eligible_entries} "
                            f"({row.opponent_top_cut_rate:.1%})"
                            if pd.notna(row.opponent_top_cut_rate)
                            else "NA"
                        ),
                        axis=1,
                    ),
                }
            )
            st.dataframe(
                table,
                width="stretch",
                hide_index=True,
                column_config={
                    "Opponent share": st.column_config.NumberColumn(format="percent"),
                    "Raw matchup WR": st.column_config.NumberColumn(format="percent"),
                    "Tie rate": st.column_config.NumberColumn(format="percent"),
                },
            )
            st.download_button(
                "Export matchup table",
                dataframe_to_safe_csv_bytes(table),
                file_name=f"{selected_id}_matchups.csv",
                mime="text/csv",
            )

    with st.container(border=True):
        st.subheader("Weekly trend")
        trend = compute_deck_period_series(
            tournaments,
            entries,
            matches,
            deck_id=selected_id,
            start_date=selected_start,
            end_date=selected_end,
            minimum_players=minimum_players,
            match_scope=match_scope,
            focus_player_ids=analysis_player_ids,
        )
        trend_columns = st.columns(3)
        trend_columns[0].altair_chart(
            trend_chart(trend, "representation", "Representation"), width="stretch"
        )
        trend_columns[1].altair_chart(
            trend_chart(trend, "overall_raw_win_rate", "Overall raw WR"),
            width="stretch",
        )
        if trend["top_cut_rate"].notna().any():
            trend_columns[2].altair_chart(
                trend_chart(trend, "top_cut_rate", "Top Cut rate"), width="stretch"
            )
        else:
            trend_columns[2].info(
                "No conversion-eligible event in these weekly buckets."
            )

    with st.container(border=True):
        st.subheader("Representative decklists")
        selected_decklists = load_decklists(
            DATABASE_PATH.stat().st_mtime,
            selected_id,
            tuple(sorted(included_ids)),
        )
        representative_lists = select_representative_decklists(
            filtered_tournaments,
            filtered_entries,
            selected_decklists,
            deck_id=selected_id,
            limit=3,
        )
        st.caption(
            (
                "The selected population's best finish with this deck in each "
                "tournament; "
                if analysis_player_ids
                else "One best-finishing list per tournament; "
            )
            + "ranked by tournament size, up to three tournaments in the current window."
        )
        if representative_lists.empty:
            st.info(
                "No published decklist is available for this deck in the current window."
            )
        else:
            for index, row in enumerate(
                representative_lists.itertuples(index=False)
            ):
                placing = (
                    f"#{int(row.placing)}" if pd.notna(row.placing) else "Unplaced"
                )
                expander_title = (
                    f"{index + 1}. {escape_markdown(str(row.tournament_name))} · "
                    f"{int(row.players):,} players · {placing}"
                )
                with st.expander(expander_title, expanded=index == 0):
                    detail_column, link_column = st.columns([4, 2])
                    with detail_column:
                        st.caption(
                            escape_markdown(
                                f"{row.tournament_date} · {row.player_name} · "
                                f"{int(row.wins)}-{int(row.losses)}-{int(row.ties)}"
                            )
                        )
                    with link_column:
                        st.link_button(
                            "Open on Limitless",
                            "https://play.limitlesstcg.com/tournament/"
                            f"{row.tournament_id}/player/{row.player_id}/decklist",
                            width="stretch",
                        )
                    card_sections = decklist_cards(row.decklist_json)
                    section_columns = st.columns(3)
                    for section_column, (section_name, card_frame) in zip(
                        section_columns, card_sections.items(), strict=True
                    ):
                        with section_column:
                            total_cards = (
                                int(card_frame["Qty"].sum())
                                if not card_frame.empty
                                else 0
                            )
                            st.markdown(f"**{section_name} ({total_cards})**")
                            st.dataframe(
                                card_frame, width="stretch", hide_index=True
                            )

with tabs[2]:
    st.subheader("Matchup matrix")
    st.caption(
        f"Automatically shows up to the top {MAX_MATRIX_ARCHETYPES} archetypes by "
        "representation. Use Minimum matchup N in the sidebar to control reliability."
    )
    matrix_summary = deck_summary
    if hide_unknown:
        matrix_summary = matrix_summary[matrix_summary["deck_id"] != UNKNOWN_DECK_ID]
    matrix_size = min(MAX_MATRIX_ARCHETYPES, len(matrix_summary))
    matrix_ids = matrix_summary.head(matrix_size)["deck_id"].tolist()
    matrix_names = matrix_summary.head(matrix_size)["deck_name"].tolist()
    if analysis_player_ids:
        opponent_summary = (
            matchups[
                ["deck_b", "deck_b_name", "opponent_representation"]
            ]
            .drop_duplicates("deck_b")
            .sort_values(["opponent_representation", "deck_b_name"], ascending=[False, True])
        )
        if hide_unknown:
            opponent_summary = opponent_summary[opponent_summary["deck_b"] != UNKNOWN_DECK_ID]
        opponent_ids = opponent_summary.head(matrix_size)["deck_b"].tolist()
        opponent_names = opponent_summary.head(matrix_size)["deck_b_name"].tolist()
    else:
        opponent_ids = matrix_ids
        opponent_names = matrix_names
    matrix = matchups[
        matchups["deck_a"].isin(matrix_ids)
        & matchups["deck_b"].isin(opponent_ids)
        & (matchups["n_decided"] >= minimum_n)
        & matchups["raw_win_rate"].notna()
    ].copy()
    if matrix.empty:
        st.info("No matrix cells meet the current minimum N.")
    else:
        heatmap = (
            alt.Chart(matrix)
            .mark_rect()
            .encode(
                x=alt.X("deck_b_name:N", title="Opponent", sort=opponent_names),
                y=alt.Y("deck_a_name:N", title="Selected deck", sort=matrix_names),
                color=alt.Color(
                    "raw_win_rate:Q",
                    title="Raw matchup WR",
                    scale=alt.Scale(
                        domain=[0.25, 0.50, 0.75],
                        range=[LOW_BLUE, NEUTRAL_GRAY, HIGH_RED],
                        clamp=True,
                    ),
                    legend=alt.Legend(format=".0%"),
                ),
                tooltip=[
                    alt.Tooltip("deck_a_name:N", title="Deck"),
                    alt.Tooltip("deck_b_name:N", title="Opponent"),
                    alt.Tooltip("wins:Q", title="W"),
                    alt.Tooltip("losses:Q", title="L"),
                    alt.Tooltip("n_decided:Q", title="N"),
                    alt.Tooltip("raw_win_rate:Q", title="Raw WR", format=".1%"),
                ],
            )
            .properties(height=max(430, len(matrix_ids) * 28))
        )
        st.altair_chart(heatmap, width="stretch")
        st.caption(
            "Each row is the selected deck's perspective. Blue is below 50%, red is above "
            "50%, and blank cells are below the presentation-only minimum N."
        )

with tabs[3]:
    period_days = (selected_end - selected_start).days + 1
    previous_end = selected_start - timedelta(days=1)
    previous_start = previous_end - timedelta(days=period_days - 1)
    st.caption(
        f"Current: {selected_start.isoformat()} – {selected_end.isoformat()} · "
        f"Previous equal window: {previous_start.isoformat()} – {previous_end.isoformat()}"
    )
    previous_tournaments, previous_entries, previous_matches = filter_observed_window(
        tournaments,
        entries,
        matches,
        start_date=previous_start,
        end_date=previous_end,
        minimum_players=minimum_players,
    )
    if analysis_player_ids:
        previous_focus_entries = previous_entries[
            previous_entries["player_id"].astype(str).isin(analysis_player_ids)
        ]
        previous_has_data = not previous_focus_entries.empty
        previous_summary, _ = compute_cohort_metrics(
            previous_tournaments,
            previous_entries,
            previous_matches,
            focus_player_ids=analysis_player_ids,
            match_scope=match_scope,
        )
    else:
        previous_has_data = not previous_tournaments.empty
        previous_summary, _ = compute_metrics(
            previous_tournaments, previous_entries, previous_matches, match_scope=match_scope
        )
    if not previous_has_data:
        st.info(
            (f"{scope_label} has no eligible entry" if analysis_player_ids else
             "The database contains no eligible tournament")
            + " in the previous equal-length window."
        )
    else:
        comparison = deck_summary.merge(
            previous_summary,
            on="deck_id",
            how="outer",
            suffixes=("_current", "_previous"),
        )
        comparison["deck_name"] = comparison["deck_name_current"].fillna(
            comparison["deck_name_previous"]
        )
        for column in ("entries", "representation"):
            comparison[f"{column}_current"] = comparison[f"{column}_current"].fillna(0)
            comparison[f"{column}_previous"] = comparison[f"{column}_previous"].fillna(0)
        comparison["representation_delta_pp"] = (
            comparison["representation_current"] - comparison["representation_previous"]
        ) * 100
        comparison["raw_wr_delta_pp"] = (
            comparison["overall_raw_win_rate_current"]
            - comparison["overall_raw_win_rate_previous"]
        ) * 100
        comparison["top_cut_delta_pp"] = (
            comparison["top_cut_rate_current"] - comparison["top_cut_rate_previous"]
        ) * 100
        if hide_unknown:
            comparison = comparison[comparison["deck_id"] != UNKNOWN_DECK_ID]

        delta_chart_source = comparison.copy()
        delta_chart_source["absolute_delta"] = delta_chart_source[
            "representation_delta_pp"
        ].abs()
        delta_chart_source = delta_chart_source.nlargest(15, "absolute_delta")
        delta_chart_source["direction"] = delta_chart_source["representation_delta_pp"].map(
            lambda value: "Increased" if value >= 0 else "Decreased"
        )
        delta_chart = (
            alt.Chart(delta_chart_source)
            .mark_bar()
            .encode(
                x=alt.X("representation_delta_pp:Q", title="Representation change (pp)"),
                y=alt.Y(
                    "deck_name:N", title=None,
                    sort=alt.SortField("absolute_delta", order="descending"),
                ),
                color=alt.Color(
                    "direction:N",
                    title="Representation direction",
                    scale=alt.Scale(
                        domain=["Decreased", "Increased"], range=[LOW_BLUE, HIGH_RED]
                    ),
                ),
                tooltip=[
                    alt.Tooltip("deck_name:N", title="Deck"),
                    alt.Tooltip("representation_previous:Q", title="Previous", format=".2%"),
                    alt.Tooltip("representation_current:Q", title="Current", format=".2%"),
                    alt.Tooltip("representation_delta_pp:Q", title="Change (pp)", format="+.2f"),
                ],
            )
            .properties(height=max(300, len(delta_chart_source) * 27))
        )
        st.altair_chart(delta_chart, width="stretch")

        comparison_table = comparison[
            [
                "deck_name", "entries_previous", "entries_current",
                "representation_previous", "representation_current", "representation_delta_pp",
                "overall_raw_win_rate_previous", "overall_raw_win_rate_current", "raw_wr_delta_pp",
                "top_cut_rate_previous", "top_cut_rate_current", "top_cut_delta_pp",
            ]
        ].rename(
            columns={
                "deck_name": "Deck", "entries_previous": "Previous entries",
                "entries_current": "Current entries",
                "representation_previous": "Previous representation",
                "representation_current": "Current representation",
                "representation_delta_pp": "Representation Δ (pp)",
                "overall_raw_win_rate_previous": "Previous WR",
                "overall_raw_win_rate_current": "Current WR",
                "raw_wr_delta_pp": "WR Δ (pp)",
                "top_cut_rate_previous": "Previous Top Cut rate",
                "top_cut_rate_current": "Current Top Cut rate",
                "top_cut_delta_pp": "Top Cut Δ (pp)",
            }
        ).sort_values("Representation Δ (pp)", key=lambda values: values.abs(), ascending=False)
        st.dataframe(
            comparison_table,
            width="stretch",
            hide_index=True,
            column_config={
                "Previous representation": st.column_config.NumberColumn(format="percent"),
                "Current representation": st.column_config.NumberColumn(format="percent"),
                "Previous WR": st.column_config.NumberColumn(format="percent"),
                "Current WR": st.column_config.NumberColumn(format="percent"),
                "Previous Top Cut rate": st.column_config.NumberColumn(format="percent"),
                "Current Top Cut rate": st.column_config.NumberColumn(format="percent"),
            },
        )

st.divider()
st.caption(
    "Independent, unofficial analytics. Not affiliated with or endorsed by Limitless "
    "or The Pokémon Company. Pokémon and related names belong to their respective owners."
)
