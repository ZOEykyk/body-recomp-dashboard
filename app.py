import datetime as dt
from pathlib import Path
import pandas as pd
import streamlit as st

DATA_FILE = 'records.csv'

st.set_page_config(page_title='筋トレ・減量管理アプリ', page_icon='💪', layout='wide')
st.title('💪 筋トレ・減量管理アプリ')
st.caption('体重・歩数・筋トレを記録して、減量と筋力アップを見える化します。')

if Path(DATA_FILE).exists():
    df = pd.read_csv(DATA_FILE)
    if not df.empty:
        df['日付'] = pd.to_datetime(df['日付'])
else:
    df = pd.DataFrame(columns=['日付','体重(kg)','歩数','摂取カロリー(kcal)','筋トレ','ベンチプレス(kg)'])

st.header('今日の記録')
with st.form('daily_record_form'):
    col1,col2,col3 = st.columns(3)
    with col1:
        record_date = st.date_input('日付', value=dt.date.today())
        weight = st.number_input('朝の体重(kg)',40.0,150.0,85.0,0.1)
    with col2:
        steps = st.number_input('歩数',0,50000,7000,500)
        calories = st.number_input('摂取カロリー(kcal)',0,6000,2300,50)
    with col3:
        trained = st.checkbox('筋トレした')
        bench = st.number_input('ベンチプレス最高重量(kg)',0.0,250.0,90.0,2.5)
    submitted = st.form_submit_button('記録する')

if submitted:
    new_row = pd.DataFrame([{
        '日付':record_date,
        '体重(kg)':weight,
        '歩数':steps,
        '摂取カロリー(kcal)':calories,
        '筋トレ':'あり' if trained else 'なし',
        'ベンチプレス(kg)':bench if trained else 0
    }])

    df = pd.concat([df,new_row], ignore_index=True)
    df.to_csv(DATA_FILE,index=False)
    st.success('CSVへ保存しました！')

if not df.empty:
    df = df.sort_values('日付')
    latest = df.iloc[-1]

    c1,c2,c3,c4 = st.columns(4)
    c1.metric('最新体重', f"{latest['体重(kg)']:.1f}kg")
    c2.metric('平均体重', f"{df['体重(kg)'].mean():.1f}kg")
    c3.metric('平均歩数', f"{df['歩数'].mean():,.0f}")
    c4.metric('筋トレ回数', int((df['筋トレ']=='あり').sum()))

    st.subheader('体重推移')
    st.line_chart(df.set_index('日付')[['体重(kg)']])

    st.subheader('歩数推移')
    st.bar_chart(df.set_index('日付')[['歩数']])

    st.subheader('記録一覧')
    st.dataframe(df, use_container_width=True)

    csv = df.to_csv(index=False).encode('utf-8-sig')
    st.download_button('CSVダウンロード', csv, 'body_recomp_records.csv', 'text/csv')
else:
    st.info('まだ記録がありません。')

st.caption('次回：82kg到達予測・ベンチ100kg到達予測')