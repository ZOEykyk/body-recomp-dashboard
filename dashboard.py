from __future__ import annotations

import datetime as dt
import html
import math
import textwrap
from typing import Any, Callable

import altair as alt
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from bodyos_standard import SCORE_COMPONENTS, SCORE_COMPONENT_MAXIMA
from data_integrity import format_optional_number, format_weight_kg, valid_weight_series
from nutrition_intelligence import analyze_nutrition
from workout_intelligence import analyze_workout

X_AXIS_LABEL_ANGLE = -40
X_AXIS_LABEL_FONT_SIZE = 16
SCORE_LABELS = [
    (90, "🟢 Excellent", "#2ca02c"),
    (80, "🔵 Good", "#1f77b4"),
    (70, "🟡 Fair", "#f2c94c"),
    (60, "🟠 Needs Attention", "#f2994a"),
    (0, "🔴 Recovery Needed", "#d62728"),
]
SCORE_COMPONENT_LABELS = {
    "体重スコア": "体重",
    "食事スコア": "食事",
    "タンパク質スコア": "タンパク質",
    "歩数スコア": "歩数",
    "筋トレスコア": "筋トレ",
    "睡眠スコア": "睡眠",
    "体調スコア": "体調",
    "飲酒スコア": "飲酒",
}


def parse_number(value: Any, default: float = 0) -> float:
    try:
        if value is None or pd.isna(value):
            return default
    except (TypeError, ValueError):
        pass
    text = str(value).replace(",", "").strip()
    if text == "":
        return default
    try:
        return float(text)
    except ValueError:
        return default


def score_label(score: Any) -> str:
    value = parse_number(score, default=0)
    for threshold, label, _color in SCORE_LABELS:
        if value >= threshold:
            return label
    return SCORE_LABELS[-1][1]


def score_color_scale() -> alt.Scale:
    return alt.Scale(
        domain=[label for _threshold, label, _color in SCORE_LABELS],
        range=[color for _threshold, _label, color in SCORE_LABELS],
    )


def dashboard_x_axis(title: str) -> alt.Axis:
    return alt.Axis(
        title=title,
        labelAngle=X_AXIS_LABEL_ANGLE,
        labelFontSize=X_AXIS_LABEL_FONT_SIZE,
        labelLimit=140,
    )


def apply_dashboard_axis_config(chart: alt.Chart | alt.LayerChart) -> alt.Chart | alt.LayerChart:
    return chart.configure_axisX(
        labelAngle=X_AXIS_LABEL_ANGLE,
        labelFontSize=X_AXIS_LABEL_FONT_SIZE,
        labelLimit=140,
    )


def add_daily_display_columns(data: pd.DataFrame) -> pd.DataFrame:
    display = data.copy()
    dates = pd.to_datetime(display["日付"], errors="coerce")
    display["日付表示"] = dates.dt.strftime("%Y/%m/%d")
    display["日付ラベル"] = dates.dt.month.astype(str) + "/" + dates.dt.day.astype(str)
    display["Daily Label"] = display.apply(
        lambda row: f"{row['日付ラベル']} 🎉" if row.get("モード") == "EVENT" else row["日付ラベル"],
        axis=1,
    )
    display["Score Label"] = display["Body Score"].apply(score_label)
    return display


def ordered_daily_x(data: pd.DataFrame) -> alt.X:
    return alt.X(
        "Daily Label:N",
        sort=list(data["Daily Label"]),
        axis=dashboard_x_axis("日付"),
    )


def daily_line_chart(data: pd.DataFrame, y_column: str, title: str, color: str = "#1f77b4") -> alt.Chart:
    return (
        alt.Chart(data)
        .mark_line(point=True, color=color)
        .encode(
            x=ordered_daily_x(data),
            y=alt.Y(f"{y_column}:Q", title=title),
            tooltip=["日付表示", "モード", alt.Tooltip(f"{y_column}:Q", title=title)],
        )
    )


def weight_axis_domain(data: pd.DataFrame, columns: list[str]) -> list[float] | None:
    valid_values: list[float] = []
    for column in columns:
        if column not in data.columns:
            continue
        series = pd.to_numeric(data[column], errors="coerce")
        valid_values.extend(float(value) for value in series.dropna() if float(value) > 0)

    if not valid_values:
        return None

    min_weight = min(valid_values)
    max_weight = max(valid_values)
    if math.isclose(min_weight, max_weight):
        return [math.floor(min_weight - 1.5), math.ceil(max_weight + 1.5)]

    observed_range = max_weight - min_weight
    padding = max(0.5, observed_range * 0.15)
    y_min = math.floor(min_weight - padding)
    y_max = math.ceil(max_weight + padding)
    if y_min >= y_max:
        y_min = math.floor(min_weight - 1.0)
        y_max = math.ceil(max_weight + 1.0)
    return [y_min, y_max]


def daily_weight_line_chart(
    data: pd.DataFrame,
    y_column: str,
    title: str,
    y_domain: list[float] | None,
    color: str = "#1f77b4",
) -> alt.Chart:
    return (
        alt.Chart(data)
        .mark_line(point=True, color=color)
        .encode(
            x=ordered_daily_x(data),
            y=alt.Y(
                f"{y_column}:Q",
                title=title,
                scale=alt.Scale(domain=y_domain) if y_domain else alt.Undefined,
            ),
            tooltip=["日付表示", "モード", alt.Tooltip(f"{y_column}:Q", title=title)],
        )
    )


def daily_bar_chart(data: pd.DataFrame, y_column: str, title: str, color: str = "#4c78a8") -> alt.Chart:
    return (
        alt.Chart(data)
        .mark_bar(color=color)
        .encode(
            x=ordered_daily_x(data),
            y=alt.Y(f"{y_column}:Q", title=title),
            tooltip=["日付表示", "モード", alt.Tooltip(f"{y_column}:Q", title=title)],
        )
    )


def body_score_chart(data: pd.DataFrame) -> alt.LayerChart:
    base = alt.Chart(data).encode(x=ordered_daily_x(data))
    score_line = base.mark_line(color="#333333").encode(
        y=alt.Y("Body Score:Q", title="Body Score", scale=alt.Scale(domain=[0, 100])),
        tooltip=["日付表示", "モード", "Body Score", "Score Label"],
    )
    score_points = base.mark_circle(size=85).encode(
        y=alt.Y("Body Score:Q", scale=alt.Scale(domain=[0, 100])),
        color=alt.Color("Score Label:N", scale=score_color_scale(), legend=alt.Legend(title="Score Label")),
        tooltip=["日付表示", "モード", "Body Score", "Score Label"],
    )
    average_line = base.mark_line(color="#888888", strokeDash=[5, 4]).encode(
        y=alt.Y("7日平均Body Score:Q", scale=alt.Scale(domain=[0, 100])),
        tooltip=["日付表示", alt.Tooltip("7日平均Body Score:Q", format=".1f")],
    )
    return (score_line + average_line + score_points).properties(height=320)


def optional_score(value: Any) -> float | None:
    try:
        if value is None or pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, str) and not value.strip():
        return None
    parsed = parse_number(value, default=None)
    return parsed if parsed is not None else None


def achievement_rate(score: Any, maximum: int) -> float | None:
    actual = optional_score(score)
    if actual is None or maximum <= 0:
        return None
    return max(0.0, min(100.0, actual / maximum * 100))


def format_component_score(score: Any, maximum: int) -> str:
    actual = optional_score(score)
    if actual is None:
        return "—"
    return f"{actual:g} / {maximum}"


def format_percentage(value: Any) -> str:
    try:
        if value is None or pd.isna(value):
            return "—"
    except (TypeError, ValueError):
        pass
    return f"{float(value):.0f}%"


def component_rate_series(data: pd.DataFrame, component: str) -> pd.Series:
    maximum = SCORE_COMPONENT_MAXIMA[component]
    return data[component].apply(lambda value: achievement_rate(value, maximum))


def seven_day_average_percentage(data: pd.DataFrame, component: str) -> float | None:
    valid_rates = component_rate_series(data, component).dropna()
    if valid_rates.empty:
        return None
    return float(valid_rates.tail(7).mean())


def component_trend(data: pd.DataFrame, component: str) -> str:
    valid_rates = component_rate_series(data, component).dropna()
    if len(valid_rates) < 8:
        return "データ不足"

    recent = valid_rates.tail(7).mean()
    previous = valid_rates.iloc[:-7].tail(7).mean()
    if pd.isna(previous):
        return "データ不足"

    delta = recent - previous
    if delta >= 3:
        return "↑ improving"
    if delta <= -3:
        return "↓ declining"
    return "→ stable"


def trend_class(trend: str) -> str:
    if trend.startswith("↑"):
        return "trend-up"
    if trend.startswith("↓"):
        return "trend-down"
    if trend.startswith("→"):
        return "trend-stable"
    return "trend-insufficient"


def score_component_rows(chart_df: pd.DataFrame) -> list[dict[str, Any]]:
    latest = chart_df.iloc[-1]
    rows: list[dict[str, Any]] = []
    for component in SCORE_COMPONENTS:
        maximum = SCORE_COMPONENT_MAXIMA[component]
        actual = latest.get(component)
        current_rate = achievement_rate(actual, maximum)
        rows.append(
            {
                "component": component,
                "label": SCORE_COMPONENT_LABELS.get(component, component.replace("スコア", "")),
                "actual": actual,
                "maximum": maximum,
                "current_rate": current_rate,
                "seven_day_average": seven_day_average_percentage(chart_df, component),
                "trend": component_trend(chart_df, component),
            }
        )
    return rows


def score_component_styles() -> str:
    return textwrap.dedent(
        """
    <style>
      .bodyos-component-section,
      .bodyos-component-section * {
        box-sizing: border-box;
        min-width: 0;
      }
      .bodyos-component-section .bodyos-component-grid {
        display: grid;
        gap: 0.9rem;
        width: 100%;
        max-width: 100%;
        overflow-x: hidden;
      }
      .bodyos-component-section .bodyos-priority-grid {
        grid-template-columns: repeat(3, minmax(0, 1fr));
        margin: 0.25rem 0 1.25rem;
      }
      .bodyos-component-section .bodyos-card-grid {
        grid-template-columns: repeat(4, minmax(0, 1fr));
        margin-top: 0.5rem;
      }
      .bodyos-component-section .bodyos-component-card {
        border: 1px solid rgba(49, 51, 63, 0.18);
        border-radius: 8px;
        padding: 0.85rem 0.95rem;
        background: #fff;
        color: #31313f;
        opacity: 1;
        filter: none;
        backdrop-filter: none;
        mix-blend-mode: normal;
        overflow-wrap: anywhere;
        word-break: normal;
      }
      .bodyos-component-section .bodyos-component-label {
        color: #31313f;
        font-weight: 700;
        line-height: 1.35;
        margin-bottom: 0.55rem;
      }
      .bodyos-component-section .bodyos-component-score {
        color: rgba(49, 51, 63, 0.82);
        font-size: 0.98rem;
        line-height: 1.3;
        margin-bottom: 0.45rem;
      }
      .bodyos-component-section .bodyos-component-rate {
        color: #31313f;
        font-size: 2rem;
        font-weight: 750;
        line-height: 1.05;
        margin-bottom: 0.35rem;
      }
      .bodyos-component-section .bodyos-component-meta {
        color: rgba(49, 51, 63, 0.68);
        font-size: 0.9rem;
        line-height: 1.45;
      }
      .bodyos-component-section .bodyos-component-trend {
        display: inline-block;
        max-width: 100%;
        border-radius: 999px;
        padding: 0.12rem 0.45rem;
        margin-top: 0.35rem;
        font-size: 0.82rem;
        line-height: 1.35;
        overflow-wrap: anywhere;
      }
      .bodyos-component-section .trend-up {
        background: rgba(38, 166, 91, 0.12);
        color: #137333;
      }
      .bodyos-component-section .trend-down {
        background: rgba(214, 39, 40, 0.11);
        color: #9f1d1d;
      }
      .bodyos-component-section .trend-stable,
      .bodyos-component-section .trend-insufficient {
        background: rgba(49, 51, 63, 0.08);
        color: rgba(49, 51, 63, 0.78);
      }
      .bodyos-component-section .bodyos-progress-track {
        height: 0.48rem;
        width: 100%;
        border-radius: 999px;
        background: rgba(49, 51, 63, 0.08);
        overflow: hidden;
        margin-top: 0.75rem;
      }
      .bodyos-component-section .bodyos-progress-fill {
        height: 100%;
        border-radius: inherit;
        background: #1f77b4;
      }
      @media (max-width: 900px) {
        .bodyos-component-section .bodyos-priority-grid,
        .bodyos-component-section .bodyos-card-grid {
          grid-template-columns: repeat(2, minmax(0, 1fr));
        }
      }
      @media (max-width: 520px) {
        .bodyos-component-section .bodyos-priority-grid,
        .bodyos-component-section .bodyos-card-grid {
          grid-template-columns: minmax(0, 1fr);
        }
        .bodyos-component-section .bodyos-component-card {
          padding: 0.8rem 0.85rem;
        }
        .bodyos-component-section .bodyos-component-rate {
          font-size: 1.85rem;
        }
      }
    </style>
    """
    ).strip()


def body_score_card_styles() -> str:
    return textwrap.dedent(
        """
    <style>
      .bodyos-body-score-summary .bodyos-body-score-card,
      .bodyos-body-score-summary .bodyos-body-score-title,
      .bodyos-body-score-summary .bodyos-body-score-value,
      .bodyos-body-score-summary .bodyos-body-score-subtitle {
        opacity: 1 !important;
        filter: none !important;
        mix-blend-mode: normal !important;
        background-image: none !important;
        background-clip: border-box !important;
        -webkit-background-clip: border-box !important;
      }
      .bodyos-body-score-summary .bodyos-body-score-card,
      .bodyos-body-score-summary .bodyos-body-score-title,
      .bodyos-body-score-summary .bodyos-body-score-value {
        color: #31313f !important;
        -webkit-text-fill-color: #31313f !important;
      }
      .bodyos-body-score-summary .bodyos-body-score-subtitle {
        color: rgba(49, 51, 63, 0.68) !important;
        -webkit-text-fill-color: rgba(49, 51, 63, 0.68) !important;
        opacity: 1 !important;
        filter: none !important;
        mix-blend-mode: normal !important;
        background-image: none !important;
        background-clip: border-box !important;
        -webkit-background-clip: border-box !important;
      }
    </style>
    """
    ).strip()


def render_improvement_priorities(rows: list[dict[str, Any]]) -> str:
    priorities = sorted(
        [row for row in rows if row["seven_day_average"] is not None],
        key=lambda row: row["seven_day_average"],
    )[:3]
    if not priorities:
        return '<p class="bodyos-component-meta">—</p>'

    cards: list[str] = []
    for index, row in enumerate(priorities, start=1):
        trend = html.escape(row["trend"])
        cards.append(
            textwrap.dedent(
                f"""
            <div class="bodyos-component-card">
              <div class="bodyos-component-label">{index}. {html.escape(row['label'])}</div>
              <div class="bodyos-component-rate">{format_percentage(row['seven_day_average'])}</div>
              <div class="bodyos-component-trend {trend_class(row['trend'])}">{trend}</div>
            </div>
            """
            ).strip()
        )
    return f'<div class="bodyos-component-grid bodyos-priority-grid">{"".join(cards)}</div>'


def render_score_component_cards(rows: list[dict[str, Any]]) -> str:
    cards: list[str] = []
    for row in rows:
        current_rate = row["current_rate"]
        progress_width = 0 if current_rate is None else max(0, min(100, current_rate))
        progress = (
            '<div class="bodyos-component-meta">達成率データなし</div>'
            if current_rate is None
            else textwrap.dedent(
                f"""
              <div class="bodyos-progress-track" aria-hidden="true">
                <div class="bodyos-progress-fill" style="width: {progress_width:.0f}%"></div>
              </div>
            """
            ).strip()
        )
        trend = html.escape(row["trend"])
        cards.append(
            textwrap.dedent(
                f"""
            <div class="bodyos-component-card">
              <div class="bodyos-component-label">{html.escape(row['label'])}</div>
              <div class="bodyos-component-score">{format_component_score(row['actual'], row['maximum'])}</div>
              <div class="bodyos-component-meta">達成率</div>
              <div class="bodyos-component-rate">{format_percentage(current_rate)}</div>
              <div class="bodyos-component-trend {trend_class(row['trend'])}">{trend}</div>
              <div class="bodyos-component-meta">7日平均 {format_percentage(row['seven_day_average'])}</div>
              {progress}
            </div>
            """
            ).strip()
        )
    return f'<div class="bodyos-component-grid bodyos-card-grid">{"".join(cards)}</div>'


def render_score_component_overview(chart_df: pd.DataFrame) -> None:
    st.subheader("スコアコンポーネント")
    rows = score_component_rows(chart_df)
    markup = textwrap.dedent(
        f"""
        {score_component_styles()}
        <div class="bodyos-component-section">
          <h4>改善優先項目</h4>
          {render_improvement_priorities(rows)}
          <h4>最新コンポーネント</h4>
          {render_score_component_cards(rows)}
        </div>
        """
    ).strip()
    if hasattr(st, "html"):
        st.html(markup)
    else:
        components.html(markup, height=1300, scrolling=False)


def format_metric_number(value: Any, suffix: str = "") -> str:
    parsed = parse_number(value, default=None)
    if parsed is None:
        return "—"
    if float(parsed).is_integer():
        return f"{int(parsed):,}{suffix}"
    return f"{parsed:,.1f}{suffix}"


WORKOUT_NO_TEXTS = {"", "なし", "無し", "無", "false", "no", "n", "0", "休み", "してない", "未実施"}
WORKOUT_EXPLICIT_NO_TEXTS = WORKOUT_NO_TEXTS - {""}
WORKOUT_YES_TEXTS = {"あり", "有", "true", "yes", "y", "1", "done", "実施", "した"}


def normalized_workout_text(value: Any) -> str:
    try:
        if value is None or pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip().lower()


def recommendation_priority(target: dict[str, Any]) -> tuple[str, int]:
    reason = str(target.get("reason", ""))
    if target.get("target_weight_kg") is not None and any(keyword in reason for keyword in ["重量", "増量"]):
        return "★★★★★", 5
    if target.get("target_reps"):
        return "★★★★☆", 4
    return "★★★☆☆", 3


def pr_candidate_detail(pr: dict[str, Any]) -> str:
    previous = f" / previous {pr['previous_best']:g}{pr['unit']}" if pr.get("previous_best") else ""
    return f"{pr.get('label', 'PR候補')}: {pr.get('value', 0):g}{pr.get('unit', '')}{previous}"


def workout_display_candidates(
    prs: list[dict[str, Any]],
    next_targets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_exercise: dict[str, dict[str, Any]] = {}

    def upsert(exercise: str, stars: str, priority: int, details: list[str]) -> None:
        key = exercise.strip() or "Workout"
        current = by_exercise.setdefault(key, {"exercise": key, "stars": stars, "priority": priority, "details": []})
        if priority > current["priority"]:
            current["priority"] = priority
            current["stars"] = stars
        for detail in details:
            if detail and detail not in current["details"]:
                current["details"].append(detail)

    for pr in prs:
        upsert(str(pr.get("exercise", "Workout")), "★★★★★", 6, [pr_candidate_detail(pr)])

    for target in next_targets:
        stars, priority = recommendation_priority(target)
        upsert(
            str(target.get("exercise", "Workout")),
            stars,
            priority,
            [str(target.get("target", "")), str(target.get("reason", ""))],
        )

    return sorted(by_exercise.values(), key=lambda candidate: candidate["priority"], reverse=True)[:3]


def workout_recommendation_cards(prs: list[dict[str, Any]], next_targets: list[dict[str, Any]]) -> str:
    candidates = workout_display_candidates(prs, next_targets)
    if not candidates:
        return '<p class="bodyos-component-meta">表示できる候補はありません。</p>'

    cards: list[str] = []
    for candidate in candidates:
        details = candidate["details"][:2]
        primary = details[0] if details else ""
        secondary = details[1] if len(details) > 1 else ""
        secondary_markup = (
            f'<div class="bodyos-component-meta">{html.escape(secondary)}</div>' if secondary else ""
        )
        cards.append(
            textwrap.dedent(
                f"""
            <div class="bodyos-component-card">
              <div class="bodyos-component-label">{html.escape(str(candidate['exercise']))}</div>
              <div class="bodyos-component-rate" style="font-size: 1.35rem;">{candidate['stars']}</div>
              <div class="bodyos-component-score">{html.escape(primary)}</div>
              {secondary_markup}
            </div>
            """
            ).strip()
        )
    return f'<div class="bodyos-component-grid bodyos-priority-grid">{"".join(cards)}</div>'


def workout_marked_performed(latest: pd.Series) -> bool:
    status = normalized_workout_text(latest.get("筋トレ有無", ""))
    detail = normalized_workout_text(latest.get("筋トレ内容", ""))
    if status in WORKOUT_EXPLICIT_NO_TEXTS:
        return False
    if detail not in WORKOUT_NO_TEXTS:
        return True
    return status in WORKOUT_YES_TEXTS


def dashboard_metric_cards(cards: list[dict[str, str]]) -> str:
    card_markup: list[str] = []
    for card in cards:
        caption = card.get("caption", "")
        caption_markup = f'<div class="bodyos-component-meta">{html.escape(caption)}</div>' if caption else ""
        card_markup.append(
            textwrap.dedent(
                f"""
            <div class="bodyos-component-card">
              <div class="bodyos-component-label">{html.escape(card["label"])}</div>
              <div class="bodyos-component-rate">{html.escape(card["value"])}</div>
              {caption_markup}
            </div>
            """
            ).strip()
        )
    return f'<div class="bodyos-component-grid bodyos-card-grid">{"".join(card_markup)}</div>'


def body_score_metric_cards(cards: list[dict[str, str]]) -> str:
    card_markup: list[str] = []
    for card in cards:
        caption = card.get("caption", "")
        caption_markup = (
            f'<div class="bodyos-component-meta bodyos-body-score-subtitle">{html.escape(caption)}</div>'
            if caption
            else ""
        )
        card_markup.append(
            textwrap.dedent(
                f"""
            <div class="bodyos-component-card bodyos-body-score-card">
              <div class="bodyos-component-label bodyos-body-score-title">{html.escape(card["label"])}</div>
              <div class="bodyos-component-rate bodyos-body-score-value">{html.escape(card["value"])}</div>
              {caption_markup}
            </div>
            """
            ).strip()
        )
    return f'<div class="bodyos-component-grid bodyos-card-grid">{"".join(card_markup)}</div>'


def render_html_section(markup: str, fallback_height: int = 700) -> None:
    if hasattr(st, "html"):
        st.html(markup)
    else:
        components.html(markup, height=fallback_height, scrolling=False)


def render_workout_intelligence(latest: pd.Series, data: pd.DataFrame) -> None:
    st.subheader("Workout Intelligence")
    if not workout_marked_performed(latest):
        st.write("筋トレ記録がありません。")
        return

    workout_history = data.iloc[:-1].to_dict("records") if len(data) > 1 else []
    workout_insight = analyze_workout(latest.to_dict(), history=workout_history)
    st.write(workout_insight["summary"])
    markup = textwrap.dedent(
        f"""
        {score_component_styles()}
        <div class="bodyos-component-section">
          {workout_recommendation_cards(workout_insight["prs"], workout_insight["next_targets"])}
        </div>
        """
    ).strip()
    render_html_section(markup, fallback_height=420)


def render_body_score_summary(latest: pd.Series, chart_df: pd.DataFrame) -> None:
    st.subheader("Body Score")
    markup = textwrap.dedent(
        f"""
        {score_component_styles()}
        {body_score_card_styles()}
        <div class="bodyos-component-section bodyos-body-score-summary">
          {body_score_metric_cards([
              {"label": "最新Body Score", "value": f"{int(latest['Body Score'])}点", "caption": score_label(latest["Body Score"])},
              {"label": "7日平均Body Score", "value": f"{chart_df['7日平均Body Score'].iloc[-1]:.1f}点"},
              {"label": "最新モード", "value": str(latest["モード"])},
          ])}
        </div>
        """
    ).strip()
    render_html_section(markup, fallback_height=420)


def render_todays_metrics(latest: pd.Series, chart_df: pd.DataFrame, this_week: pd.DataFrame) -> None:
    st.subheader("今日のメトリクス")
    this_week_average_weight = valid_weight_series(this_week["体重"]).mean() if not this_week.empty else pd.NA
    markup = textwrap.dedent(
        f"""
        {score_component_styles()}
        <div class="bodyos-component-section">
          {dashboard_metric_cards([
              {"label": "体重", "value": format_weight_kg(latest["体重"])},
              {"label": "睡眠", "value": format_metric_number(latest.get("睡眠時間"), "h")},
              {"label": "歩数", "value": format_metric_number(latest.get("歩数"), "歩")},
              {"label": "カロリー", "value": format_metric_number(latest.get("推定摂取カロリー"), "kcal")},
              {
                  "label": "タンパク質",
                  "value": format_component_score(
                      latest.get("タンパク質スコア"),
                      SCORE_COMPONENT_MAXIMA["タンパク質スコア"],
                  ),
              },
              {"label": "今週の平均体重", "value": format_optional_number(this_week_average_weight, "kg")},
              {"label": "7日平均体重", "value": format_optional_number(chart_df["7日平均体重"].iloc[-1], "kg")},
          ])}
        </div>
        """
    ).strip()
    render_html_section(markup, fallback_height=700)


def render_nutrition_intelligence(
    latest: pd.Series,
    data: pd.DataFrame,
    food_knowledge: dict[str, Any] | None = None,
) -> None:
    """Render a compact, mobile-safe projection of the pure nutrition result."""
    st.subheader("Nutrition Intelligence")
    history = data.iloc[:-1].to_dict("records") if len(data) > 1 else []
    profile = {"body_weight": latest.get("体重")}
    insight = analyze_nutrition(
        latest.to_dict(),
        history=history,
        profile=profile,
        food_knowledge=food_knowledge,
    )
    cards = [
        ("Nutrition Score", f"{insight['score']}点", f"利用可能 {insight['available_points']}点分で正規化"),
        ("信頼度", insight["confidence"]["level"], f"{insight['confidence']['score']:.0%}"),
        ("記録状況", insight["status"], f"目標進捗 {insight['expected_progress_ratio']:.0%}"),
    ]
    card_markup = "".join(
        f'<div class="bodyos-ni-card"><div class="bodyos-ni-label">{html.escape(label)}</div>'
        f'<div class="bodyos-ni-value">{html.escape(value)}</div>'
        f'<div class="bodyos-ni-meta">{html.escape(caption)}</div></div>'
        for label, value, caption in cards
    )
    markup = textwrap.dedent(
        f"""
        <style>
          .bodyos-nutrition-intelligence,
          .bodyos-nutrition-intelligence * {{ box-sizing: border-box; min-width: 0; }}
          .bodyos-nutrition-intelligence .bodyos-ni-grid {{
            display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 0.9rem; width: 100%;
          }}
          .bodyos-nutrition-intelligence .bodyos-ni-card {{
            border: 1px solid rgba(49, 51, 63, 0.18); border-radius: 8px; padding: 0.85rem 0.95rem;
            background: #fff; color: #31313f; opacity: 1; filter: none; backdrop-filter: none;
            mix-blend-mode: normal; overflow-wrap: anywhere;
          }}
          .bodyos-nutrition-intelligence .bodyos-ni-label {{ color: #31313f; font-weight: 700; line-height: 1.35; margin-bottom: 0.55rem; }}
          .bodyos-nutrition-intelligence .bodyos-ni-value {{ color: #31313f; font-size: 2rem; font-weight: 750; line-height: 1.05; margin-bottom: 0.35rem; }}
          .bodyos-nutrition-intelligence .bodyos-ni-meta {{ color: rgba(49, 51, 63, 0.68); font-size: 0.9rem; line-height: 1.45; }}
          @media (max-width: 900px) {{ .bodyos-nutrition-intelligence .bodyos-ni-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }} }}
          @media (max-width: 520px) {{
            .bodyos-nutrition-intelligence .bodyos-ni-grid {{ grid-template-columns: minmax(0, 1fr); }}
            .bodyos-nutrition-intelligence .bodyos-ni-card {{ padding: 0.8rem 0.85rem; }}
            .bodyos-nutrition-intelligence .bodyos-ni-value {{ font-size: 1.85rem; }}
          }}
        </style>
        <div class="bodyos-nutrition-intelligence"><div class="bodyos-ni-grid">{card_markup}</div></div>
        """
    ).strip()
    render_html_section(markup, fallback_height=420)
    st.write(insight["summary"])
    if insight["strengths"]:
        st.markdown("**良い点**")
        for strength in insight["strengths"][:2]:
            st.write(f"- {strength['title']}: {strength['detail']}")
    if insight["priorities"]:
        st.markdown("**改善優先項目**")
        for priority in insight["priorities"][:3]:
            st.write(f"- [{priority['severity']}] {priority['title']}: {priority['detail']}")
    if insight["actions"]:
        st.markdown("**次のアクション**")
        for action in insight["actions"]:
            st.write(f"{action['priority']}. {action['title']} - {action['detail']}")
    with st.expander("栄養評価の詳細"):
        breakdown = pd.DataFrame(
            [
                {
                    "項目": name,
                    "状態": item["status"],
                    "実績": item["actual"] if item["actual"] is not None else "—",
                    "目標": str(item["target"]),
                    "点": f"{item['points']} / {item['max_points']}" if item["available"] else "—",
                }
                for name, item in insight["score_breakdown"].items()
            ]
        )
        st.dataframe(breakdown, use_container_width=True, hide_index=True)
        st.caption("データ品質: " + (" / ".join(insight["confidence"]["reasons"]) or "十分な記録範囲"))
        st.json(insight["comparisons"])


def render_core_trend_charts(chart_df: pd.DataFrame) -> None:
    st.subheader("コア推移")

    st.markdown("**Body Score**")
    st.altair_chart(apply_dashboard_axis_config(body_score_chart(chart_df)), use_container_width=True)

    st.markdown("**体重**")
    weight_domain = weight_axis_domain(chart_df, ["有効体重", "7日平均体重"])
    weight_chart = daily_weight_line_chart(chart_df, "有効体重", "体重(kg)", weight_domain, "#1f77b4") + daily_weight_line_chart(
        chart_df, "7日平均体重", "7日平均体重(kg)", weight_domain, "#888888"
    ).mark_line(strokeDash=[5, 4], color="#888888")
    st.altair_chart(apply_dashboard_axis_config(weight_chart.properties(height=300)), use_container_width=True)

    st.markdown("**摂取カロリー**")
    st.altair_chart(
        apply_dashboard_axis_config(daily_bar_chart(chart_df, "推定摂取カロリー", "推定摂取カロリー(kcal)", "#59a14f")),
        use_container_width=True,
    )

    st.markdown("**歩数**")
    st.altair_chart(apply_dashboard_axis_config(daily_bar_chart(chart_df, "歩数", "歩数", "#4c78a8")), use_container_width=True)


def render_recent_details(latest: pd.Series) -> None:
    st.subheader("直近の食事・筋トレ内容")
    st.write(f"朝: {latest.get('朝', '')} / {int(latest.get('朝カロリー(kcal)', 0)):,}kcal")
    st.write(f"昼: {latest.get('昼', '')} / {int(latest.get('昼カロリー(kcal)', 0)):,}kcal")
    st.write(f"夜: {latest.get('夜', '')} / {int(latest.get('夜カロリー(kcal)', 0)):,}kcal")
    st.write(f"間食: {latest.get('間食', '')} / {int(latest.get('間食カロリー(kcal)', 0)):,}kcal")
    st.write(
        f"仕事中のドリンク: {latest.get('仕事中のドリンク', '')} / "
        f"{int(latest.get('ドリンクカロリー(kcal)', 0)):,}kcal"
    )
    st.write(f"カロリー推定信頼度: {latest.get('カロリー推定信頼度', '')}")
    st.write(f"筋トレ: {latest.get('筋トレ有無', '')} / {latest.get('筋トレ内容', '')}")
    st.write(
        f"モード: {latest.get('モード', '')} / イベント名: {latest.get('イベント名', '')} / "
        f"Body Score: {int(latest.get('Body Score', 0))}"
    )
    st.write(
        f"体調: {latest.get('体調', '')} / 飲酒: {latest.get('飲酒', '')} "
        f"/ 飲酒内容: {latest.get('飲酒内容', '')} / 採点: {latest.get('今日の採点', 0)}"
    )
    st.write(f"コメント: {latest.get('コメント', '')}")


def render_history_table(chart_df: pd.DataFrame) -> None:
    st.subheader("記録一覧")
    history_df = chart_df.copy()
    history_df["体重"] = history_df["体重表示"]
    history_columns = [
        "日付表示",
        "Body Score",
        "Score Label",
        "モード",
        "イベント名",
        "体重",
        "歩数",
        "歩数ランク",
        "睡眠時間",
        "筋トレ有無",
        "飲酒",
        "飲酒内容",
        "コメント",
    ]
    st.dataframe(history_df[history_columns], use_container_width=True, hide_index=True)


def render_dashboard(
    data: pd.DataFrame,
    target_weight: float,
    predict_target_date: Callable[[pd.DataFrame, float], str],
    training_counted: Callable[[dict[str, Any] | pd.Series], bool],
    *,
    food_knowledge: dict[str, Any] | None = None,
) -> None:
    data = data.sort_values("日付")
    latest = data.iloc[-1]
    chart_df = add_daily_display_columns(data)
    chart_df["有効体重"] = valid_weight_series(chart_df["体重"])
    chart_df["体重表示"] = chart_df["体重"].apply(format_weight_kg)
    chart_df["7日平均体重"] = chart_df["有効体重"].rolling(window=7, min_periods=1).mean()
    chart_df["7日平均Body Score"] = chart_df["Body Score"].rolling(window=7, min_periods=1).mean()

    today = pd.Timestamp(dt.date.today())
    week_start = today - pd.Timedelta(days=today.weekday())
    this_week = chart_df[pd.to_datetime(chart_df["日付"], errors="coerce") >= week_start]
    st.header("ダッシュボード")
    render_body_score_summary(latest, chart_df)
    render_todays_metrics(latest, chart_df, this_week)
    render_nutrition_intelligence(latest, data, food_knowledge)
    render_workout_intelligence(latest, data)
    render_core_trend_charts(chart_df)
    render_history_table(chart_df)

    st.subheader("詳細分析")
    st.markdown("**76kg到達予測**")
    st.info(predict_target_date(data, target_weight))
    render_score_component_overview(chart_df)
    render_recent_details(latest)

    csv = data.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
    st.download_button("CSVダウンロード", csv, "body_recomp_records.csv", "text/csv")
