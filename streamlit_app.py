from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import os
import threading
import numpy as np
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import streamlit as st
from pyproj import Transformer
from streamlit_js_eval import get_geolocation

st.set_page_config(page_title="내 주변 오락실 탐색", page_icon="🕹️", layout="wide")
API = "https://apis.data.go.kr/1741000/youth_game_providers/info"
SOURCE = "https://www.data.go.kr/data/15154958/openapi.do"
SNAPSHOT = "https://raw.githubusercontent.com/1100qpzm/my-streamlit-app/main/data/arcades.csv"


def prepare(raw):
    df = raw.copy().fillna("")
    df = df[df["SALS_STTS_CD"].astype(str).str.zfill(2) == "01"].copy()
    df["ID"] = df["OPN_ATMY_GRP_CD"].astype(str) + ":" + df["MNG_NO"].astype(str)
    df = df.drop_duplicates("ID")
    if "latitude" not in df:
        x = pd.to_numeric(df["CRD_INFO_X"], errors="coerce").to_numpy()
        y = pd.to_numeric(df["CRD_INFO_Y"], errors="coerce").to_numpy()
        df["longitude"], df["latitude"] = Transformer.from_crs(5174, 4326, always_xy=True).transform(x, y)
    for field in ["latitude", "longitude"]:
        df[field] = pd.to_numeric(df[field], errors="coerce")
    df["게임기 수"] = pd.to_numeric(df["TOTAL_GMCON_CNT"], errors="coerce")
    df["인허가일"] = pd.to_datetime(df["LCPMT_YMD"], errors="coerce")
    df["주소"] = df["ROAD_NM_ADDR"].where(df["ROAD_NM_ADDR"] != "", df["LOTNO_ADDR"])
    return df


@st.cache_data(ttl=3600, show_spinner="전국 오락실의 최신 정보를 조회하고 있어요...")
def live_data(_key):
    connections = threading.local()
    def page(number):
        if not hasattr(connections, "session"):
            connections.session = requests.Session()
            retry = Retry(total=2, backoff_factor=0.5, status_forcelist=[429, 500, 502, 503, 504])
            connections.session.mount("https://", HTTPAdapter(max_retries=retry))
        params = {"serviceKey": _key, "pageNo": number,
            "numOfRows": 100, "returnType": "json", "cond[SALS_STTS_CD::EQ]": "01"}
        r = connections.session.get(API, params=params, timeout=(8, 20))
        r.raise_for_status()
        result = r.json()["response"]
        if str(result["header"]["resultCode"]) != "0":
            raise ValueError("API 조회 실패")
        return result["body"]
    first = page(1)
    rows = first["items"]["item"]
    with ThreadPoolExecutor(max_workers=4) as pool:
        for body in pool.map(page, range(2, (int(first["totalCount"]) + 99) // 100 + 1)):
            rows.extend(body["items"]["item"])
    if len(rows) != int(first["totalCount"]):
        raise ValueError("일부 페이지 누락")
    return prepare(pd.DataFrame(rows)), datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M")


@st.cache_data(show_spinner=False)
def saved_data():
    path = Path(__file__).parent / "data" / "arcades.csv"
    return prepare(pd.read_csv(path if path.exists() else SNAPSHOT, dtype=str))


def distance_km(lat, lon, lats, lons):
    a, b = np.radians(lat), np.radians(lats)
    h = np.sin((b-a)/2)**2 + np.cos(a)*np.cos(b)*np.sin(np.radians(lons-lon)/2)**2
    return 6371.0088 * 2 * np.arcsin(np.sqrt(np.clip(h, 0, 1)))


st.title("🕹️ 내 주변 오락실 탐색")
st.write("가까운 오락실부터, 게임기가 많은 곳과 최근 인허가된 곳까지 찾아보세요.")
st.sidebar.header("내 위치와 검색 조건")
if st.sidebar.button("최신 데이터 불러오기", width="stretch"):
    live_data.clear()
key = os.environ.get("LOCALDATA_API_KEY", "")
if not key:
    try:
        key = st.secrets.get("LOCALDATA_API_KEY", "")
    except (FileNotFoundError, st.errors.StreamlitSecretNotFoundError):
        pass
if key:
    try:
        data, fetched = live_data(key)
        st.caption(f"API 조회 {fetched} KST / 1시간 캐시 / 전국 영업 중 사업장 {len(data):,}곳")
    except Exception:
        data = saved_data()
        st.warning("API 연결이 지연되어 2026-11-11 저장 데이터를 표시합니다. 잠시 후 최신 데이터를 다시 불러오세요.")
else:
    data = saved_data()
    st.info("2026-11-11 API 수집 데이터를 표시합니다. 실시간 조회는 앱의 API 키 설정 후 사용할 수 있습니다.")
st.caption("원본 데이터는 매일 갱신되며 2일 전 기준으로 현행화됩니다. 거리는 직선거리입니다.")
presets = {"서울대학교 정문": (37.4663, 126.9485), "강남역": (37.4979, 127.0276),
           "홍대입구역": (37.5572, 126.9245), "부산 서면역": (35.1578, 129.0592), "직접 입력": (37.5665, 126.9780)}
place = st.sidebar.selectbox("기준 위치", list(presets))
lat0, lon0 = presets[place]
lat = st.sidebar.number_input("위도", min_value=33.0, max_value=39.5, value=lat0, format="%.6f", key=f"lat_{place}")
lon = st.sidebar.number_input("경도", min_value=124.0, max_value=132.0, value=lon0, format="%.6f", key=f"lon_{place}")
if st.sidebar.checkbox("기기에서 현재 위치 가져오기"):
    st.sidebar.caption("브라우저 위치 권한을 허용해 주세요. 위치는 검색 계산에 사용됩니다.")
    loc = get_geolocation()
    if loc and "coords" in loc:
        lat, lon = loc["coords"]["latitude"], loc["coords"]["longitude"]
        st.sidebar.success(f"현재 위치: {lat:.5f}, {lon:.5f}")
    elif loc and "error" in loc:
        st.sidebar.warning("현재 위치를 가져오지 못했어요. 좌표를 직접 입력해 주세요.")
    else:
        st.sidebar.info("위치 확인 중입니다. 확인 전에는 입력한 위치를 사용합니다.")
use_radius = st.sidebar.checkbox("검색 반경 필터 사용", value=True)
radius = st.sidebar.slider("검색 반경 (km)", 1, 100, 5, disabled=not use_radius)
if not use_radius:
    st.sidebar.caption("거리 제한 없이 전국에서 검색합니다.")
minimum = st.sidebar.slider("최소 게임기 수", 0, 200, 0, step=5)
include_missing = st.sidebar.checkbox("게임기 수 미등록 포함", value=True)
years = st.sidebar.slider("인허가 연도", 1950, datetime.now().year, (1950, datetime.now().year))
keyword = st.sidebar.text_input("사업장명 또는 게임 품목 검색")
order = st.sidebar.radio("정렬", ["가까운 순", "게임기 많은 순", "최근 인허가 순"])
valid = data["latitude"].between(33, 39.5) & data["longitude"].between(124, 132)
near = data.loc[valid].copy()
near["거리 (km)"] = distance_km(lat, lon, near["latitude"], near["longitude"])
if use_radius:
    near = near[near["거리 (km)"] <= radius]
near = near[near["인허가일"].dt.year.between(*years)]
machine_match = near["게임기 수"] >= minimum
if include_missing:
    machine_match |= near["게임기 수"].isna()
near = near[machine_match]
if keyword:
    near = near[near["BPLC_NM"].str.contains(keyword, case=False, regex=False) |
                near["FBCTN_HNDL_ITEM_CN"].str.contains(keyword, case=False, regex=False)]
sorts = {"가까운 순": ("거리 (km)", True), "게임기 많은 순": ("게임기 수", False), "최근 인허가 순": ("인허가일", False)}
column, ascending = sorts[order]
near = near.sort_values([column, "ID"], ascending=[ascending, True], na_position="last")
a, b, c = st.columns(3)
a.metric("조건에 맞는 오락실", f"{len(near):,}곳")
b.metric("가장 가까운 거리", f"{near['거리 (km)'].min():.2f} km" if len(near) else "검색 결과 없음")
c.metric("게임기 수 등록 사업장", f"{near['게임기 수'].notna().sum():,}곳")
st.caption(f"검색 기준 {lat:.5f}, {lon:.5f} / 좌표 누락 또는 범위 오류로 거리 검색에서 제외한 전국 사업장 {(~valid).sum():,}곳")
if near.empty:
    st.info("검색 결과가 없어요. 검색 반경을 늘리거나 게임기 수와 연도 조건을 넓혀보세요.")
else:
    closest = near.loc[near["거리 (km)"].idxmin()]
    st.subheader(f"가장 가까운 곳: {closest['BPLC_NM']}")
    st.write(f"{closest['주소']} / 직선거리 {closest['거리 (km)']:.2f} km")
    st.header("위치 지도")
    points = near[["latitude", "longitude"]].copy()
    points["color"] = "#6d5dfc"
    points = pd.concat([points, pd.DataFrame([{"latitude": lat, "longitude": lon, "color": "#f97316"}])])
    st.map(points, color="color", size=35)
    st.caption("보라색: 오락실 / 주황색: 검색 기준 위치")
    st.header("오락실 목록")
    shown = near.rename(columns={"BPLC_NM": "사업장명", "PVSN_VG_NM": "제공게임물", "FBCTN_HNDL_ITEM_CN": "게임 품목", "DTL_SALS_STTS_NM": "영업상태"})
    columns = ["사업장명", "거리 (km)", "게임기 수", "인허가일", "주소", "게임 품목"]
    st.dataframe(shown[columns], hide_index=True, width="stretch",
        column_config={"거리 (km)": st.column_config.NumberColumn(format="%.2f"), "인허가일": st.column_config.DateColumn(format="YYYY-MM-DD")})
    st.header("주변 오락실 비교")
    chart = st.radio("차트 선택", ["게임기 수 비교", "연도별 인허가 수"], horizontal=True)
    if chart == "게임기 수 비교":
        counts = near.dropna(subset=["게임기 수"]).head(15).copy()
        if counts.empty:
            st.info("검색된 사업장에 등록된 게임기 수가 없습니다.")
        else:
            counts["사업장"] = counts["BPLC_NM"] + " (" + counts["거리 (km)"].round(2).astype(str) + "km)"
            st.bar_chart(counts.set_index("사업장")[["게임기 수"]])
    else:
        st.bar_chart(near.groupby(near["인허가일"].dt.year).size().rename("사업장 수"))
    st.caption("현재 영업 중이며 검색 조건에 맞는 사업장만 집계합니다. 인허가일은 행정상 등록일입니다.")
    st.download_button("검색 결과 CSV 저장", shown[columns].to_csv(index=False).encode("utf-8-sig"), "주변_오락실.csv", "text/csv")
st.markdown(f"[행정안전부 청소년게임제공업 데이터 출처]({SOURCE})")
