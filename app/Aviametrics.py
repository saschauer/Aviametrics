"""Aviametrics – Streamlit front end. Talks ONLY to the API (never directly to the data)."""
import json
import os
import sys
import time
from datetime import date, timedelta
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
st.set_page_config(page_title="Aviametrics", page_icon="✈", layout="wide")
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


def api(path, method="GET", timeout=90, **kw):
    try:
        r = httpx.request(method, f"{API_URL}{path}", headers={"X-Role": st.session_state.get("role", "visitor")}, timeout=timeout, **kw)
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
lang = st.sidebar.radio("Sprache / Language", list(LANGS), format_func=LANGS.get, horizontal=True,
                        index=list(LANGS).index(CFG["app"]["default_language"]))
role = st.sidebar.radio(t(lang, "role"), ["visitor", "analyst"], format_func=lambda r: t(lang, f"role_{r}"),
                        help=t(lang, "role_help"), key="role")
days = api("/v1/days") or []


@st.dialog(" ", width="large")
def add_data_dialog():
    st.subheader(t(lang, "add_day"))
    st.markdown(t(lang, "workflow"))
    d1, d2 = st.tabs([t(lang, "add_download"), t(lang, "add_folder")])
    with d1:
        mode = st.segmented_control(t(lang, "dl_mode"), ["one", "range"], default="one",
                                    format_func=lambda m: t(lang, "dl_" + m), label_visibility="collapsed")
        if mode == "range":
            rng = st.date_input(t(lang, "date_range"), value=(), max_value=date.today(), format="DD.MM.YYYY")
            rng = tuple(rng) if isinstance(rng, (tuple, list)) else (rng,)
        else:
            one = st.date_input(t(lang, "day"), value=None, max_value=date.today(), format="DD.MM.YYYY")
            rng = (one,) if one else ()
        if (mode == "range" and len(rng) == 2) or (mode != "range" and rng):
            start, end = rng[0], rng[-1]
            n = (end - start).days + 1
            st.caption(t(lang, "download_estimate", n=n, gb=f"{n * 3.3:.1f}"))
            if n > 14:
                st.warning(t(lang, "max_days"))
            elif st.button(t(lang, "start_download"), type="primary"):
                for i in range(n):
                    api(f"/v1/days/{start + timedelta(days=i)}", method="POST")
                st.session_state["toast"] = t(lang, "load_started"); st.rerun()
    with d2:
        def scan_folder(path):
            st.session_state["chosen"] = path
            res = api("/v1/scan_path", params={"path": path})
            st.session_state["found"] = res if res is not None else []
            if res is None:
                st.error(st.session_state.get("api_error", "API error"))

        if st.button(t(lang, "pick_native"), type="primary", width="stretch"):
            r = api("/v1/pick_folder", timeout=620, params={"start": st.session_state.get("chosen", "~")})
            if r and r.get("path"):
                scan_folder(r["path"])
            elif r and r.get("error"):
                st.warning(r["error"] + " – " + t(lang, "pick_fallback"))
        cur = st.session_state.setdefault("browse", "~")
        b = api("/v1/browse", params={"path": cur}) or {"path": "~", "folders": [], "parent": None}
        st.caption(t(lang, "pick_or_browse"))
        nav = st.columns([1, 6, 3], vertical_alignment="center")
        if b.get("parent") is not None and nav[0].button("↑", key="up", help=t(lang, "up")):
            st.session_state["browse"] = b["parent"] or "~"; st.rerun(scope="fragment")
        nav[1].markdown(f"**`{b['path']}`**" + ("  · adsb.lol" if b.get("is_adsblol_day") else ""))
        if nav[2].button(t(lang, "choose_folder"), width="stretch"):
            scan_folder(b["path"])
        sel = st.selectbox(t(lang, "subfolder"), b["folders"], index=None, placeholder=t(lang, "open_subfolder"), key=f"sub_{cur}")
        if sel:
            st.session_state["browse"] = b["path"].rstrip("/") + "/" + sel; st.rerun(scope="fragment")
        with st.expander(t(lang, "folder_path")):
            pth = st.text_input(t(lang, "folder_path"), placeholder="~/aviabench", label_visibility="collapsed")
            if pth and st.button(t(lang, "go"), key="go_path"):
                st.session_state["browse"] = pth; st.rerun(scope="fragment")
        found = st.session_state.get("found")
        if found is not None:
            st.markdown(f"**{t(lang, 'found_in')} `{st.session_state.get('chosen', '')}`**")
            if not found:
                st.info(t(lang, "found_none"))
            importable = [r for r in found if r.get("valid") and r.get("day") and not r.get("loaded")]
            for i, r in enumerate(found):
                c = st.columns([4, 2, 3, 2], vertical_alignment="center")
                if r.get("error"):
                    c[0].error(r["error"]); continue
                c[0].markdown(f"`{r['folder']}`")
                c[1].markdown(f"**{r.get('day') or '?'}**")
                c[2].caption(t(lang, "kind_" + r.get("kind", "extracted")) + " · " + r.get("note", ""))
                if r.get("loaded"):
                    c[3].caption(t(lang, "already"))
                elif not r.get("valid"):
                    c[3].caption(t(lang, "invalid"))
                elif c[3].button(t(lang, "import_btn"), key=f"imp{i}"):
                    api(f"/v1/days/{r['day']}", method="POST", params={"source": r["folder"]})
                    st.session_state["toast"] = t(lang, "load_started"); st.rerun()
            if len(importable) > 1 and st.button(t(lang, "import_all", n=len(importable)), type="primary"):
                for r in importable:
                    api(f"/v1/days/{r['day']}", method="POST", params={"source": r["folder"]})
                st.session_state["toast"] = t(lang, "load_started"); st.rerun()


st.sidebar.markdown("---")
day = st.sidebar.selectbox(t(lang, "day"), days, index=len(days) - 1 if days else None,
                           placeholder=t(lang, "no_days_short")) if days else None
if not days:
    st.sidebar.caption(t(lang, "no_days_short"))
if st.sidebar.button("＋ " + t(lang, "add_day"), width="stretch"):
    add_data_dialog()
if "toast" in st.session_state:
    st.toast(st.session_state.pop("toast"))
st.sidebar.markdown("---")
st.sidebar.caption("Flugdatenanalyse für das BMLV · TGM 2026/27\n\nStefan Aschauer · Isaac Jerryson")
st.sidebar.caption(t(lang, "credits"))

st.markdown('<p class="avia-title">AVIAMETRICS</p>', unsafe_allow_html=True)
st.markdown(f'<p class="avia-tag">{t(lang, "tagline")}</p>', unsafe_allow_html=True)
tabs = st.tabs([t(lang, k) for k in ["tab_live", "tab_time", "tab_numbers", "tab_guess", "tab_plugin", "tab_data", "tab_arch"]])


def need_day():
    st.info(t(lang, "no_days"))
    if st.button("＋ " + t(lang, "add_day"), key=f"nd{time.time_ns()}"):
        add_data_dialog()


# ------------------------------------------------------------------ 1 live radar with Notion-style filters
FILTERS = ["f_alt", "f_speed", "f_type", "f_status", "f_at"]
MAX_CHIPS = 4
DEFAULTS = {"v_alt": (0, 50000), "v_speed": (0, 700), "v_type": [], "v_status": "all"}
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
    if f == "f_status":
        return f"{t(lang, f)} · {t(lang, 'status_' + v['v_status'])}"
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
        opts = sorted(set(st.session_state.get("live_types", [])) | set(st.session_state["v_type"]))
        st.multiselect(t(lang, f), opts, key="v_type", placeholder=t(lang, "all_types"))
        st.caption(t(lang, "types_visible"))
    elif f == "f_status":
        st.segmented_control(t(lang, f), ["all", "air", "ground"], key="v_status",
                             format_func=lambda o: t(lang, "status_" + o), label_visibility="collapsed")
    else:
        st.caption(t(lang, f + "_hint"))
    st.button(t(lang, "remove"), key=f"rm_{f}", on_click=remove_filter, args=(f,))


with tabs[0]:
    active = st.session_state.setdefault("filters", [])
    visible, hidden = active[:MAX_CHIPS], active[MAX_CHIPS:]
    row = st.columns([1.1] + [1.7] * MAX_CHIPS + [0.5, 1.0, 1.0], vertical_alignment="center")   # fixed slots: no re-layout
    view3d = row[0].toggle(t(lang, "view3d"), value=False)
    for c, f in zip(row[1:1 + len(visible)], visible):
        with c.popover(chip_label(f), width="stretch"):
            chip_body(f, active)
    if hidden:
        with row[1 + MAX_CHIPS].popover("…", width="stretch"):
            for f in hidden:
                with st.expander(chip_label(f)):
                    chip_body(f, active)
    with row[2 + MAX_CHIPS].popover("＋ Filter", width="stretch"):
        q = st.text_input(t(lang, "search"), placeholder=t(lang, "search_filters"), label_visibility="collapsed")
        avail = [f for f in FILTERS if f not in active and q.lower() in t(lang, f).lower()]
        for f in avail:
            st.button(t(lang, f), key=f"add_{f}", width="stretch", on_click=add_filter, args=(f,))
        if not avail:
            st.caption("–")
    fvals = {}
    for f in active:
        fvals[f] = {"f_alt": st.session_state["v_alt"], "f_speed": st.session_state["v_speed"],
                    "f_type": st.session_state["v_type"], "f_status": st.session_state["v_status"] or "all"}.get(f, True)
    st.markdown(f"""<div class="legend"><b style="color:#e9e4d8">{t(lang, "legend")}</b>
      <span><span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:#e7c27d;margin-right:5px"></span>{t(lang, "leg_dot")}</span><span style="color:{GOLD}">━ {t(lang, "leg_trail")}</span>
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
        if fvals.get("f_status") == "air":
            df = df[df.alt > 0]
        elif fvals.get("f_status") == "ground":
            df = df[df.alt <= 0]
        if "f_at" in fvals:
            df = df[df.in_at]
        st.session_state["live_types"] = sorted(x for x in df.type.unique() if x and x != "MIL")   # facets: types after the other filters
        if fvals.get("f_type"):
            df = df[df.type.isin(fvals["f_type"])]
        at = df[df.in_at]
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
                layer = pdk.Layer("HexagonLayer", pts, get_position=["lon", "lat"], radius=4000, elevation_scale=25, extruded=True,
                                  coverage=0.85, pickable=True, upper_percentile=99, elevation_upper_percentile=99, lower_percentile=5,
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
                st.markdown(f'<div class="fact">{t(lang, "fact_longest", **f["longest_flight"])}</div>', unsafe_allow_html=True)
            if "busiest_minute" in f:
                mm = (f["busiest_minute"]["utc_minute_of_day"] + 60) % 1440
                st.markdown(f'<div class="fact">{t(lang, "fact_busiest", aircraft=f["busiest_minute"]["aircraft"], time=f"{mm // 60:02d}:{mm % 60:02d}")}</div>', unsafe_allow_html=True)
            if "highest" in f:
                hv = f"{f['highest']['alt_ft']:,}".replace(",", ".")
                st.markdown(f'<div class="fact">{t(lang, "fact_highest", type=f["highest"]["type"], alt=hv)}</div>', unsafe_allow_html=True)

# ------------------------------------------------------------------ 4 quiz with its own live map
with tabs[3]:
    qd = st.session_state.get("quiz_snapshot")
    if qd is None or st.button(t(lang, "quiz_new")):
        live_now = api("/v1/live")
        st.session_state["quiz_snapshot"] = qd = live_now
        st.session_state.pop("quiz_result", None)
    if not qd:
        st.error(t(lang, "no_api"))
    else:
        q = pd.DataFrame(qd["aircraft"])
        q["alt"] = pd.to_numeric(q.alt, errors="coerce").fillna(0).astype(int)
        q["type"] = q.type.fillna("").astype(str)
        at_q = q[q.in_at.astype(bool)] if "in_at" in q else q.iloc[0:0]
        m, qcol = st.columns([3, 2])
        with m:
            qq = at_q.assign(color=at_q.alt.map(alt_color))[["lon", "lat", "color"]]
            deck([pdk.Layer("ScatterplotLayer", qq, get_position=["lon", "lat"], get_fill_color="color", get_radius=2500,
                            radius_min_pixels=4, radius_max_pixels=10)], AT_VIEW, height=520)
            st.caption(t(lang, "quiz_map"))
        real_n = len(at_q)
        types = at_q[(at_q.type != "") & (at_q.type != "MIL")].type.value_counts()
        top = types.index[0] if len(types) else "A320"
        pool = [x for x in ["A320", "B738", "A20N", "A21N", "E195", "DH8D", "A319", "B38M", "CRJ9", "AT76"] if x != top]
        opts_type = sorted([top] + pool[:3])
        hi = int(at_q.alt.max()) if len(at_q) else 0
        hi_band = min(4, hi // 10000)
        bands = ["< 10.000 ft", "10.000–20.000 ft", "20.000–30.000 ft", "30.000–40.000 ft", "> 40.000 ft"]
        with qcol:
            with st.form("quiz"):
                st.markdown(f"**1.** {t(lang, 'quiz_q1')}")
                a1 = st.number_input("q1", 0, 2000, 50, 5, label_visibility="collapsed")
                st.markdown(f"**2.** {t(lang, 'quiz_q2')}")
                a2 = st.radio("q2", opts_type, horizontal=True, label_visibility="collapsed", index=None)
                st.markdown(f"**3.** {t(lang, 'quiz_q3')}")
                a3 = st.radio("q3", bands, label_visibility="collapsed", index=None)
                sent = st.form_submit_button(t(lang, "guess_btn"), type="primary", width="stretch")
            if sent:
                pts1 = 3 if abs(a1 - real_n) <= max(3, real_n * 0.1) else 2 if abs(a1 - real_n) <= real_n * 0.25 else 0
                pts2 = 2 if a2 == top else 0
                pts3 = 2 if a3 == bands[hi_band] else 0
                st.session_state["quiz_result"] = (pts1 + pts2 + pts3, [
                    t(lang, "quiz_a1", real=real_n, you=a1, pts=pts1), t(lang, "quiz_a2", real=top, pts=pts2),
                    t(lang, "quiz_a3", real=f"{hi:,}".replace(",", "."), pts=pts3)])
            res = st.session_state.get("quiz_result")
            if res:
                total, lines = res
                st.markdown(f"### {t(lang, 'quiz_score', pts=total)}")
                for line in lines:
                    st.markdown(f'<div class="fact">{line}</div>', unsafe_allow_html=True)
                if total >= 5:
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
        add_data_dialog()
    st.markdown(f"**{t(lang, 'loaded_days')}:** " + (", ".join(days) if days else "–"))
    if day:
        with st.expander(f"{t(lang, 'quality')} · {day}"):
            @st.cache_data(show_spinner=True)
            def qual(day):
                return api(f"/v1/quality/{day}", timeout=300)
            qd = qual(day)
            if qd:
                c = st.columns(4)
                c[0].metric(t(lang, "positions"), f"{qd['positions']:,}".replace(",", "."))
                c[1].metric(t(lang, "aircraft"), f"{qd['aircraft']:,}".replace(",", "."))
                c[2].metric(t(lang, "q_median"), qd["points_per_aircraft_median"])
                c[3].metric(t(lang, "q_max"), f"{qd['points_per_aircraft_max']:,}".replace(",", "."))
                qdf = pd.DataFrame(qd["checks"]).assign(check=lambda x: x.check.map(lambda k: t(lang, "q_" + k)))
                st.dataframe(qdf.rename(columns={"check": t(lang, "q_check"), "count": t(lang, "q_count"), "pct": "%"}),
                             hide_index=True, width="stretch")
                if qd["stationary"]:
                    st.markdown(f"**{t(lang, 'q_stationary_title')}**")
                    st.dataframe(pd.DataFrame(qd["stationary"]), hide_index=True, width="stretch")
                st.caption(t(lang, "q_note"))
    st.markdown(f"#### {t(lang, 'jobs')}")

    keys = ["attempt", "stage_download", "stage_extract", "stage_parse", "stage_enrich", "stage_write", "stage_flights", "no_jobs",
            "job_done", "queued_hint", "st_running", "st_done", "st_failed", "st_queued"]
    html = (Path(__file__).parent / "pipeline_anim.html").read_text()
    components.html(html.replace("__API__", PUBLIC_API).replace("__LABELS__", json.dumps({k: t(lang, k) for k in keys}, ensure_ascii=False)),
                    height=640, scrolling=True)

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
