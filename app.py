import datetime as dt

import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="筋トレ・減量管理アプリ",
    page_icon="💪",
    layout="wide",
)

st.title("💪 筋トレ・減量管理アプリ")
st.caption("体重・歩数・筋トレを記録して、減量と筋力アップを見える化します。")

# -----------------------------
# 初期データ
# -----------------------------
if "records" not in st.session_state:
    st.session_state.records = []

# -----------------------------
# 入力フォーム
# -----------------------------
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
        bench_press = st.number_input("ベンチプレス最高重量(kg)", min_value=0.0, max_value=250.0, value=90.0, step=2.5)

    submitted = st.form_submit_button("記録する")

if submitted:
    st.session_state.records.append(
        {
            "日付": record_date,
            "体重(kg)": weight,
            "歩数": steps,
            "摂取カロリー(kcal)": calories,
            "筋トレ": "あり" if trained else "なし",
            "ベンチプレス(kg)": bench_press if trained else 0,
        }
    )
    st.success("記録しました！")

# -----------------------------
# 表示エリア
# -----------------------------
st.header("ダッシュボード")

if not st.session_state.records:
    st.info("まだ記録がありません。まずは今日の記録を入力してみましょう。")
else:
    df = pd.DataFrame(st.session_state.records)
    df = df.sort_values("日付")

    latest = df.iloc[-1]
    avg_weight = df["体重(kg)"].mean()
    avg_steps = df["歩数"].mean()
    training_count = (df["筋トレ"] == "あり").sum()

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("最新体重", f"{latest['体重(kg)']:.1f} kg")
    col2.metric("平均体重", f"{avg_weight:.1f} kg")
    col3.metric("平均歩数", f"{avg_steps:,.0f} 歩")
    col4.metric("筋トレ回数", f"{training_count} 回")

    st.subheader("体重推移")
    st.line_chart(df.set_index("日付")[["体重(kg)"]])

    st.subheader("歩数推移")
    st.bar_chart(df.set_index("日付")[["歩数"]])

    st.subheader("記録一覧")
    st.dataframe(df, use_container_width=True)

st.divider()
st.caption("次の改良候補：CSV保存、目標82kg到達予測、PFC管理、トレーニング種目追加")
