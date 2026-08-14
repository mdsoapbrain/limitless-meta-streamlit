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

from limitless_meta.database import read_tables  # noqa: E402
from limitless_meta.metrics import (  # noqa: E402
    compute_deck_period_series,
    compute_metrics,
    filter_observed_window,
    select_representative_decklists,
)
from limitless_meta.models import UNKNOWN_DECK_ID  # noqa: E402


DATABASE_PATH = PROJECT_ROOT / "data" / "meta.duckdb"
SUPPORT_URL = "https://buymeacoffee.com/qmi0000011"
LOW_SAMPLE_N = 20
LOW_BLUE = "#3f7cac"
HIGH_RED = "#d26a5c"
NEUTRAL_GRAY = "#f3f4f6"
ACCENT_CYAN = "#00A0C8"


st.set_page_config(page_title="Limitless PTCGL Meta Analyzer", page_icon="⚡", layout="wide")
st.title("Limitless PTCGL Online Tournament Meta Analyzer")
st.caption(
    "Descriptive analysis of the selected observed period. Weighted Impact is matchup "
    "importance under that observed representation—not a forecast."
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
            "tournament_audit",
            "topcut_diagnostics",
            "decklists",
            "run_metadata",
        ],
    )


def representation_chart(summary: pd.DataFrame, limit: int = 15) -> alt.Chart:
    source = summary.head(limit).copy()
    source["representation_label"] = source["representation"].map(lambda value: f"{value:.1%}")
    bars = (
        alt.Chart(source)
        .mark_bar(color=ACCENT_CYAN)
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


def impact_chart(selected_matchups: pd.DataFrame, limit: int = 15) -> alt.Chart:
    source = selected_matchups.copy()
    source["absolute_impact"] = source["weighted_impact"].abs()
    source = source.sort_values("absolute_impact", ascending=False).head(limit)
    source["impact_pp"] = source["weighted_impact"] * 100
    source["direction"] = source["impact_pp"].map(
        lambda value: "Favorable" if value >= 0 else "Unfavorable"
    )
    return (
        alt.Chart(source)
        .mark_bar()
        .encode(
            x=alt.X("impact_pp:Q", title="Weighted Impact (percentage points)"),
            y=alt.Y("deck_b_name:N", title=None, sort=alt.SortField("absolute_impact", order="descending")),
            color=alt.Color(
                "direction:N",
                title="Observed direction",
                scale=alt.Scale(
                    domain=["Unfavorable", "Favorable"], range=[LOW_BLUE, HIGH_RED]
                ),
            ),
            tooltip=[
                alt.Tooltip("deck_b_name:N", title="Opponent"),
                alt.Tooltip("wins:Q", title="W"),
                alt.Tooltip("losses:Q", title="L"),
                alt.Tooltip("n_decided:Q", title="N"),
                alt.Tooltip("raw_win_rate:Q", title="Raw WR", format=".1%"),
                alt.Tooltip("opponent_representation:Q", title="Opponent representation", format=".1%"),
                alt.Tooltip("impact_pp:Q", title="Weighted Impact (pp)", format="+.2f"),
            ],
        )
        .properties(height=max(280, len(source) * 27))
    )


def trend_chart(source: pd.DataFrame, column: str, title: str) -> alt.Chart:
    return (
        alt.Chart(source)
        .mark_line(point=True, color=ACCENT_CYAN)
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
decklists = data["decklists"].copy()
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

with st.sidebar:
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
    minimum_n = st.number_input("Minimum matchup N", min_value=0, value=10, step=1)
    hide_unknown = st.checkbox("Hide UNKNOWN decks", value=True)
    debug_mode = st.checkbox("Debug mode", value=False)

if selected_start > selected_end:
    st.error("Start date must be on or before end date.")
    st.stop()

filtered_tournaments, filtered_entries, filtered_matches = filter_observed_window(
    tournaments,
    entries,
    matches,
    start_date=selected_start,
    end_date=selected_end,
    minimum_players=minimum_players,
)
included_ids = set(filtered_tournaments["tournament_id"])
deck_summary, matchups = compute_metrics(
    filtered_tournaments, filtered_entries, filtered_matches, match_scope=match_scope
)

if deck_summary.empty:
    st.warning("No entries match these filters. Broaden the window or lower the player threshold.")
    st.stop()

selector_summary = deck_summary
if hide_unknown:
    selector_summary = selector_summary[selector_summary["deck_id"] != UNKNOWN_DECK_ID]
label_to_id = {
    f"{row.deck_name} · {row.deck_id}": row.deck_id
    for row in selector_summary.sort_values(["entries", "deck_name"], ascending=[False, True]).itertuples()
}
with st.sidebar:
    st.divider()
    selected_label = st.selectbox("Deck", list(label_to_id))
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
            background: #00A0C8;
            color: #002147 !important;
            font-weight: 600;
            text-decoration: none !important;
            box-shadow: 0 0.2rem 0.6rem rgba(0, 0, 0, 0.22);
        }}
        .bmc-sidebar-link:hover {{
            background: #35B6D5;
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
selected_id = label_to_id[selected_label]
selected = deck_summary[deck_summary["deck_id"] == selected_id].iloc[0]

tabs = st.tabs(
    [
        "Overview",
        "Selected deck",
        "Matchup heatmap",
        "Period comparison",
        "Tournament drill-down",
        "Tournament audit",
        "Top Cut diagnostics",
    ]
)

with tabs[0]:
    overview_metrics = st.columns(3)
    overview_metrics[0].metric("Eligible tournaments", f"{len(filtered_tournaments):,}")
    overview_metrics[1].metric("Eligible entries", f"{len(filtered_entries):,}")
    overview_metrics[2].metric("Archetypes", f"{len(deck_summary):,}")

    chart_summary = deck_summary
    if hide_unknown:
        chart_summary = chart_summary[chart_summary["deck_id"] != UNKNOWN_DECK_ID]
    st.subheader("Observed representation")
    st.altair_chart(representation_chart(chart_summary), width="stretch")
    st.caption("Top 15 archetypes by tournament-entry representation; UNKNOWN remains in the denominator.")

    global_table = chart_summary[
        [
            "deck_name", "deck_id", "entries", "representation", "wins", "losses",
            "n_decided", "overall_raw_win_rate", "top_cut_entries",
            "conversion_eligible_entries", "top_cut_rate",
        ]
    ].rename(
        columns={
            "deck_name": "Deck", "deck_id": "Deck ID", "entries": "Entries",
            "representation": "Representation", "wins": "W", "losses": "L",
            "n_decided": "N", "overall_raw_win_rate": "Overall WR",
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
            "Overall WR": st.column_config.NumberColumn(format="percent"),
            "Top Cut Rate": st.column_config.NumberColumn(format="percent"),
        },
    )
    st.download_button(
        "Export global summary",
        global_table.to_csv(index=False).encode("utf-8"),
        file_name="deck_summary_filtered.csv",
        mime="text/csv",
    )

with tabs[1]:
    metric_columns = st.columns(4)
    metric_columns[0].metric("Representation", f"{selected.representation:.1%}")
    metric_columns[1].metric(
        "Overall raw WR",
        f"{selected.overall_raw_win_rate:.1%}" if pd.notna(selected.overall_raw_win_rate) else "NA",
        help="Wins / (wins + losses); ties and byes excluded.",
    )
    metric_columns[2].metric("Entries", f"{selected.entries:,}")
    metric_columns[3].metric("Tournaments represented", f"{selected.tournament_count:,}")
    conversion = (
        f"{selected.top_cut_entries}/{selected.conversion_eligible_entries} "
        f"({selected.top_cut_rate:.2%})"
        if pd.notna(selected.top_cut_rate)
        else "NA"
    )
    st.markdown(f"**Top Cut / Conversion:** {conversion}")
    st.caption(
        f"Overall decided record: {selected.wins:,}-{selected.losses:,}. "
        f"Internally retained ties: {selected.ties:,}."
    )

    st.subheader("Representative decklists")
    representative_lists = select_representative_decklists(
        filtered_tournaments,
        filtered_entries,
        decklists,
        deck_id=selected_id,
        limit=3,
    )
    st.caption(
        "One best-finishing list per tournament, ranked by tournament size; "
        "up to three tournaments in the current observed window."
    )
    if representative_lists.empty:
        st.info("No published decklist is available for this deck in the current window.")
    else:
        list_tabs = st.tabs(
            [
                (
                    f"{index + 1} · {int(row.players):,} players · "
                    f"#{int(row.placing)}" if pd.notna(row.placing)
                    else f"{index + 1} · {int(row.players):,} players · unplaced"
                )
                for index, row in enumerate(representative_lists.itertuples(index=False))
            ]
        )
        for list_tab, row in zip(
            list_tabs, representative_lists.itertuples(index=False), strict=True
        ):
            with list_tab:
                detail_column, link_column = st.columns([4, 2])
                with detail_column:
                    st.markdown(f"**{row.tournament_name}**")
                    placing = f"#{int(row.placing)}" if pd.notna(row.placing) else "Unplaced"
                    st.caption(
                        f"{row.tournament_date} · {int(row.players):,} players · "
                        f"{row.player_name} · {placing} · "
                        f"{int(row.wins)}-{int(row.losses)}-{int(row.ties)}"
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
                        total_cards = int(card_frame["Qty"].sum()) if not card_frame.empty else 0
                        st.markdown(f"**{section_name} ({total_cards})**")
                        st.dataframe(card_frame, width="stretch", hide_index=True)

    selected_matchups = matchups[
        (matchups["deck_a"] == selected_id) & (matchups["n_decided"] >= minimum_n)
    ].copy()
    if hide_unknown:
        selected_matchups = selected_matchups[selected_matchups["deck_b"] != UNKNOWN_DECK_ID]

    st.subheader("Observed matchup impact")
    if selected_matchups.empty:
        st.info("No matchups meet the current minimum N.")
    else:
        st.altair_chart(impact_chart(selected_matchups), width="stretch")
        st.caption(
            "Positive and negative bars show representation-weighted deviation from 50%; "
            "they do not predict a future win rate."
        )

    st.subheader("Observed weekly trend")
    trend = compute_deck_period_series(
        tournaments,
        entries,
        matches,
        deck_id=selected_id,
        start_date=selected_start,
        end_date=selected_end,
        minimum_players=minimum_players,
        match_scope=match_scope,
    )
    trend_columns = st.columns(3)
    trend_columns[0].altair_chart(
        trend_chart(trend, "representation", "Representation"), width="stretch"
    )
    trend_columns[1].altair_chart(
        trend_chart(trend, "overall_raw_win_rate", "Overall raw WR"), width="stretch"
    )
    if trend["top_cut_rate"].notna().any():
        trend_columns[2].altair_chart(
            trend_chart(trend, "top_cut_rate", "Top Cut rate"), width="stretch"
        )
    else:
        trend_columns[2].info("No conversion-eligible event in these weekly buckets.")

    sort_label = st.selectbox(
        "Sort matchup table by",
        [
            "Absolute Weighted Impact", "Representation", "Raw Matchup WR", "N",
            "Weighted Impact", "Top Cut Rate", "Conversion count",
        ],
    )
    sort_map = {
        "Representation": ("opponent_representation", False),
        "Raw Matchup WR": ("raw_win_rate", False),
        "N": ("n_decided", False),
        "Weighted Impact": ("weighted_impact", False),
        "Top Cut Rate": ("opponent_top_cut_rate", False),
        "Conversion count": ("opponent_top_cut_entries", False),
    }
    if sort_label == "Absolute Weighted Impact":
        selected_matchups["_sort"] = selected_matchups["weighted_impact"].abs()
        selected_matchups = selected_matchups.sort_values("_sort", ascending=False)
    else:
        column, ascending = sort_map[sort_label]
        selected_matchups = selected_matchups.sort_values(column, ascending=ascending, na_position="last")

    low_sample_count = int((selected_matchups["n_decided"] < LOW_SAMPLE_N).sum())
    if low_sample_count:
        st.warning(
            f"{low_sample_count} displayed matchup(s) have N < {LOW_SAMPLE_N}. "
            "Their raw rates are retained but should be read cautiously."
        )
    table = pd.DataFrame(
        {
            "Opponent": selected_matchups["deck_b_name"],
            "Representation": selected_matchups["opponent_representation"],
            "W": selected_matchups["wins"],
            "L": selected_matchups["losses"],
            "N": selected_matchups["n_decided"],
            "Sample": selected_matchups["n_decided"].map(
                lambda value: f"Low N (<{LOW_SAMPLE_N})" if value < LOW_SAMPLE_N else ""
            ),
            "Raw Matchup WR": selected_matchups["raw_win_rate"],
            "Weighted Impact (pp)": selected_matchups["weighted_impact"] * 100,
            "Top Cut Rate / Conversion": selected_matchups.apply(
                lambda row: (
                    f"{row.opponent_top_cut_entries}/{row.opponent_conversion_eligible_entries} "
                    f"({row.opponent_top_cut_rate:.2%})"
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
            "Representation": st.column_config.NumberColumn(format="percent"),
            "Raw Matchup WR": st.column_config.NumberColumn(format="percent"),
            "Weighted Impact (pp)": st.column_config.NumberColumn(format="%+.2f pp"),
        },
    )
    st.download_button(
        "Export selected matchups",
        table.to_csv(index=False).encode("utf-8"),
        file_name=f"{selected_id}_matchups.csv",
        mime="text/csv",
    )

with tabs[2]:
    matrix_size = st.slider("Archetypes in matrix", min_value=5, max_value=25, value=15)
    matrix_summary = deck_summary
    if hide_unknown:
        matrix_summary = matrix_summary[matrix_summary["deck_id"] != UNKNOWN_DECK_ID]
    matrix_ids = matrix_summary.head(matrix_size)["deck_id"].tolist()
    matrix_names = matrix_summary.head(matrix_size)["deck_name"].tolist()
    matrix = matchups[
        matchups["deck_a"].isin(matrix_ids)
        & matchups["deck_b"].isin(matrix_ids)
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
                x=alt.X("deck_b_name:N", title="Opponent", sort=matrix_names),
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
                    alt.Tooltip("weighted_impact:Q", title="Weighted Impact", format="+.2%"),
                ],
            )
            .properties(height=max(430, matrix_size * 28))
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
    if previous_tournaments.empty:
        st.info(
            "The database does not contain eligible tournaments for the previous equal-length "
            "window. Run analysis with an earlier start date to enable this comparison."
        )
    else:
        previous_summary, _ = compute_metrics(
            previous_tournaments, previous_entries, previous_matches, match_scope=match_scope
        )
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

with tabs[4]:
    event_options = {
        f"{row.date} · {row.name} · {row.players} players": row.tournament_id
        for row in filtered_tournaments.sort_values(["date", "players"], ascending=[False, False]).itertuples()
    }
    event_label = st.selectbox("Tournament", list(event_options))
    event_id = event_options[event_label]
    event = filtered_tournaments[filtered_tournaments["tournament_id"] == event_id].iloc[0]
    event_entries = filtered_entries[filtered_entries["tournament_id"] == event_id].copy()
    event_matches = filtered_matches[filtered_matches["tournament_id"] == event_id].copy()
    event_summary, _ = compute_metrics(
        filtered_tournaments[filtered_tournaments["tournament_id"] == event_id],
        event_entries,
        event_matches,
        match_scope=match_scope,
    )
    valid_event_matches = event_matches[
        event_matches["result"].isin(["A_WIN", "B_WIN"])
        & event_matches["player_a"].notna()
        & event_matches["player_b"].notna()
    ]
    event_metrics = st.columns(4)
    event_metrics[0].metric("Players", f"{event.players:,}")
    event_metrics[1].metric("Loaded entries", f"{len(event_entries):,}")
    event_metrics[2].metric("Decided matches", f"{len(valid_event_matches):,}")
    event_metrics[3].metric(
        "Top Cut", f"{int(event.top_cut_size)}" if pd.notna(event.top_cut_size) else "NA"
    )
    completion = getattr(event, "is_complete", None)
    if completion is not None and not bool(completion):
        st.warning("This tournament appears incomplete; its cache will be refreshed after the configured TTL.")

    event_visual = event_summary
    if hide_unknown:
        event_visual = event_visual[event_visual["deck_id"] != UNKNOWN_DECK_ID]
    st.altair_chart(representation_chart(event_visual, limit=12), width="stretch")

    cut_entries = event_entries[event_entries["top_cut"].fillna(False).astype(bool)][
        ["placing", "player_id", "deck_name", "deck_id", "wins", "losses", "ties"]
    ].sort_values("placing")
    st.subheader("Top Cut entrants")
    if cut_entries.empty:
        st.info("No explicit Top Cut was detected for this tournament.")
    else:
        st.dataframe(cut_entries, width="stretch", hide_index=True)

    deck_lookup = event_entries.set_index("player_id")[["deck_name", "deck_id"]]
    match_detail = event_matches.copy()
    match_detail["deck_a"] = match_detail["player_a"].map(deck_lookup["deck_name"])
    match_detail["deck_b"] = match_detail["player_b"].map(deck_lookup["deck_name"])
    match_columns = [
        "phase_type", "round", "table_or_match", "player_a", "deck_a",
        "player_b", "deck_b", "winner", "result",
    ]
    st.subheader("Pairing audit")
    st.dataframe(match_detail[match_columns], width="stretch", hide_index=True)
    st.download_button(
        "Export tournament pairings",
        match_detail[match_columns].to_csv(index=False).encode("utf-8"),
        file_name=f"{event_id}_pairings.csv",
        mime="text/csv",
    )

with tabs[5]:
    audit = data["tournament_audit"].copy()
    audit["date"] = pd.to_datetime(audit["date"]).dt.date
    visible_audit = audit[(audit["date"] >= selected_start) & (audit["date"] <= selected_end)]
    if not debug_mode:
        visible_audit = visible_audit[visible_audit["included"].fillna(False)]
    audit_columns = [
        "name", "date", "players", "organizer", "format", "platform", "included",
        "exclusion_reason", "is_complete", "top_cut_detected", "top_cut_size",
    ]
    audit_columns = [column for column in audit_columns if column in visible_audit.columns]
    st.dataframe(visible_audit[audit_columns], width="stretch", hide_index=True)
    st.download_button(
        "Export tournament audit",
        visible_audit.to_csv(index=False).encode("utf-8"),
        file_name="tournament_audit_filtered.csv",
        mime="text/csv",
    )

with tabs[6]:
    diagnostics = data["topcut_diagnostics"]
    diagnostics = diagnostics[diagnostics["tournament_id"].isin(included_ids)]
    st.dataframe(diagnostics, width="stretch", hide_index=True)
    suspicious_count = (
        int(diagnostics["suspicious"].fillna(False).sum()) if not diagnostics.empty else 0
    )
    st.caption(f"Suspicious Top Cut detections requiring manual inspection: {suspicious_count}")

st.divider()
st.caption(
    "Independent, unofficial analytics. Not affiliated with or endorsed by Limitless "
    "or The Pokémon Company. Pokémon and related names belong to their respective owners."
)
