import streamlit as st
import pandas as pd
import numpy as np

st.title("나의 첫 번째 Streamlit 앱")

# ── 사이드바 ──────────────────────────────────
st.sidebar.title("설정")

chart_type = st.sidebar.radio(
    "차트 유형",
    ["꺾은선 그래프", "막대 그래프", "면적 그래프"]
)

n = st.sidebar.slider("데이터 개수", min_value=10, max_value=100, value=30)

# ── 메인 화면 ─────────────────────────────────
st.write(f"차트 유형: **{chart_type}** | 데이터 개수: **{n}개**")

data = pd.DataFrame(
    np.random.randn(n, 3),
    columns=['A', 'B', 'C']
)

if chart_type == "꺾은선 그래프":
    st.line_chart(data)
elif chart_type == "막대 그래프":
    st.bar_chart(data)
else:
    st.area_chart(data)

preview = data.head(5)
stats = data.agg(["mean", "std", "min", "max"])
table = pd.concat([preview, stats])
st.dataframe(table)
