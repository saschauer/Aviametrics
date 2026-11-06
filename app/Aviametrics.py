"""Aviametrics – Streamlit front end. Talks ONLY to the API (never directly to the data)."""
import json
import os
import sys
import time
from datetime import date
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
GOLD, BLUE = "#d9b36c", "#7fa7c9"
st.set_page_config(page_title="Aviametrics", page_icon="✈️", layout="wide")
st.markdown("""<style>
@import url('https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@600;700&display=swap');
.block-container{padding-top:1.4rem;max-width:1600px}
header[data-testid="stHeader"],#MainMenu,footer,[data-testid="stToolbar"],[data-testid="stDecoration"]{display:none !important}
h1,h2,h3{font-family:'Cormorant Garamond',Georgia,serif !important;letter-spacing:.04em}
.avia-title{font-family:'Cormorant Garamond',Georgia,serif;font-size:2.4rem;letter-spacing:.24em;color:#d9b36c;margin:0}
.avia-tag{color:#a9a294;margin-top:-6px}
.stTabs [data-baseweb="tab"]{font-family:'Cormorant Garamond',Georgia,serif;font-size:1.15rem;letter-spacing:.06em}
[data-testid="stMetric"]{background:#15181d;border:1px solid #3a3222;border-radius:8px;padding:10px 14px}
[data-testid="stMetricLabel"]{color:#a9a294}
[data-testid="stMetricValue"]{font-family:'Cormorant Garamond',Georgia,serif;font-size:2.2rem;color:#e7c27d}
.fact{border-left:3px solid #d9b36c;padding:6px 12px;margin:8px 0;background:rgba(217,179,108,.08);border-radius:4px}
.legend{display:flex;gap:18px;align-items:center;flex-wrap:wrap;font-size:.85rem;color:#a9a294;margin:2px 0 8px}
.chip{display:inline-block;border:1px solid #6b5a33;border-radius:14px;padding:2px 10px;margin:0 6px 4px 0;color:#e9e4d8;font-size:.85rem}
</style>""", unsafe_allow_html=True)


def api(path, method="GET", **kw):
    try:
        r = httpx.request(method, f"{API_URL}{path}", headers={"X-Role": st.session_state.get("role", "visitor")}, timeout=90, **kw)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        st.session_state["api_error"] = f"{method} {path}: {e}"
        return None


def alt_color(a):
    x = max(0.0, min(1.0, float(a or 0) / 40000))
    return [int(80 + 175 * x), int(170 + 30 * x - 60 * x * x), int(255 - 210 * x), 235]


@st.cache_data
def bundeslaender():
    c = [p for p in (DATA / "geo").glob("2021/**/*.json") if "laender" in p.name.lower() and "topo" not in str(p).lower()]
    return json.loads(min(c, key=lambda p: p.stat().st_size).read_text()) if c else None


def outline():
    g = bundeslaender()
    return [pdk.Layer("GeoJsonLayer", g, stroked=True, filled=True, get_fill_color=[217, 179, 108, 10],
                      get_line_color=[217, 179, 108, 120], line_width_min_pixels=1)] if g else []


def deck(layers, view, tooltip=None, height=620):
    st.pydeck_chart(pdk.Deck(layers=outline() + layers, map_provider="carto", map_style="dark",
                             initial_view_state=view, tooltip=tooltip), height=height)


AT_VIEW = pdk.ViewState(latitude=47.6, longitude=13.4, zoom=6.3)

# ------------------------------------------------------------------ sidebar: language, role, central day selection
lang = st.sidebar.radio("🌐", list(LANGS), format_func=LANGS.get, horizontal=True,
                        index=list(LANGS).index(CFG["app"]["default_language"]))
role = st.sidebar.radio(t(lang, "role"), ["visitor", "analyst"], format_func=lambda r: t(lang, f"role_{r}"),
                        help=t(lang, "role_help"), key="role")
days = api("/v1/days") or []


@st.dialog(" ")
def add_day_dialog():
    st.subheader(t(lang, "add_day"))
    d1, d2, d3 = st.tabs([t(lang, "add_download"), t(lang, "add_folder"), t(lang, "add_auto")])
    with d1:
        nd = st.date_input(t(lang, "day"), value=None, max_value=date.today(), format="DD.MM.YYYY")
        st.caption(t(lang, "download_hint"))
        if nd and st.button(t(lang, "start_download"), type="primary"):
            api(f"/v1/days/{nd}", method="POST"); st.session_state["toast"] = t(lang, "load_started"); st.rerun()
    with d2:
        st.caption(t(lang, "folder_hint"))
        pth = st.text_input(t(lang, "folder_path"), value=st.session_state.get("browse", "~/"), placeholder="~/aviabench")
        if st.button(t(lang, "scan_this"), type="primary", key="scan_path_btn"):
            st.session_state["browse"] = pth
            res = api("/v1/scan_path", params={"path": pth})
            st.session_state["found"] = res if res is not None else []
            if res is None:
                st.error(st.session_state.get("api_error", "API error"))
        with st.expander(t(lang, "browse")):
            cur = st.session_state.get("browse", "~") or "~"
            b = api("/v1/browse", params={"path": cur}) or {"path": "~", "folders": [], "parent": None}
            c = st.columns([1, 5])
            if b.get("parent") is not None and c[0].button("⬆", key="up"):
                st.session_state["browse"] = b["parent"] or "~"; st.rerun(scope="fragment")
            c[1].markdown(f"📁 `{b['path']}`" + ("  ✅ adsb.lol" if b.get("is_adsblol_day") else ""))
            sel = st.selectbox(t(lang, "subfolder"), [""] + b["folders"], key=f"sub_{cur}")
            if sel:
                st.session_state["browse"] = b["path"].rstrip("/") + "/" + sel; st.rerun(scope="fragment")
    with d3:
        st.caption(t(lang, "auto_hint"))
        if st.button(t(lang, "auto_btn"), type="primary"):
            with st.spinner(t(lang, "searching")):
                res = api("/v1/scan", params={"auto": "true"})
            st.session_state["found"] = res if res is not None else []
            if res is None:
                st.error(st.session_state.get("api_error", "API error"))
    found = st.session_state.get("found")
    if found is not None:
        st.markdown("---")
        if not found:
            st.info(t(lang, "found_none"))
        for i, r in enumerate(found):
            c = st.columns([4, 2, 2])
            c[0].markdown(f"`{r['folder']}`")
            if r.get("error"):
                c[1].error(r["error"]); continue
            c[1].markdown(f"**{r.get('day') or '?'}**")
            if r.get("loaded"):
                c[2].caption(t(lang, "already"))
            elif r.get("day") and c[2].button(t(lang, "import_btn"), key=f"imp{i}"):
                api(f"/v1/days/{r['day']}", method="POST", params={"source": r["folder"]})
                st.session_state["toast"] = t(lang, "load_started"); st.rerun()


st.sidebar.markdown("---")
day = st.sidebar.selectbox(t(lang, "day"), days, index=len(days) - 1 if days else None,
                           placeholder=t(lang, "no_days_short")) if days else None
if not days:
    st.sidebar.caption(t(lang, "no_days_short"))
if st.sidebar.button("＋ " + t(lang, "add_day"), width="stretch"):
    add_day_dialog()
if "toast" in st.session_state:
    st.toast(st.session_state.pop("toast"), icon="⏳")
st.sidebar.markdown("---")
st.sidebar.caption("Flugdatenanalyse für das BMLV · TGM 2026/27\n\nStefan Aschauer · Isaac Jerryson")
st.sidebar.caption(t(lang, "credits"))

st.markdown('<p class="avia-title">AVIAMETRICS</p>', unsafe_allow_html=True)
st.markdown(f'<p class="avia-tag">{t(lang, "tagline")}</p>', unsafe_allow_html=True)
tabs = st.tabs([t(lang, k) for k in ["tab_live", "tab_time", "tab_numbers", "tab_guess", "tab_plugin", "tab_data", "tab_arch"]])


def need_day():
    st.info(t(lang, "no_days"))
    if st.button("＋ " + t(lang, "add_day"), key=f"nd{time.time_ns()}"):
        add_day_dialog()


# ------------------------------------------------------------------ 1 live radar with Notion-style filters
FILTERS = ["f_alt", "f_speed", "f_type", "f_at", "f_ground"]
MAX_CHIPS = 4
DEFAULTS = {"v_alt": (0, 50000), "v_speed": (0, 700), "v_type": []}
for k, v in DEFAULTS.items():
    st.session_state.setdefault(k, v)


def chip_label(f):
    v = st.session_state
    if f == "f_alt":
        lo, hi = v["v_alt"]; return f"{t(lang, f)} · {lo // 1000}–{hi // 1000}k ft"
    if f == "f_speed":
        lo, hi = v["v_speed"]; return f"{t(lang, f)} · {lo}–{hi} kt"
    if f == "f_type":
        n = len(v["v_type"]); return f"{t(lang, f)}" + (f" · {n}" if n else "")
    return t(lang, f)


def remove_filter(f):
    """Callback: runs before the widgets are drawn, so their values may be reset here."""
    if f in st.session_state["filters"]:
        st.session_state["filters"].remove(f)
    for k in DEFAULTS:
        if k[2:] in f:
            st.session_state[k] = DEFAULTS[k]


def add_filter(f):
    if f not in st.session_state["filters"]:
        st.session_state["filters"].append(f)


def chip_body(f, active):
    if f == "f_alt":
        st.slider(t(lang, f), 0, 50000, step=1000, format="%d ft", key="v_alt")
    elif f == "f_speed":
        st.slider(t(lang, f), 0, 700, step=10, format="%d kt", key="v_speed")
    elif f == "f_type":
        st.multiselect(t(lang, f), st.session_state.get("live_types", []), key="v_type", placeholder=t(lang, "all_types"))
    else:
        st.caption(t(lang, f + "_hint"))
    st.button("🗑 " + t(lang, "remove"), key=f"rm_{f}", on_click=remove_filter, args=(f,))


with tabs[0]:
    active = st.session_state.setdefault("filters", [])
    visible, hidden = active[:MAX_CHIPS], active[MAX_CHIPS:]
    widths = [1.1] + [1.7] * len(visible) + ([0.6] if hidden else []) + [1.0, max(0.1, 8 - 1.7 * len(visible))]
    row = st.columns(widths, vertical_alignment="center")
    view3d = row[0].toggle(t(lang, "view3d"), value=False)
    for c, f in zip(row[1:1 + len(visible)], visible):
        with c.popover(chip_label(f), width="stretch"):
            chip_body(f, active)
    i = 1 + len(visible)
    if hidden:
        with row[i].popover("…", width="stretch"):
            for f in hidden:
                with st.expander(chip_label(f)):
                    chip_body(f, active)
        i += 1
    with row[i].popover("＋ Filter", width="stretch"):
        q = st.text_input(t(lang, "search"), placeholder=t(lang, "search_filters"), label_visibility="collapsed")
        avail = [f for f in FILTERS if f not in active and q.lower() in t(lang, f).lower()]
        for f in avail:
            st.button(t(lang, f), key=f"add_{f}", width="stretch", on_click=add_filter, args=(f,))
        if not avail:
            st.caption("–")
    fvals = {}
    for f in active:
        fvals[f] = {"f_alt": st.session_state["v_alt"], "f_speed": st.session_state["v_speed"],
                    "f_type": st.session_state["v_type"]}.get(f, True)
    st.markdown(f"""<div class="legend"><b style="color:#e9e4d8">{t(lang, "legend")}</b>
      <span>● {t(lang, "leg_dot")}</span><span style="color:{GOLD}">━ {t(lang, "leg_trail")}</span>
      <span>{t(lang, "leg_alt")}: 0 ft <span style="display:inline-block;width:140px;height:9px;border-radius:5px;vertical-align:middle;
      background:linear-gradient(90deg,rgb(80,170,255),rgb(168,186,150),rgb(255,140,45))"></span> 40.000 ft</span>
      <span>▭ {t(lang, "leg_border")}</span></div>""", unsafe_allow_html=True)

    @st.fragment(run_every=10)
    def live():
        d = api("/v1/live")
        if d is None:
            st.error(t(lang, "no_api")); return
        df = pd.DataFrame(d["aircraft"])
        if df.empty:
            st.warning("–"); return
        for col in ["flight", "type", "reg", "icao"]:
            df[col] = df[col].fillna("").astype(str)
        df["alt"] = pd.to_numeric(df.alt, errors="coerce").fillna(0).astype(int)
        df["gs"] = pd.to_numeric(df.gs, errors="coerce").fillna(0).round().astype(int)
        df["in_at"] = df["in_at"].astype(bool) if "in_at" in df else False
        st.session_state["live_types"] = sorted(x for x in df.type.unique() if x)
        hist = st.session_state.setdefault("trails", {})
        now = time.time()
        for r in df.itertuples():
            hist.setdefault(r.icao, []).append((now, r.lon, r.lat, r.alt * 0.3048))
        for k in list(hist):
            hist[k] = [p for p in hist[k] if now - p[0] < 240][-25:]
            if not hist[k]:
                del hist[k]
        # filters
        if "f_alt" in fvals:
            df = df[df.alt.between(*fvals["f_alt"])]
        if "f_speed" in fvals:
            df = df[df.gs.between(*fvals["f_speed"])]
        if fvals.get("f_type"):
            df = df[df.type.isin(fvals["f_type"])]
        if "f_ground" in fvals:
            df = df[df.alt > 0]
        at = df[df.in_at]
        if "f_at" in fvals:
            df = at
        df = df.assign(color=df.alt.map(alt_color), alt_m=df.alt * 0.3048 * (3 if view3d else 0))
        df = df[["icao", "flight", "type", "reg", "lat", "lon", "alt", "gs", "alt_m", "color"]]
        left, right = st.columns([3, 1])
        right.metric(t(lang, "over_at"), len(at))
        right.metric(t(lang, "shown"), len(df))
        right.metric(t(lang, "highest"), f"{int(at.alt.max()):,} ft".replace(",", ".") if len(at) else "–")
        tp = at[(at.type != "") & (at.type != "MIL")].type.value_counts()
        right.metric(t(lang, "common"), tp.index[0] if len(tp) else "–")
        shown = set(df.icao)
        trails = pd.DataFrame([{"path": [[p[1], p[2], p[3] * (3 if view3d else 0)] for p in v]}
                               for k, v in hist.items() if k in shown and len(v) > 1])
        layers = []
        if len(trails):
            layers.append(pdk.Layer("PathLayer", trails, get_path="path", get_color=[217, 179, 108, 110], width_min_pixels=1.5))
        if view3d:
            df = df.assign(ground=[[x, y, 0] for x, y in zip(df.lon, df.lat)], air=[[x, y, z] for x, y, z in zip(df.lon, df.lat, df.alt_m)])
            layers.append(pdk.Layer("LineLayer", df, get_source_position="ground", get_target_position="air",
                                    get_color=[120, 160, 200, 60], get_width=1))
        layers.append(pdk.Layer("ScatterplotLayer", df, get_position=["lon", "lat", "alt_m"], get_fill_color="color",
                                get_radius=2200, radius_min_pixels=3, radius_max_pixels=10, pickable=True))
        with left:
            deck(layers, pdk.ViewState(latitude=47.6, longitude=13.4, zoom=6.3, pitch=50 if view3d else 0, bearing=-10 if view3d else 0),
                 {"text": "{flight} · {type}\n{alt} ft · {gs} kt"}, height=640)
        # fetch statistics
        stats = st.session_state.setdefault("fetch_stats", [])
        if d.get("fetched_at") and (not stats or stats[-1]["t"] != d["fetched_at"]):
            stats.append({"t": d["fetched_at"], "ms": d.get("latency_ms"), "kb": round((d.get("bytes") or 0) / 1000), "n": len(d["aircraft"])})
            del stats[:-90]
        mode = t(lang, f"mode_{d['mode']}")
        ms = f" · {t(lang, 'latency')} {d['latency_ms']} ms" if d.get("latency_ms") is not None else ""
        st.caption(f"{t(lang, 'source')}: {d['source']} · {mode}{ms} · {len(d['aircraft'])} {t(lang, 'aircraft')} · "
                   f"{time.strftime('%H:%M:%S')}" + (f" · {t(lang, 'masked')}" if role == "visitor" else ""))
        if len(stats) > 1:
            with st.expander(t(lang, "fetch_stats")):
                sdf = pd.DataFrame(stats).assign(time=lambda x: pd.to_datetime(x.t, unit="s"))
                st.altair_chart(alt.Chart(sdf).mark_line(color=GOLD, point=True).encode(
                    x=alt.X("time:T", title=None), y=alt.Y("ms:Q", title=t(lang, "latency") + " (ms)"),
                    tooltip=["time:T", "ms:Q", "kb:Q", "n:Q"]), width="stretch")
                st.caption(t(lang, "fetch_stats_hint"))
    live()

# ------------------------------------------------------------------ 2 time travel
with tabs[1]:
    if not day:
        need_day()
    else:
        view = st.radio(t(lang, "tt_view"), ["anim", "heat", "hex"], horizontal=True, format_func=lambda v: t(lang, f"tt_{v}"))
        if view == "anim":
            @st.cache_data(show_spinner=True)
            def trips(day, role):
                return api(f"/v1/trips/{day}?step_s=60")
            data = trips(day, role)
            st.caption(t(lang, "play_hint"))
            if data:
                html = (Path(__file__).parent / "timetravel.html").read_text()
                components.html(html.replace("__TRIPS__", json.dumps(data["trips"], separators=(",", ":")))
                                .replace("__GEO__", json.dumps(bundeslaender() or {"type": "FeatureCollection", "features": []}))
                                .replace("__MASK__", "true" if role == "visitor" else "false"), height=640)
        else:
            @st.cache_data(show_spinner=True)
            def heatdata(day):
                return api(f"/v1/heat/{day}")
            pts = pd.DataFrame(heatdata(day) or [], columns=["lon", "lat", "alt"])
            if view == "heat":
                layer = pdk.Layer("HeatmapLayer", pts, get_position=["lon", "lat"], radius_pixels=22, intensity=1.2, threshold=0.03,
                                  color_range=[[20, 30, 60], [60, 90, 150], [120, 150, 200], [217, 179, 108], [255, 140, 45], [255, 230, 180]])
                deck([layer], AT_VIEW)
            else:
                layer = pdk.Layer("HexagonLayer", pts, get_position=["lon", "lat"], radius=4000, elevation_scale=60, extruded=True,
                                  coverage=0.9, pickable=True,
                                  color_range=[[40, 60, 100], [70, 110, 160], [140, 160, 170], [217, 179, 108], [240, 150, 60], [255, 100, 40]])
                deck([layer], pdk.ViewState(latitude=47.3, longitude=13.4, zoom=6.5, pitch=50, bearing=-15), {"text": "{elevationValue}"})
            st.caption(t(lang, f"tt_{view}_cap"))

# ------------------------------------------------------------------ 3 numbers
with tabs[2]:
    if not day:
        need_day()
    else:
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
            a.altair_chart(alt.Chart(pd.DataFrame(s["hourly"])).mark_area(color=GOLD, opacity=.75, line=True)
                           .encode(x=alt.X("hour:Q", title=None), y=alt.Y("aircraft:Q", title=None)), width="stretch")
            b.subheader(t(lang, "types"))
            b.altair_chart(alt.Chart(pd.DataFrame(s["types"])).mark_bar(color=BLUE)
                           .encode(x=alt.X("aircraft:Q", title=None), y=alt.Y("type:N", sort="-x", title=None)), width="stretch")
            if s["regions"]:
                st.subheader(t(lang, "per_region"))
                reg = pd.DataFrame(s["regions"])
                g = bundeslaender()
                m1, m2 = st.columns([3, 2])
                if g:
                    mx = max(reg.km.max(), 1)
                    kmap = dict(zip(reg.region, reg.km))
                    for f in g["features"]:
                        v = kmap.get(f["properties"].get("name"), 0)
                        f["properties"]["km"] = int(v)
                        f["properties"]["fill"] = [217, 179, 108, int(40 + 200 * v / mx)]
                    with m1:
                        st.pydeck_chart(pdk.Deck(layers=[pdk.Layer("GeoJsonLayer", g, filled=True, stroked=True, pickable=True,
                                                                   get_fill_color="properties.fill", get_line_color=[30, 30, 30, 200])],
                                                 map_provider="carto", map_style="dark", tooltip={"text": "{name}: {km} km"},
                                                 initial_view_state=pdk.ViewState(latitude=47.6, longitude=13.4, zoom=6.0)), height=420)
                m2.altair_chart(alt.Chart(reg).mark_bar(color=GOLD).encode(x=alt.X("km:Q", title="km"), y=alt.Y("region:N", sort="-x", title=None)),
                                width="stretch")
            f = s["facts"]
            st.subheader(t(lang, "facts"))
            if "longest_flight" in f:
                st.markdown(f'<div class="fact">✈️ {t(lang, "fact_longest", **f["longest_flight"])}</div>', unsafe_allow_html=True)
            if "busiest_minute" in f:
                mm = (f["busiest_minute"]["utc_minute_of_day"] + 60) % 1440
                st.markdown(f'<div class="fact">⏱️ {t(lang, "fact_busiest", aircraft=f["busiest_minute"]["aircraft"], time=f"{mm // 60:02d}:{mm % 60:02d}")}</div>', unsafe_allow_html=True)
            if "highest" in f:
                hv = f"{f['highest']['alt_ft']:,}".replace(",", ".")
                st.markdown(f'<div class="fact">🏔️ {t(lang, "fact_highest", type=f["highest"]["type"], alt=hv)}</div>', unsafe_allow_html=True)

# ------------------------------------------------------------------ 4 guess
with tabs[3]:
    st.subheader(t(lang, "guess_q"))
    g = st.number_input("guess", min_value=0, max_value=2000, value=50, step=5, label_visibility="collapsed")
    if st.button(t(lang, "guess_btn"), type="primary"):
        d = api("/v1/live")
        if d:
            real = sum(1 for a in d["aircraft"] if a.get("in_at"))
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
    if not day:
        need_day()
    elif st.button(t(lang, "plugin_run"), type="primary"):
        sys.path.insert(0, str(plugin.parent))
        import co2_demo  # noqa: E402
        t0 = time.perf_counter()
        res = co2_demo.run(API_URL, day, role)
        st.success(f"{time.perf_counter() - t0:.1f} s")
        st.altair_chart(alt.Chart(res.head(15)).mark_bar(color=BLUE).encode(
            x=alt.X("t_co2:Q", title="t CO₂ (Demo)"), y=alt.Y("type:N", sort="-x", title=None)), width="stretch")
        st.dataframe(res, width="stretch", hide_index=True)
    with st.expander(t(lang, "plugin_code")):
        st.code(plugin.read_text(), language="python")

# ------------------------------------------------------------------ 6 data: storage + live processing
with tabs[5]:
    cfg = api("/v1/settings") or {"data_dir": "?"}
    a, b = st.columns([3, 1])
    a.markdown(f"**{t(lang, 'data_location')}:** `{cfg['data_dir']}`")
    a.caption(t(lang, "data_location_help"))
    if b.button("＋ " + t(lang, "add_day"), width="stretch", type="primary", key="add_data_tab"):
        add_day_dialog()
    st.markdown(f"**{t(lang, 'loaded_days')}:** " + (", ".join(days) if days else "–"))
    st.markdown(f"#### {t(lang, 'jobs')}")

    @st.fragment(run_every=2)
    def jobs_view():
        j = api("/v1/jobs")
        if not j or not j["jobs"]:
            st.caption(t(lang, "no_jobs")); return
        stages = [x for x in j["stages"] if x != "done"]
        for job in j["jobs"]:
            with st.container(border=True):
                status, stage = job.get("status"), job.get("stage")
                icon = {"running": "⏳", "done": "✅", "failed": "❌"}.get(status, "•")
                elapsed = int(job.get("updated", 0) - job.get("started", 0))
                st.markdown(f"{icon} **{job['day']}** · {t(lang, 'st_' + status) if status else ''} · {elapsed // 60}:{elapsed % 60:02d} min")
                cols = st.columns(len(stages))
                for c, sname in zip(cols, stages):
                    if status == "done" or sname in job.get("done_stages", []):
                        mark = "✓"
                    elif sname == stage:
                        mark = "✗" if status == "failed" else "⏳"
                    else:
                        mark = "·"
                    c.markdown(f"<div style='text-align:center;font-size:.85rem'>{mark}<br>{t(lang, 'stage_' + sname)}</div>", unsafe_allow_html=True)
                if status == "running":
                    st.progress(min(1.0, (job.get("pct") or 0) / 100), text=job.get("msg") or "")
                elif status == "failed":
                    st.error(job.get("msg") or "")
                else:
                    st.success(t(lang, "job_done"))
    jobs_view()

# ------------------------------------------------------------------ 7 architecture
with tabs[6]:
    st.subheader(t(lang, "arch_title"))
    st.graphviz_chart("""
digraph G {
  rankdir=LR; bgcolor="transparent"; fontname="Helvetica"; nodesep=0.35; ranksep=0.6;
  node [shape=box, style="rounded,filled", fillcolor="#15181d", color="#6b5a33", fontcolor="#e9e4d8", fontname="Helvetica", fontsize=11];
  edge [color="#d9b36c", fontcolor="#a9a294", fontsize=9, fontname="Helvetica"];
  subgraph cluster_src { label="Sources"; color="#3a3222"; fontcolor="#d9b36c";
    arch [label="adsb.lol archive\\n(daily, ODbL)"]; live [label="Live APIs\\nadsb.lol → adsb.fi → airplanes.live"]; geo [label="Borders\\nStatistik Austria (CC BY)"]; }
  subgraph cluster_pipe { label="pipeline container · Dagster"; color="#3a3222"; fontcolor="#d9b36c";
    dl [label="Download / import\\nhttpx · tar"]; parse [label="Parse + clean\\norjson · PyArrow"]; enr [label="Bundesland\\nDuckDB spatial"]; seg [label="Flight segments\\nDuckDB SQL"]; }
  subgraph cluster_store { label="storage (../aviametrics-data)"; color="#3a3222"; fontcolor="#d9b36c";
    lake [label="DuckLake\\nSQLite catalog + Parquet per day", shape=cylinder]; }
  subgraph cluster_api { label="api container · FastAPI"; color="#3a3222"; fontcolor="#d9b36c";
    repo [label="Repository\\nDuckDB (only SQL here)"]; ep [label="/v1/… endpoints\\nJSON + Arrow · OpenAPI"]; mask [label="Roles → masking\\n(Isaac)"]; }
  subgraph cluster_app { label="app container · Streamlit"; color="#3a3222"; fontcolor="#d9b36c";
    ui [label="Web app\\npydeck · deck.gl · Altair · DE/EN"]; }
  plug [label="Plugins (Python / R)\\nWirtschaftsingenieure", fillcolor="#1d1a14"];
  user [label="Browser", shape=ellipse];
  arch -> dl [label="HTTPS"]; dl -> parse -> enr -> seg; geo -> enr; enr -> lake [label="atomic write"]; seg -> lake;
  lake -> repo [label="read"]; repo -> mask -> ep; live -> ep [label="fallback chain"];
  ep -> ui [label="HTTP"]; ep -> plug [label="Arrow"]; ui -> user;
}""", width="stretch")
    st.subheader(t(lang, "arch_stack"))
    st.dataframe(pd.DataFrame([
        ["Pipeline", "Dagster", "daily partitioned assets, data checks, UI"],
        ["Download", "httpx", "archive download, live polling"],
        ["Parsing", "orjson · PyArrow", "read JSON traces, columnar tables"],
        ["Storage", "DuckLake (SQLite catalog) · Parquet", "tables with snapshots, atomic writes, one partition per day"],
        ["Query + geo", "DuckDB + spatial", "SQL analytics, point-in-polygon"],
        ["API", "FastAPI · Uvicorn · Pydantic", "plugin interface, OpenAPI docs, JSON + Arrow"],
        ["App", "Streamlit · pydeck · deck.gl · Altair", "UI, maps, charts"],
        ["Operations", "Docker Compose · start.sh · uv", "one-command start, reproducible environment"],
    ], columns=["Layer", "Technology", "Role"]), hide_index=True, width="stretch")
    st.caption(t(lang, "arch_note"))
