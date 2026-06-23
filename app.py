import datetime as dt
from pathlib import Path

import pandas as pd
import streamlit as st

DATA_FILE = "records.csv"
COLUMNS = ["日付", "体重(kg)", "歩数", "摂取カロリー(kcal)", "筋トレ", "ベンチプレス(kg)"]
TARGET_WEIGHT = 82.0

st.set_page_config(page_title="筋トレ・減量管理アプリ", page_icon="💪", layout="wide")
st.title("💪 筋トレ・減量管理アプリ")
st.caption("体重・歩数・筋トレをCSVに保存し、過去データをもとに減量ペースを分析します。")


def load_data() -> pd.DataFrame:
    if Path(DATA_FILE).exists():
        loaded = pd.read_csv(DATA_FILE)
    else:
        loaded = pd.DataFrame(columns=COLUMNS)

    for column in COLUMNS:
        if column not in loaded.columns:
            loaded[column] = None

    loaded = loaded[COLUMNS]
    if not loaded.empty:
        loaded["日付"] = pd.to_datetime(loaded["日付"], errors="coerce")
        loaded = loaded.dropna(subset=["日付"])
        loaded["体重(kg)"] = pd.to_numeric(loaded["体重(kg)"], errors="coerce")
        loaded["歩数"] = pd.to_numeric(loaded["歩数"], errors="coerce").fillna(0).astype(int)
        loaded["摂取カロリー(kcal)"] = pd.to_numeric(loaded["摂取カロリー(kcal)"], errors="coerce").fillna(0).astype(int)
        loaded["ベンチプレス(kg)"] = pd.to_numeric(loaded["ベンチプレス(kg)"], errors="coerce").fillna(0)
        loaded = loaded.sort_values("日付")
    return loaded


def save_data(data: pd.DataFrame) -> None:
    data.to_csv(DATA_FILE, index=False, encoding="utf-8-sig")


def predict_target_date(data: pd.DataFrame, target_weight: float) -> str:
    if len(data) < 2:
        return "予測には2件以上の記録が必要です。"

    recent = data.tail(min(len(data), 14)).copy()
    first_weight = float(recent["体重(kg)"].iloc[0])
    latest_weight = float(recent["体重(kg)"].iloc[-1])
    days_elapsed = max((recent["日付"].iloc[-1] - recent["日付"].iloc[0]).days, 1)
    daily_pace = (first_weight - latest_weight) / days_elapsed

    if latest_weight <= target_weight:
        return f"すでに目標の{target_weight:.1f}kgを達成しています。"
    if daily_pace <= 0:
        return "直近データでは体重が減っていないため、到達日はまだ予測できません。"

    days_needed = int((latest_weight - target_weight) / daily_pace)
    target_date = dt.date.today() + dt.timedelta(days=days_needed)
    return f"現在ペースなら、約{days_needed}日後（{target_date.strftime('%Y/%m/%d')}）に{target_weight:.1f}kg到達見込みです。"


df = load_data()

st.header("今日の記録")
with st.form("daily_record_form"):
    col1, col2, col3 = st.columns(3)
    with col1:
        record_date = st.date_input("日付", value=dt.date.today())
        weight = st.number_input("朝の体重(kg)", min_value=40.0, max_value=150.0, value=85.0, step=0.1)
    with col2:
        steps = st.number_input("歩数", min_value=0, max_value=50000, value=7000, step=500)
        calories = st.number_input("摂取カロリー(kcal)", min_value=0, max_value=6000, value=2300, step=50)
    with col3:
        trained = st.checkbox("筋トレした")
        bench = st.number_input("ベンチプレス最高重量(kg)", min_value=0.0, max_value=250.0, value=90.0, step=2.5)
    submitted = st.form_submit_button("CSVに保存する")

if submitted:
    new_row = pd.DataFrame([{
        "日付": pd.to_datetime(record_date),
        "体重(kg)": weight,
        "歩数": steps,
        "摂取カロリー(kcal)": calories,
        "筋トレ": "あり" if trained else "なし",
        "ベンチプレス(kg)": bench if trained else 0,
    }])
    df = pd.concat([df, new_row], ignore_index=True)
    df = df.sort_values("日付")
    save_data(df)
    st.success("CSVへ保存しました！リロードしても過去データが残ります。")

if df.empty:
    st.info("まだ記録がありません。まずは今日の記録を保存してみましょう。")
else:
    df = df.sort_values("日付")
    latest = df.iloc[-1]
    df_for_chart = df.set_index("日付")
    df_for_chart["7日平均体重(kg)"] = df_for_chart["体重(kg)"].rolling(window=7, min_periods=1).mean()

    st.header("ダッシュボード")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("最新体重", f"{latest['体重(kg)']:.1f}kg")
    c2.metric("7日平均体重", f"{df_for_chart['7日平均体重(kg)'].iloc[-1]:.1f}kg")
    c3.metric("平均歩数", f"{df['歩数'].mean():,.0f}歩")
    c4.metric("筋トレ回数", f"{int((df['筋トレ'] == 'あり').sum())}回")

    st.subheader("82kg到達予測")
    st.info(predict_target_date(df, TARGET_WEIGHT))

    st.subheader("体重推移")
    st.line_chart(df_for_chart[["体重(kg)", "7日平均体重(kg)"]])

    st.subheader("歩数推移")
    st.bar_chart(df_for_chart[["歩数"]])

    st.subheader("記録一覧")
    st.dataframe(df, use_container_width=True)

    csv = df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
    st.download_button("CSVダウンロード", csv, "body_recomp_records.csv", "text/csv")

st.caption("次の改良候補：月次レポート、PFC分析、ベンチ100kg到達予測、分析資料用グラフ出力")
