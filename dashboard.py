from __future__ import annotations

import datetime as dt
import re
from typing import Any, Callable

import altair as alt
import pandas as pd
import streamlit as st

from bodyos_standard import MODES, SCORE_COMPONENTS, condition_score
from workout_intelligence import analyze_workout

STEP_RANK_ORDER = ["S", "A", "B", "C", "D"]
SCORE_LABELS = [
    (90, "🟢 Excellent", "#2ca02c"),
    (80, "🔵 Good", "#1f77b4"),
    (70, "🟡 Fair", "#f2c94c"),
    (60, "🟠 Needs Attention", "#f2994a"),
    (0, "🔴 Recovery Needed", "#d62728"),
]


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


def alcohol_present(value: Any) -> bool:
    text = str(value).strip().lower()
    if not text:
        return False
    return text not in {"なし", "無", "no", "n", "false", "0"}


def count_bench_90kg_sets(training_detail: Any) -> int:
    text = str(training_detail or "")
    if not text:
        return 0

    total = 0
    for match in re.finditer(r"90\s*kg\s*([0-9,\s]+)", text, flags=re.IGNORECASE):
        reps_text = match.group(1).strip(" ,")
        reps = [rep for rep in re.split(r"[,\s]+", reps_text) if rep.isdigit()]
        total += len(reps)

    if total > 0:
        return total
    return len(re.findall(r"90\s*kg", text, flags=re.IGNORECASE))


def weekly_label(series: pd.Series) -> pd.Series:
    return series.dt.to_period("W-SUN").apply(lambda period: f"{period.start_time:%Y/%m/%d}週")


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
        axis=alt.Axis(title="日付", labelAngle=-45),
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


def render_workout_intelligence(latest: pd.Series, data: pd.DataFrame) -> None:
    st.subheader("Workout Intelligence")
    workout_history = data.iloc[:-1].to_dict("records") if len(data) > 1 else []
    workout_insight = analyze_workout(latest.to_dict(), history=workout_history)
    st.write(workout_insight["summary"])
    if workout_insight["prs"]:
        for pr in workout_insight["prs"][:3]:
            previous = f" / previous {pr['previous_best']:g}{pr['unit']}" if pr["previous_best"] else ""
            st.write(f"- {pr['exercise']}: {pr['label']} {pr['value']:g}{pr['unit']}{previous}")
    if workout_insight["next_targets"]:
        st.caption("次回ターゲット")
        for target in workout_insight["next_targets"][:3]:
            st.write(f"- {target['exercise']}: {target['target']}")


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
    st.dataframe(chart_df[history_columns], use_container_width=True, hide_index=True)


def render_dashboard(
    data: pd.DataFrame,
    target_weight: float,
    predict_target_date: Callable[[pd.DataFrame, float], str],
    training_counted: Callable[[dict[str, Any] | pd.Series], bool],
) -> None:
    data = data.sort_values("日付")
    latest = data.iloc[-1]
    chart_df = add_daily_display_columns(data)
    chart_df["7日平均体重"] = chart_df["体重"].rolling(window=7, min_periods=1).mean()
    chart_df["7日平均Body Score"] = chart_df["Body Score"].rolling(window=7, min_periods=1).mean()
    chart_df["ベンチプレス90kgセット数"] = chart_df["筋トレ内容"].apply(count_bench_90kg_sets)
    chart_df["飲酒あり"] = chart_df["飲酒"].apply(alcohol_present)
    chart_df["体調5段階"] = chart_df["体調"].apply(condition_score)
    chart_df["週"] = weekly_label(pd.to_datetime(chart_df["日付"], errors="coerce"))

    today = pd.Timestamp(dt.date.today())
    week_start = today - pd.Timedelta(days=today.weekday())
    this_week = chart_df[pd.to_datetime(chart_df["日付"], errors="coerce") >= week_start]
    condition_average = chart_df["体調5段階"].dropna().mean()

    st.header("ダッシュボード")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("最新Body Score", f"{int(latest['Body Score'])}点")
        st.caption(score_label(latest["Body Score"]))
    c2.metric("7日平均Body Score", f"{chart_df['7日平均Body Score'].iloc[-1]:.1f}点")
    c3.metric("最新モード", str(latest["モード"]))
    c4.metric("最新体重", f"{latest['体重']:.1f}kg")

    mode_counts = data["モード"].value_counts().reindex(MODES, fill_value=0)
    m1, m2, m3, m4 = st.columns(4)
    for metric, mode_name in zip([m1, m2, m3, m4], MODES):
        metric.metric(f"{mode_name}の日数", f"{int(mode_counts[mode_name])}日")

    st.subheader("Body Score推移")
    st.altair_chart(body_score_chart(chart_df), use_container_width=True)

    st.subheader("各スコア内訳の推移")
    score_component_chart = (
        alt.Chart(
            chart_df.melt(
                id_vars=["Daily Label", "日付表示"],
                value_vars=SCORE_COMPONENTS,
                var_name="スコア",
                value_name="点数",
            )
        )
        .mark_line(point=True)
        .encode(
            x=ordered_daily_x(chart_df),
            y=alt.Y("点数:Q", title="点数"),
            color=alt.Color("スコア:N", legend=alt.Legend(title="内訳")),
            tooltip=["日付表示", "スコア", "点数"],
        )
        .properties(height=280)
    )
    st.altair_chart(score_component_chart, use_container_width=True)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("今週の平均体重", f"{this_week['体重'].mean():.1f}kg" if not this_week.empty else "-")
    c2.metric("7日平均体重", f"{chart_df['7日平均体重'].iloc[-1]:.1f}kg")
    c3.metric("平均歩数", f"{data['歩数'].mean():,.0f}歩")
    c4.metric("平均摂取カロリー", f"{data['推定摂取カロリー'].mean():,.0f}kcal")

    c5, c6, c7, c8 = st.columns(4)
    c5.metric("平均Body Score", f"{data['Body Score'].mean():.1f}点")
    c6.metric("筋トレ回数", f"{int(data.apply(training_counted, axis=1).sum())}回")
    c7.metric("飲酒ありの日数", f"{int(chart_df['飲酒あり'].sum())}日")
    c8.metric("体調平均", f"{condition_average:.1f}/10" if pd.notna(condition_average) else "-")

    st.subheader("76kg到達予測")
    st.info(predict_target_date(data, target_weight))

    st.subheader("体重推移")
    weight_chart = daily_line_chart(chart_df, "体重", "体重(kg)", "#1f77b4") + daily_line_chart(
        chart_df, "7日平均体重", "7日平均体重(kg)", "#888888"
    ).mark_line(strokeDash=[5, 4], color="#888888")
    st.altair_chart(weight_chart.properties(height=300), use_container_width=True)

    st.subheader("摂取カロリー推移")
    st.altair_chart(daily_bar_chart(chart_df, "推定摂取カロリー", "推定摂取カロリー(kcal)", "#59a14f"), use_container_width=True)

    st.subheader("歩数推移")
    st.altair_chart(daily_bar_chart(chart_df, "歩数", "歩数", "#4c78a8"), use_container_width=True)

    st.subheader("歩数ランク別の日数")
    step_rank_counts = data["歩数ランク"].value_counts().reindex(STEP_RANK_ORDER, fill_value=0)
    st.bar_chart(step_rank_counts)

    st.subheader("週ごとの筋トレ回数")
    weekly_training = (
        chart_df.assign(筋トレ回数=chart_df.apply(training_counted, axis=1).astype(int))
        .groupby("週")["筋トレ回数"]
        .sum()
    )
    st.bar_chart(weekly_training)

    st.subheader("ベンチプレス90kgセット数の推移")
    st.altair_chart(daily_line_chart(chart_df, "ベンチプレス90kgセット数", "90kgセット数", "#9467bd"), use_container_width=True)

    render_workout_intelligence(latest, data)
    render_recent_details(latest)
    render_history_table(chart_df)

    csv = data.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
    st.download_button("CSVダウンロード", csv, "body_recomp_records.csv", "text/csv")
