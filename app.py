import datetime as dt
import re
from pathlib import Path

import pandas as pd
import streamlit as st

DATA_FILE = "records.csv"
TARGET_WEIGHT = 82.0

COLUMNS = [
    "日付",
    "体重(kg)",
    "歩数",
    "朝",
    "昼",
    "夜",
    "間食",
    "仕事中のドリンク",
    "推定摂取カロリー(kcal)",
    "筋トレ",
    "筋トレ内容",
    "ベンチプレス(kg)",
]

CALORIE_KEYWORDS = {
    "赤飯おにぎり": 220,
    "おにぎり": 180,
    "ご飯": 250,
    "白米": 250,
    "特盛": 450,
    "牛丼": 750,
    "定食": 900,
    "ハンバーグ": 500,
    "豚汁": 180,
    "うどん": 450,
    "そば": 420,
    "パスタ": 700,
    "ラーメン": 800,
    "カレー": 850,
    "とり天": 180,
    "唐揚げ": 300,
    "チキン": 180,
    "グリルチキン": 170,
    "ゆでたまご": 80,
    "卵": 80,
    "プロテイン": 120,
    "オイコス": 100,
    "ヨーグルト": 100,
    "サラダ": 80,
    "菓子": 200,
    "チョコ": 250,
    "アイス": 250,
    "ジュース": 120,
    "トマトジュース": 70,
    "コーヒー": 20,
    "カフェラテ": 140,
    "ビール": 200,
}

st.set_page_config(page_title="筋トレ・減量管理アプリ", page_icon="💪", layout="wide")
st.title("💪 筋トレ・減量管理アプリ")
st.caption("食事・体重・歩数・筋トレをCSVに保存し、減量ペースを分析します。")


def estimate_calories(text: str) -> int:
    """ざっくりカロリー推定。123kcalのように明記した場合はその数値も加算します。"""
    if not text:
        return 0

    total = 0
    lowered = text.lower()

    explicit_numbers = re.findall(r"(\d+)\s*kcal", lowered)
    total += sum(int(number) for number in explicit_numbers)

    for keyword, kcal in CALORIE_KEYWORDS.items():
        count = text.count(keyword)
        if count > 0:
            total += count * kcal

    return total


def load_data() -> pd.DataFrame:
    if Path(DATA_FILE).exists():
        loaded = pd.read_csv(DATA_FILE)
    else:
        loaded = pd.DataFrame(columns=COLUMNS)

    if "摂取カロリー(kcal)" in loaded.columns and "推定摂取カロリー(kcal)" not in loaded.columns:
        loaded["推定摂取カロリー(kcal)"] = loaded["摂取カロリー(kcal)"]

    for column in COLUMNS:
        if column not in loaded.columns:
            if column in ["朝", "昼", "夜", "間食", "仕事中のドリンク", "筋トレ内容"]:
                loaded[column] = ""
            else:
                loaded[column] = None

    loaded = loaded[COLUMNS]
    if not loaded.empty:
        loaded["日付"] = pd.to_datetime(loaded["日付"], errors="coerce")
        loaded = loaded.dropna(subset=["日付"])
        loaded["体重(kg)"] = pd.to_numeric(loaded["体重(kg)"], errors="coerce")
        loaded["歩数"] = pd.to_numeric(loaded["歩数"], errors="coerce").fillna(0).astype(int)
        loaded["推定摂取カロリー(kcal)"] = pd.to_numeric(loaded["推定摂取カロリー(kcal)"], errors="coerce").fillna(0).astype(int)
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
    basic_col1, basic_col2 = st.columns(2)
    with basic_col1:
        record_date = st.date_input("日付", value=dt.date.today())
        weight = st.number_input("朝の体重(kg)", min_value=40.0, max_value=150.0, value=85.0, step=0.1)
    with basic_col2:
        steps = st.number_input("歩数", min_value=0, max_value=50000, value=7000, step=500)
        bench = st.number_input("ベンチプレス最高重量(kg)", min_value=0.0, max_value=250.0, value=90.0, step=2.5)

    st.subheader("食べたもの")
    meal_col1, meal_col2 = st.columns(2)
    with meal_col1:
        breakfast = st.text_area("朝", placeholder="例：トマトジュース、ゆでたまご", height=80)
        lunch = st.text_area("昼", placeholder="例：肉ぶっかけうどん、とり天1個", height=80)
        snacks = st.text_area("間食", placeholder="例：菓子 123kcal、オイコス", height=80)
    with meal_col2:
        dinner = st.text_area("夜", placeholder="例：赤飯おにぎり、グリルチキン、オイコス", height=80)
        work_drinks = st.text_area("仕事中のドリンク", placeholder="例：コーヒー、カフェラテ、プロテイン", height=80)

    st.subheader("筋トレ")
    trained = st.checkbox("筋トレした")
    training_detail = st.text_area(
        "筋トレ内容",
        placeholder="例：ベンチプレス 90kg 5,6,6,4 / 懸垂 10,10,5 / サイドレイズ 12kg 15回×3",
        height=120,
    )

    submitted = st.form_submit_button("CSVに保存する")

if submitted:
    meal_text = "\n".join([breakfast, lunch, dinner, snacks, work_drinks])
    estimated_calories = estimate_calories(meal_text)

    new_row = pd.DataFrame([{
        "日付": pd.to_datetime(record_date),
        "体重(kg)": weight,
        "歩数": steps,
        "朝": breakfast,
        "昼": lunch,
        "夜": dinner,
        "間食": snacks,
        "仕事中のドリンク": work_drinks,
        "推定摂取カロリー(kcal)": estimated_calories,
        "筋トレ": "あり" if trained else "なし",
        "筋トレ内容": training_detail,
        "ベンチプレス(kg)": bench if trained else 0,
    }])
    df = pd.concat([df, new_row], ignore_index=True)
    df = df.sort_values("日付")
    save_data(df)
    st.success(f"CSVへ保存しました！推定摂取カロリーは約{estimated_calories:,}kcalです。")

if df.empty:
    st.info("まだ記録がありません。まずは今日の記録を保存してみましょう。")
else:
    df = df.sort_values("日付")
    latest = df.iloc[-1]
    df_for_chart = df.set_index("日付")
    df_for_chart["7日平均体重(kg)"] = df_for_chart["体重(kg)"].rolling(window=7, min_periods=1).mean()

    st.header("ダッシュボード")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("最新体重", f"{latest['体重(kg)']:.1f}kg")
    c2.metric("7日平均体重", f"{df_for_chart['7日平均体重(kg)'].iloc[-1]:.1f}kg")
    c3.metric("平均歩数", f"{df['歩数'].mean():,.0f}歩")
    c4.metric("平均推定カロリー", f"{df['推定摂取カロリー(kcal)'].mean():,.0f}kcal")
    c5.metric("筋トレ回数", f"{int((df['筋トレ'] == 'あり').sum())}回")

    st.subheader("82kg到達予測")
    st.info(predict_target_date(df, TARGET_WEIGHT))

    st.subheader("体重推移")
    st.line_chart(df_for_chart[["体重(kg)", "7日平均体重(kg)"]])

    st.subheader("推定摂取カロリー推移")
    st.bar_chart(df_for_chart[["推定摂取カロリー(kcal)"]])

    st.subheader("歩数推移")
    st.bar_chart(df_for_chart[["歩数"]])

    st.subheader("直近の食事・筋トレ内容")
    st.write(f"朝：{latest.get('朝', '')}")
    st.write(f"昼：{latest.get('昼', '')}")
    st.write(f"夜：{latest.get('夜', '')}")
    st.write(f"間食：{latest.get('間食', '')}")
    st.write(f"仕事中のドリンク：{latest.get('仕事中のドリンク', '')}")
    st.write(f"筋トレ：{latest.get('筋トレ内容', '')}")

    st.subheader("記録一覧")
    st.dataframe(df, use_container_width=True)

    csv = df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
    st.download_button("CSVダウンロード", csv, "body_recomp_records.csv", "text/csv")

st.caption("注意：カロリーはキーワードベースの概算です。正確化したい場合は『123kcal』のように数値を入力してください。")
