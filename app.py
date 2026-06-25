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
    "朝カロリー(kcal)",
    "昼",
    "昼カロリー(kcal)",
    "夜",
    "夜カロリー(kcal)",
    "間食",
    "間食カロリー(kcal)",
    "仕事中のドリンク",
    "ドリンクカロリー(kcal)",
    "推定摂取カロリー(kcal)",
    "筋トレ",
    "筋トレ内容",
    "ベンチプレス(kg)",
]

# ざっくり推定用。完全一致ではなく、文章内に含まれたら加算します。
CALORIE_KEYWORDS = {
    "赤飯おにぎり": 230,
    "おにぎり": 190,
    "鮭おにぎり": 190,
    "ツナマヨ": 230,
    "ご飯特盛": 500,
    "ご飯大盛": 380,
    "ご飯": 260,
    "白米": 260,
    "牛丼": 750,
    "牛丼大盛": 950,
    "定食": 900,
    "ハンバーグ定食": 1100,
    "ウマトマ": 900,
    "ハンバーグ": 520,
    "豚汁": 180,
    "釜玉うどん大": 700,
    "釜玉うどん": 560,
    "肉ぶっかけうどん": 650,
    "ぶっかけうどん": 500,
    "うどん大": 650,
    "うどん": 450,
    "とり天": 180,
    "天ぷら盛り合わせ": 600,
    "天ぷら": 250,
    "そば": 420,
    "とろろそば": 480,
    "パスタ": 750,
    "ラーメン": 850,
    "カレー": 850,
    "唐揚げ": 350,
    "チキン": 200,
    "グリルチキン": 180,
    "サラダチキン": 120,
    "ゆでたまご": 80,
    "卵": 80,
    "プロテイン": 130,
    "オイコス": 100,
    "ヨーグルト": 100,
    "サラダ": 100,
    "菓子": 220,
    "チョコ": 250,
    "アイス": 260,
    "ジュース": 130,
    "トマトジュース": 70,
    "コーヒー": 20,
    "カフェラテ": 150,
    "ビール": 200,
}

MEAL_FALLBACK = {
    "朝": 300,
    "昼": 750,
    "夜": 850,
    "間食": 200,
    "仕事中のドリンク": 100,
}

st.set_page_config(page_title="筋トレ・減量管理アプリ", page_icon="💪", layout="wide")
st.title("💪 筋トレ・減量管理アプリ")
st.caption("食事・体重・歩数・筋トレをCSVに保存し、減量ペースを分析します。")


def estimate_calories(text: str, meal_type: str = "") -> int:
    """ざっくりカロリー推定。123kcalのように明記した場合はその数値を優先的に加算します。"""
    if not text or not str(text).strip():
        return 0

    text = str(text)
    lowered = text.lower()
    total = 0

    explicit_numbers = re.findall(r"(\d+)\s*kcal", lowered)
    total += sum(int(number) for number in explicit_numbers)

    for keyword, kcal in CALORIE_KEYWORDS.items():
        count = text.count(keyword)
        if count > 0:
            total += count * kcal

    # 何か食べ物が書かれているのに推定0になる問題を避けるため、最低限の概算を入れる
    if total == 0 and meal_type in MEAL_FALLBACK:
        total = MEAL_FALLBACK[meal_type]

    return total


def final_kcal(auto_kcal: int, manual_kcal: int) -> int:
    return manual_kcal if manual_kcal > 0 else auto_kcal


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
                loaded[column] = 0

    loaded = loaded[COLUMNS]
    if not loaded.empty:
        loaded["日付"] = pd.to_datetime(loaded["日付"], errors="coerce")
        loaded = loaded.dropna(subset=["日付"])
        numeric_columns = [
            "体重(kg)", "歩数", "朝カロリー(kcal)", "昼カロリー(kcal)", "夜カロリー(kcal)",
            "間食カロリー(kcal)", "ドリンクカロリー(kcal)", "推定摂取カロリー(kcal)", "ベンチプレス(kg)"
        ]
        for column in numeric_columns:
            loaded[column] = pd.to_numeric(loaded[column], errors="coerce").fillna(0)
        loaded["歩数"] = loaded["歩数"].astype(int)
        loaded["推定摂取カロリー(kcal)"] = loaded["推定摂取カロリー(kcal)"].astype(int)
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
    st.caption("自動推定がズレる場合は、右側のカロリー欄に手入力してください。手入力がある場合はそちらを優先します。")

    meal_col1, meal_col2 = st.columns(2)
    with meal_col1:
        breakfast = st.text_area("朝", placeholder="例：トマトジュース、ゆでたまご", height=80)
        breakfast_kcal_manual = st.number_input("朝カロリー 手入力（任意）", min_value=0, max_value=3000, value=0, step=50)

        lunch = st.text_area("昼", placeholder="例：肉ぶっかけうどん、とり天1個", height=80)
        lunch_kcal_manual = st.number_input("昼カロリー 手入力（任意）", min_value=0, max_value=4000, value=0, step=50)

        snacks = st.text_area("間食", placeholder="例：菓子 123kcal、オイコス", height=80)
        snacks_kcal_manual = st.number_input("間食カロリー 手入力（任意）", min_value=0, max_value=3000, value=0, step=50)

    with meal_col2:
        dinner = st.text_area("夜", placeholder="例：赤飯おにぎり、グリルチキン、オイコス", height=80)
        dinner_kcal_manual = st.number_input("夜カロリー 手入力（任意）", min_value=0, max_value=5000, value=0, step=50)

        work_drinks = st.text_area("仕事中のドリンク", placeholder="例：コーヒー、カフェラテ、プロテイン", height=80)
        drinks_kcal_manual = st.number_input("ドリンクカロリー 手入力（任意）", min_value=0, max_value=2000, value=0, step=50)

    st.subheader("筋トレ")
    trained = st.checkbox("筋トレした")
    training_detail = st.text_area(
        "筋トレ内容",
        placeholder="例：ベンチプレス 90kg 5,6,6,4 / 懸垂 10,10,5 / サイドレイズ 12kg 15回×3",
        height=120,
    )

    submitted = st.form_submit_button("CSVに保存する")

if submitted:
    breakfast_kcal = final_kcal(estimate_calories(breakfast, "朝"), breakfast_kcal_manual)
    lunch_kcal = final_kcal(estimate_calories(lunch, "昼"), lunch_kcal_manual)
    dinner_kcal = final_kcal(estimate_calories(dinner, "夜"), dinner_kcal_manual)
    snacks_kcal = final_kcal(estimate_calories(snacks, "間食"), snacks_kcal_manual)
    drinks_kcal = final_kcal(estimate_calories(work_drinks, "仕事中のドリンク"), drinks_kcal_manual)
    estimated_calories = breakfast_kcal + lunch_kcal + dinner_kcal + snacks_kcal + drinks_kcal

    new_row = pd.DataFrame([{
        "日付": pd.to_datetime(record_date),
        "体重(kg)": weight,
        "歩数": steps,
        "朝": breakfast,
        "朝カロリー(kcal)": breakfast_kcal,
        "昼": lunch,
        "昼カロリー(kcal)": lunch_kcal,
        "夜": dinner,
        "夜カロリー(kcal)": dinner_kcal,
        "間食": snacks,
        "間食カロリー(kcal)": snacks_kcal,
        "仕事中のドリンク": work_drinks,
        "ドリンクカロリー(kcal)": drinks_kcal,
        "推定摂取カロリー(kcal)": estimated_calories,
        "筋トレ": "あり" if trained else "なし",
        "筋トレ内容": training_detail,
        "ベンチプレス(kg)": bench if trained else 0,
    }])
    df = pd.concat([df, new_row], ignore_index=True)
    df = df.sort_values("日付")
    save_data(df)
    st.success(f"CSVへ保存しました！合計カロリーは約{estimated_calories:,}kcalです。")
    st.write(f"朝 {breakfast_kcal:,}kcal / 昼 {lunch_kcal:,}kcal / 夜 {dinner_kcal:,}kcal / 間食 {snacks_kcal:,}kcal / ドリンク {drinks_kcal:,}kcal")

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
    c4.metric("平均摂取カロリー", f"{df['推定摂取カロリー(kcal)'].mean():,.0f}kcal")
    c5.metric("筋トレ回数", f"{int((df['筋トレ'] == 'あり').sum())}回")

    st.subheader("82kg到達予測")
    st.info(predict_target_date(df, TARGET_WEIGHT))

    st.subheader("体重推移")
    st.line_chart(df_for_chart[["体重(kg)", "7日平均体重(kg)"]])

    st.subheader("摂取カロリー推移")
    st.bar_chart(df_for_chart[["推定摂取カロリー(kcal)"]])

    st.subheader("歩数推移")
    st.bar_chart(df_for_chart[["歩数"]])

    st.subheader("直近の食事・筋トレ内容")
    st.write(f"朝：{latest.get('朝', '')} / {int(latest.get('朝カロリー(kcal)', 0)):,}kcal")
    st.write(f"昼：{latest.get('昼', '')} / {int(latest.get('昼カロリー(kcal)', 0)):,}kcal")
    st.write(f"夜：{latest.get('夜', '')} / {int(latest.get('夜カロリー(kcal)', 0)):,}kcal")
    st.write(f"間食：{latest.get('間食', '')} / {int(latest.get('間食カロリー(kcal)', 0)):,}kcal")
    st.write(f"仕事中のドリンク：{latest.get('仕事中のドリンク', '')} / {int(latest.get('ドリンクカロリー(kcal)', 0)):,}kcal")
    st.write(f"筋トレ：{latest.get('筋トレ内容', '')}")

    st.subheader("記録一覧")
    st.dataframe(df, use_container_width=True)

    csv = df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
    st.download_button("CSVダウンロード", csv, "body_recomp_records.csv", "text/csv")

st.caption("注意：カロリーは概算です。正確にしたい日は手入力欄を使ってください。")
