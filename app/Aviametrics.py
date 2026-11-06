"""Aviametrics – Streamlit front end. Talks ONLY to the API (never directly to the data)."""
import json
import os
import random
import sys
import time
from pathlib import Path

import altair as alt
import httpx
import pandas as pd
import pydeck as pdk
import streamlit as st
import streamlit.components.v1 as components

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from aviametrics.config import API_URL, CFG, DATA  # noqa: E402
from aviametrics.i18n import LANGS, t  # noqa: E402

PUBLIC_API = os.environ.get("AVIA_PUBLIC_API", "http://localhost:8000")
LAT0, LAT1, LON0, LON1 = CFG["area"]["bbox_core"]
st.set_page_config(page_title="Aviametrics", page_icon="✈️", layout="wide")
st.markdown("""<style>
@import url('https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@600;700&display=swap');
.block-container{padding-top:1.4rem;max-width:1600px}
header[data-testid="stHeader"],#MainMenu,footer,[data-testid="stToolbar"],[data-testid="stDecoration"]{display:none !important}
.stTabs [data-baseweb="tab"]{font-family:'Cormorant Garamond',Georgia,serif;font-size:1.15rem;letter-spacing:.06em}
[data-testid="stMetric"]{background:#15181d;border:1px solid #3a3222;border-radius:8px;padding:10px 14px}
[data-testid="stMetricLabel"]{color:#a9a294}
h1,h2,h3{font-family:'Cormorant Garamond',Georgia,serif !important;letter-spacing:.04em}
.avia-title{font-family:'Cormorant Garamond',Georgia,serif;font-size:2.6rem;letter-spacing:.22em;color:#d9b36c;margin:0}
.avia-tag{color:#a9a294;margin-top:-6px}
[data-testid="stMetricValue"]{font-family:'Cormorant Garamond',Georgia,serif;font-size:2.3rem;color:#e7c27d}
.fact{border-left:3px solid #d9b36c;padding:6px 12px;margin:8px 0;background:rgba(217,179,108,.08);border-radius:4px}
</style>""", unsafe_allow_html=True)

# ------------------------------------------------------------------ sidebar
lang = st.sidebar.radio("🌐", list(LANGS), format_func=LANGS.get, horizontal=True,
                        index=list(LANGS).index(CFG["app"]["default_language"]))
role = st.sidebar.radio(t(lang, "role"), ["visitor", "analyst"], format_func=lambda r: t(lang, f"role_{r}"),
                        help=t(lang, "role_help"))
st.sidebar.markdown("---")
st.sidebar.caption("Flugdatenanalyse für das BMLV · TGM 2026/27\n\nStefan Aschauer · Isaac Jerryson")
st.sidebar.caption(t(lang, "credits"))
H = {"X-Role": role}


def api(path, method="GET", **kw):
    try:
        r = httpx.request(method, f"{API_URL}{path}", headers=H, timeout=60, **kw)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


st.markdown('<p class="avia-title">AVIAMETRICS</p>', unsafe_allow_html=True)
st.markdown(f'<p class="avia-tag">{t(lang, "tagline")}</p>', unsafe_allow_html=True)
tabs = st.tabs([t(lang, k) for k in ["tab_live", "tab_time", "tab_numbers", "tab_guess", "tab_plugin", "tab_data", "tab_arch"]])


def alt_color(a):
    x = 0 if a is None or pd.isna(a) else max(0.0, min(1.0, float(a) / 40000))
    return [int(80 + 175 * x), int(170 + 30 * x - 60 * x * x), int(255 - 210 * x), 235]


@st.cache_data
def bundeslaender():
    c = [p for p in (DATA / "geo").glob("2021/**/*.json") if "laender" in p.name.lower() and "topo" not in str(p).lower()]
    return json.loads(min(c, key=lambda p: p.stat().st_size).read_text()) if c else None


def outline():
    g = bundeslaender()
    return [pdk.Layer("GeoJsonLayer", g, stroked=True, filled=True, get_fill_color=[217, 179, 108, 10],
                      get_line_color=[217, 179, 108, 120], line_width_min_pixels=1)] if g else []


# ------------------------------------------------------------------ 1 live radar
with tabs[0]:
    view3d = st.toggle(t(lang, "view3d"), value=False)

    @st.fragment(run_every=10)
    def live():
        d = api("/v1/live")
        if d is None:
            st.error(t(lang, "no_api")); return
        df = pd.DataFrame(d["aircraft"])
        if df.empty:
            st.warning("–"); return
        hist = st.session_state.setdefault("trails", {})
        now = time.time()
        for r in df.itertuples():
            hist.setdefault(r.icao, []).append((now, r.lon, r.lat, float(r.alt or 0) * 0.3048))
        for k in list(hist):
            hist[k] = [p for p in hist[k] if now - p[0] < 240][-25:]
            if not hist[k]:
                del hist[k]
        for col in ["flight", "type", "reg", "icao"]:
            df[col] = df[col].fillna("").astype(str)
        df["alt"] = pd.to_numeric(df.alt, errors="coerce").fillna(0).astype(int)
        df["gs"] = pd.to_numeric(df.gs, errors="coerce").fillna(0).round().astype(int)
        df["color"] = df.alt.map(alt_color)
        df["alt_m"] = df.alt.astype(float) * 0.3048 * (3 if view3d else 0)
        df = df[["icao", "flight", "type", "reg", "lat", "lon", "alt", "gs", "alt_m", "color"]]
        at = df[df.lat.between(LAT0, LAT1) & df.lon.between(LON0, LON1)]
        left, right = st.columns([3, 1])
        right.metric(t(lang, "over_at"), len(at))
        right.metric(t(lang, "in_radius"), len(df))
        right.metric(t(lang, "highest"), f"{int(at.alt.max()):,} ft".replace(",", ".") if len(at) else "–")
        tp = at[(at.type != "") & (at.type != "MIL")].type.value_counts()
        right.metric(t(lang, "common"), tp.index[0] if len(tp) else "–")
        if len(tp):
            right.dataframe(tp.head(8).rename_axis(t(lang, "types")).reset_index(name="#"), hide_index=True, use_container_width=True)
        trails = pd.DataFrame([{"path": [[p[1], p[2], p[3] * (3 if view3d else 0)] for p in v]} for v in hist.values() if len(v) > 1])
        layers = outline()
        if len(trails):
            layers.append(pdk.Layer("PathLayer", trails, get_path="path", get_color=[217, 179, 108, 110], width_min_pixels=1.5))
        if view3d:
            df["ground"] = df.apply(lambda r: [r.lon, r.lat, 0], axis=1)
            df["air"] = df.apply(lambda r: [r.lon, r.lat, r.alt_m], axis=1)
            layers.append(pdk.Layer("LineLayer", df, get_source_position="ground", get_target_position="air",
                                    get_color=[120, 160, 200, 60], get_width=1))
        layers.append(pdk.Layer("ScatterplotLayer", df, get_position=["lon", "lat", "alt_m"], get_fill_color="color",
                                get_radius=2200, radius_min_pixels=3, radius_max_pixels=10, pickable=True))
        with left:
            st.pydeck_chart(pdk.Deck(layers=layers, map_provider="carto", map_style="dark",
                                     initial_view_state=pdk.ViewState(latitude=47.6, longitude=13.4, zoom=6.3,
                                                                      pitch=50 if view3d else 0, bearing=-10 if view3d else 0),
                                     tooltip={"text": "{flight} · {type}\n{alt} ft · {gs} kt"}), height=640)
        mode = t(lang, f"mode_{d['mode']}")
        st.caption(f"{t(lang, 'source')}: {d['source']} · {mode} · {time.strftime('%H:%M:%S')}"
                   + (f" · {t(lang, 'masked')}" if role == "visitor" else ""))
    live()

# ------------------------------------------------------------------ 2 time travel
days = api("/v1/days") or []
with tabs[1]:
    st.caption(t(lang, "play_hint"))
    if not days:
        st.info(t(lang, "no_days"))
    else:
        day = st.selectbox(t(lang, "day"), days, index=len(days) - 1, key="tt_day")

        @st.cache_data(show_spinner=True)
        def trips(day, role):
            return api(f"/v1/trips/{day}?step_s=60")
        data = trips(day, role)
        if data:
            html = (Path(__file__).parent / "timetravel.html").read_text()
            components.html(html.replace("__TRIPS__", json.dumps(data["trips"], separators=(",", ":")))
                            .replace("__GEO__", json.dumps(bundeslaender() or {"type": "FeatureCollection", "features": []}))
                            .replace("__MASK__", "true" if role == "visitor" else "false"), height=640)
    with st.expander(t(lang, "load_day")):
        new = st.date_input(t(lang, "day"), value=None, format="DD.MM.YYYY", key="newday")
        if new and st.button(t(lang, "load_btn")):
            api(f"/v1/days/{new}", method="POST")
            st.success(t(lang, "load_started"))
        if new:
            s = api(f"/v1/days/{new}/status")
            if s:
                st.caption(f"{s['status']} · {s['log']}")

# ------------------------------------------------------------------ 3 numbers
with tabs[2]:
    if days:
        day = st.selectbox(t(lang, "day"), days, index=len(days) - 1, key="num_day")

        @st.cache_data
        def stats(day):
            return api(f"/v1/stats/{day}")
        s = stats(day)
        if s:
            k = s["kpis"]
            c = st.columns(4)
            for col, key in zip(c, ["positions", "aircraft", "flights", "km"]):
                col.metric(t(lang, key), f"{k[key]:,}".replace(",", ".") if k[key] is not None else "–")
            a, b = st.columns(2)
            a.subheader(t(lang, "per_hour"))
            a.altair_chart(alt.Chart(pd.DataFrame(s["hourly"])).mark_area(color="#d9b36c", opacity=.75, line=True)
                           .encode(x=alt.X("hour:Q", title=None), y=alt.Y("aircraft:Q", title=None)), use_container_width=True)
            b.subheader(t(lang, "types"))
            b.altair_chart(alt.Chart(pd.DataFrame(s["types"])).mark_bar(color="#7fa7c9")
                           .encode(x=alt.X("aircraft:Q", title=None), y=alt.Y("type:N", sort="-x", title=None)), use_container_width=True)
            if s["regions"]:
                st.subheader(t(lang, "per_region"))
                reg = pd.DataFrame(s["regions"])
                g = bundeslaender()
                if g:
                    mx = max(reg.km.max(), 1)
                    kmap = dict(zip(reg.region, reg.km))
                    for f in g["features"]:
                        v = kmap.get(f["properties"].get("name"), 0)
                        f["properties"]["km"] = int(v)
                        f["properties"]["fill"] = [217, 179, 108, int(40 + 200 * v / mx)]
                    st.pydeck_chart(pdk.Deck(layers=[pdk.Layer("GeoJsonLayer", g, filled=True, stroked=True, pickable=True,
                                                               get_fill_color="properties.fill", get_line_color=[30, 30, 30, 200])],
                                             map_provider="carto", map_style="dark", tooltip={"text": "{name}: {km} km"},
                                             initial_view_state=pdk.ViewState(latitude=47.6, longitude=13.4, zoom=6.2)), height=420)
                st.altair_chart(alt.Chart(reg).mark_bar(color="#d9b36c").encode(x=alt.X("km:Q", title="km"), y=alt.Y("region:N", sort="-x", title=None)),
                                use_container_width=True)
            f = s["facts"]
            st.subheader(t(lang, "facts"))
            if "longest_flight" in f:
                st.markdown(f'<div class="fact">✈️ {t(lang, "fact_longest", **f["longest_flight"])}</div>', unsafe_allow_html=True)
            if "busiest_minute" in f:
                m = (f["busiest_minute"]["utc_minute_of_day"] + 60) % 1440
                st.markdown(f'<div class="fact">⏱️ {t(lang, "fact_busiest", aircraft=f["busiest_minute"]["aircraft"], time=f"{m // 60:02d}:{m % 60:02d}")}</div>', unsafe_allow_html=True)
            if "highest" in f:
                st.markdown(f'<div class="fact">🏔️ {t(lang, "fact_highest", type=f["highest"]["type"], alt=f"{f["highest"]["alt_ft"]:,}".replace(",", "."))}</div>', unsafe_allow_html=True)
    else:
        st.info(t(lang, "no_days"))

# ------------------------------------------------------------------ 4 guess
with tabs[3]:
    st.subheader(t(lang, "guess_q"))
    g = st.number_input("", min_value=0, max_value=2000, value=50, step=5, label_visibility="collapsed")
    if st.button(t(lang, "guess_btn")):
        d = api("/v1/live")
        if d:
            df = pd.DataFrame(d["aircraft"])
            real = int((df.lat.between(LAT0, LAT1) & df.lon.between(LON0, LON1)).sum()) if len(df) else 0
            if real == g:
                st.balloons(); st.success(t(lang, "guess_exact"))
            else:
                st.info(t(lang, "guess_off", real=real, diff=abs(real - g)))
                if abs(real - g) <= max(3, real * 0.1):
                    st.balloons()

# ------------------------------------------------------------------ 5 plugin lab
with tabs[4]:
    st.write(t(lang, "plugin_intro"))
    st.markdown(f"[{t(lang, 'plugin_docs')} →]({PUBLIC_API}/docs)")
    plugin = Path(__file__).resolve().parents[1] / "plugins" / "co2_demo.py"
    if days:
        pday = st.selectbox(t(lang, "day"), days, index=len(days) - 1, key="pl_day")
        if st.button(t(lang, "plugin_run")):
            sys.path.insert(0, str(plugin.parent))
            import co2_demo  # noqa: E402
            t0 = time.perf_counter()
            res = co2_demo.run(API_URL, pday, role)
            st.success(f"{time.perf_counter() - t0:.1f} s")
            st.altair_chart(alt.Chart(res.head(15)).mark_bar(color="#7fa7c9").encode(
                x=alt.X("t_co2:Q", title="t CO₂ (Demo)"), y=alt.Y("type:N", sort="-x", title=None)), use_container_width=True)
            st.dataframe(res, use_container_width=True, hide_index=True)
    with st.expander(t(lang, "plugin_code")):
        st.code(plugin.read_text(), language="python")

# ------------------------------------------------------------------ 6 data manager
with tabs[5]:
    cfg = api("/v1/settings") or {"folders": [], "data_dir": "?"}
    st.markdown(f"**{t(lang, 'data_location')}:** `{cfg['data_dir']}`")
    st.caption(t(lang, "data_location_help"))
    st.markdown(f"**{t(lang, 'loaded_days')}:** " + (", ".join(days) if days else "–"))
    home = cfg.get("host_home") or ""
    txt = st.text_area(t(lang, "folders"), "\n".join(f.replace(home, "~", 1) if home and f.startswith(home) else f for f in cfg["folders"]),
                       help=t(lang, "folders_help"))
    if st.button(t(lang, "scan")):
        folders = [(home + l.strip()[1:]) if l.strip().startswith("~") and home else l.strip() for l in txt.splitlines() if l.strip()]
        api("/v1/settings", method="PUT", json={"folders": folders})
        st.session_state["scan"] = api("/v1/scan") or []
    res = st.session_state.get("scan")
    if res is not None:
        if not res:
            st.info(t(lang, "found_none"))
        for i, r in enumerate(res):
            c = st.columns([4, 2, 2])
            c[0].markdown(f"`{r['folder']}`")
            if r.get("error"):
                c[1].error(r["error"]); continue
            c[1].markdown(f"**{r.get('day') or '?'}**")
            if r.get("loaded"):
                c[2].caption(t(lang, "already"))
            elif r.get("day") and c[2].button(t(lang, "import_btn"), key=f"imp{i}"):
                api(f"/v1/days/{r['day']}", method="POST", params={"source": r["folder"]})
                st.success(t(lang, "load_started"))
    st.markdown("---")
    st.markdown(f"**{t(lang, 'load_day')}**")
    nd = st.date_input(t(lang, "day"), value=None, format="DD.MM.YYYY", key="dl_day")
    if nd and st.button(t(lang, "load_btn"), key="dl_btn"):
        api(f"/v1/days/{nd}", method="POST")
        st.success(t(lang, "load_started"))

# ------------------------------------------------------------------ 7 architecture
with tabs[6]:
    st.code("""
 adsb.lol archive ──HTTPS──► [pipeline] Dagster ──► DuckLake (SQLite catalog + Parquet, per day) ◄──DuckDB── [api] FastAPI ◄──HTTP── [app] Streamlit ◄── you
 adsb.lol / adsb.fi / airplanes.live (live, fallback chain) ──────────────────────► /v1/live    ▲
                                                                       CO₂ plugin (external) ──┘  JSON / Arrow
""", language=None)
    st.caption(t(lang, "arch_note"))
