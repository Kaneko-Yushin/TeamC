# ファイル名: care_diary.py
# 実行方法: streamlit run care_diary.py

import streamlit as st
import pandas as pd
from datetime import datetime

# 既存データの読み込み
if "entries" not in st.session_state:
    st.session_state.entries = []

st.title("📝 介護日誌 記録画面")

with st.form("care_form", clear_on_submit=True):
    date_time = st.datetime_input("日時", datetime.now())
    resident = st.selectbox("利用者", ["佐藤 次郎(101)", "鈴木 花子(102)", "高橋 一郎(103)"])
    activity = st.selectbox("活動カテゴリ", ["", "入浴", "排泄", "食事", "移乗", "機能訓練", "服薬", "その他"])
    
    st.subheader("バイタルサイン")
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        temperature = st.number_input("体温(℃)", min_value=30.0, max_value=43.0, step=0.1)
    with col2:
        blood_pressure = st.text_input("血圧", placeholder="120/80")
    with col3:
        pulse = st.number_input("脈拍", min_value=0, max_value=200, step=1)
    with col4:
        respiration = st.number_input("呼吸", min_value=0, max_value=60, step=1)
    
    mood = st.selectbox("気分", ["良い", "普通", "不調", "無表情"])
    medication = st.text_input("服薬・処置", placeholder="例: アリセプト 朝1錠")
    notes = st.text_area("詳細・観察メモ", height=150)
    
    photos = st.file_uploader("写真（最大5枚）", accept_multiple_files=True, type=["png", "jpg", "jpeg"])
    
    submitted = st.form_submit_button("💾 保存")
    if submitted:
        entry = {
            "日時": date_time,
            "利用者": resident,
            "活動": activity,
            "体温": temperature,
            "血圧": blood_pressure,
            "脈拍": pulse,
            "呼吸": respiration,
            "気分": mood,
            "服薬": medication,
            "メモ": notes,
            "写真枚数": len(photos) if photos else 0,
        }
        st.session_state.entries.insert(0, entry)  # 新しい順で保存
        st.success("保存しました ✅")

st.divider()
st.subheader("📚 過去の記録")

if st.session_state.entries:
    df = pd.DataFrame(st.session_state.entries)
    st.dataframe(df, use_container_width=True)
else:
    st.info("まだ記録がありません。")
