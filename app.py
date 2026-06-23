import streamlit as st

st.title("筋トレ・減量管理アプリ")

weight = st.number_input("今日の体重(kg)", value=85.0)

if st.button("記録"):
    st.success(f"{weight}kg を記録しました")
