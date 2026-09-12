Prompt: 
Give me everything i need to know about gods eye view, how it was made etc so that i know if that is relevant for my diploma thesis as my partner and i need to analyse flight for the bmlv in austria (so its not really defined but basically we just need to use open source data and make analysis on that and we have two additional teammates from the department of wirtschaftsingenieure, we are from an htl tgm in vienna last year for matura) were still discussing the tech stack and researching what already exists, and as i said we found gods eye view and there is also cirium or oag, were still trying to find out what makes us unique, so the usp, and also we wanna compete in many competitions centered around diplomarbeiten for htl and try to incorporate features for that, like also sustainability and whatever and future

we just dont know where to start, first give me an overview over the market a detailed one using the newest sources online, then give me a unique selling point for my project and then give me options for my tech stack and what is realistic for a diploma thesis

Answer:
Good news first: God's Eye View is **not** a competitor to what you're doing. It's a display, not an analysis tool. That distinction is going to be the backbone of your whole thesis positioning, so let me go through it properly.

## 1. God's Eye View — what it actually is

Built by Bilawal Sidhu (the same person behind a YouTube series with millions of views, earlier called WorldView), open-sourced in August 2026 under MIT. It reached #1 on GitHub Trending in August 2026, and the repo has 24.4k stars.

**How it was made:** Vanilla JavaScript, CesiumJS and Vite — no React, no framework. The browser holds the Cesium globe and all rendering; a server-side proxy brokers every private API key. The `data/` directory has one module per layer (flights, vessels, satellites, earthquakes, CCTV, traffic, fires, radio, etc.), so new layers follow the same pattern. Voice control runs on the OpenAI Realtime API with 28 tools across four jobs (direct, annotate, identify, frame).

**Where its flight data comes from** — this matters for you: live flights are 11,000+ aircraft from the OpenSky Network, with adsb.lol as a bounded fallback; the military layer is ADS-B military traffic from adsb.lol. Live feeds arrive every 15–30 seconds, the globe renders one interval behind real time and interpolates between known fixes, with dead reckoning filling gaps.

**Why it's not your competitor:** it has no history, no statistics, no hypothesis testing, no reproducibility. It answers "what is flying right now" beautifully and "what happened over Austria last March, and was that normal" not at all. Even its own comparison writeups frame it as the choice when you want flight data as one layer in a broader situational picture, versus a managed API when you need guaranteed data quality and historical playback. It's also explicitly scoped away from tracking individuals — it models events, assets and infrastructure, and rejects pull requests for named-person search or face recognition. Mirror that boundary in your own scope; it makes for a clean ethics chapter.

**Use it as:** your *Stand der Technik* reference, your visual benchmark, and (MIT licence) a legitimate source of frontend patterns if you want a globe for the final presentation.

## 2. Market overview

Think of it as five tiers, not one market.

**Tier 1 — Commercial data & analytics (the money).** The aviation analytics market was around USD 2.58 bn in 2024, projected to roughly USD 7.45 bn by 2032. Cirium is the largest player — part of LexisNexis Risk Solutions, ~404 employees as of April 2026, generating about 2.35× OAG's revenue, against OAG's ~300 employees. Cirium covers schedules, routes, connections, passenger traffic, flight status for 99%+ of commercial flights, 770+ aircraft types with 300+ data points each, plus historical data including seats, fares and CO₂ — priced from around $2.50 per 1k records. OAG remains the schedule-data specialist for route planning and market analysis; FlightAware and Cirium dominate enterprise operational visibility; Aviationstack and similar sit at the cheap-and-easy end. ADS-B Exchange, once the community outlier, was acquired by JETNET and now sells subscription products with positions delivered every 250 ms.

**Tier 2 — Institutional open data (your real opportunity).** EUROCONTROL's Aviation Data Repository for Research: 28 million flights as of July 2026, ~3 million flights/year, 2015–2024, but only 4 months of data per year — and with a two-year delay and lower sampling rates, which makes it better for cross-referencing than for high-resolution trajectory work. Far more interesting for you is **OPDI** (Open Performance Data Initiative), run by EUROCONTROL's Performance Review Commission with the OpenSky Network: coverage January 2022 – July 2026, downloadable as Parquet files in 10-day intervals with a predictable URL pattern you can script. The datasets comprise a flight list, flight events per flight, measurements associated with each event, and a 5-second state-vector representation of the trajectory. The explicit goal is to remove the repetitive data-collection work so university groups can focus on analysis. No application, no approval, no cost.

**Tier 3 — Community ADS-B.** OpenSky Network (Swiss non-profit) is the academic backbone: free access to the full dataset via an SQL-like Trino/MinIO interface, available to university-affiliated researchers, governmental organisations and aviation authorities. Two catches: OpenSky now exclusively supports OAuth2 client credentials — basic auth is gone, and bulk full-day extraction is explicitly described as not for general student work. **Your BMLV connection is the lever here** — they are a governmental organisation. Get a letter from them and apply early; approval is not automatic. Alongside: adsb.lol (fully open-source, ODbL-licensed data, free API and free historical data), airplanes.live/ADSB One, adsb.fi, TheAirTraffic, and live-military-mode-s.eu which focuses specifically on military aircraft.

**Tier 4 — Open-source analysis tooling (this is mature, use it).** `pyopensky` and the `traffic` library are the recommended tools for most Trino users, providing high-level trajectory extraction and flight filtering without raw SQL. `pyModeS` decodes Mode-S/ADS-B. `OpenAP` from TU Delft is the big one for your sustainability angle: a fully open-source aircraft performance and emission model covering kinematics, thrust, drag and fuel flow, built entirely on open data, with engine data primarily from the ICAO emissions databank. Also `pycontrails`, `CLIMaCCF`, `fastmeteo`, and EUROCONTROL's own pip-installable OPDI package that transforms raw ADS-B state vectors into enriched flight datasets with H3 geospatial indexing, event detection and data-quality monitoring.

**Tier 5 — OSINT visualisation.** God's Eye View, GPSJam, SkAI's spoofing tracker. SkAI Data Services with Zurich University of Applied Sciences built real-time GPS spoofing detection from OpenSky ADS-B data; GPSJam does the same using ADS-B Exchange.

**The gap:** the data is free, the tooling is free, the visualisation is solved. What nobody has done is a **defence-framed, Austria-specific, reproducible analysis** of that data. That's your slot.

## 3. Your USP

My recommendation — and it's one idea with a sustainability limb that grows out of it rather than being glued on:

> **An open-data airspace integrity monitor for Austrian and Central European airspace: detecting, quantifying and costing anomalies that a display-only tool cannot see.**

Four analysis pillars, all from the same pipeline:

**a) GNSS interference detection over Austria and its neighbours.** ADS-B messages carry quality indicators (NIC, NACp, SIL). Degradation across many aircraft in the same area is the standard open-data signature of jamming. This is live geopolitics: GNSS RFI incidents have increased significantly and expose the vulnerability of European airspace, particularly in Central Europe and the Baltics, while most authorities still rely on pilot reports with reporting rates as low as 5–15%, and ground-based sensors that can't observe interference in the airspace. Existing tools do this globally with one coarse metric. You'd do it for one airspace with a documented, validated methodology.

**b) Transponder anomaly and "dark flight" analysis.** Dropouts, implausible position jumps, emergency squawks, callsign/registration inconsistencies, coverage gaps. This is exactly the ambiguity the Product Hunt commenters raised about God's Eye View — ADS-B and AIS are self-reported, so the globe shows whatever agreed to be seen that minute. Turning that weakness into your measured subject is a genuinely good research move.

**c) Military and state aircraft baseline over Austria.** What is normal, seasonally and by corridor? Austria's neutrality context makes this substantive rather than a gimmick: the Verband Luftraumüberwachung monitors Austrian airspace around the clock, and 30 to 50 times a year the air force flies "Priorität Alpha" intercepts. Frame your work as an open-source complement to the classified picture — Goldhaube integrates fixed radar with civil and international radar data, and your contribution is the question *how much of that picture is reconstructable from purely open sources, and where does open data fail?*

**d) Sustainability, derived not bolted on.** Run OpenAP over the actual trajectories to get per-flight fuel and CO₂, then measure *inefficiency*: holding patterns, level-offs during climb, non-direct routing, taxi time at LOWW. Then close the loop — quantify the extra fuel burn caused by the disruptions you detected in (a) and (b). That gives you a sustainability chapter that couldn't exist without the rest of the thesis, which is exactly what competition juries reward over a tacked-on "and it's green too" section.

**Why this is defensible as a USP:** Cirium and OAG sell schedules and status to airlines — they don't do airspace integrity, and they'd never publish methodology. God's Eye View displays but doesn't measure. GPSJam does one metric globally with no Austrian focus and no economic layer. Academic papers exist but aren't reproducible artefacts with an interface. Your combination — *one airspace, defence-framed, fully open licences, published methodology, downloadable derived dataset, economic costing* — genuinely doesn't exist.

**Your two Wirtschaftsingenieure get real work,** which is important: economic exposure of the Austrian air-traffic network, cost-of-disruption modelling, a make-vs-buy analysis (what would Cirium charge for the equivalent, versus your open pipeline — that's a killer slide), and the sustainability quantification.

**Two fallbacks** if BMLV steers you elsewhere:
- **Resilience/scenario modelling:** graph analysis of the Central European route network — if LOWW or a corridor closes, what reroutes where, at what fuel and delay cost. Even more Wirtschaftsingenieur-friendly.
- **ADS-B coverage atlas for Austria:** where does open ADS-B reception actually fail? Alpine terrain shadowing, low-altitude blind spots, MLAT vs ADS-B comparison. Cheap, novel, and directly useful to a defence customer who needs to know the limits of open sources.

## 4. Tech stack

**Option A — recommended. Boring, finishable, defensible.**

| Layer | Choice |
|---|---|
| Language | Python 3.12+ |
| Storage | Parquet files + DuckDB (no database server to maintain) |
| Processing | Polars or pandas; `traffic`, `pyopensky`, `pyModeS` |
| Domain models | OpenAP (fuel/emissions), optionally fastmeteo for weather |
| Backend | FastAPI |
| Frontend | React + MapLibre GL, or deck.gl for trajectory volume |
| Charts | Plotly or ECharts |
| Infra | Docker Compose, GitHub with CI, everything reproducible from a `make` target |

DuckDB over Parquet is the single most important call here. It handles tens of millions of rows on a laptop, needs no server, and makes your entire pipeline reproducible by a jury member in one command. That reproducibility *is* half your USP.

**Option B — the demo layer, optional.** A thin CesiumJS globe for the Präsentation and the competition video, reusing patterns from God's Eye View (MIT licence permits this, cite it properly). Build it last, timebox it to two weeks, and only if the analysis is already done. A wow-factor frontend on a thin analysis is the classic way HTL projects lose competitions to less flashy but deeper work.

**Option C — one hardware component worth having.** An RTL-SDR dongle (~€40) plus antenna, running readsb, feeding your own receiver. It costs almost nothing, gives you a physical artefact for the competition stand, lets you write an honest chapter on the physical layer and reception limits, and earns you feeder status with adsb.lol. Genuinely good value per hour spent.

**What to cut ruthlessly:** Kafka, Spark, Airflow, Kubernetes, microservices, your own ML model trained from scratch, real-time streaming. None of these survive contact with a school-year deadline, and none of them impress a jury that's looking for depth of analysis. If you need orchestration, a Makefile and a cron job are fine and you can defend that choice as engineering judgement.

**Team split (4 people):** you and your HTL partner own the data pipeline and the application; the Wirtschaftsingenieure own market analysis, cost modelling, sustainability quantification and the business case. Give them their own chapter and their own deliverable — joint HTL/Wirtschaftsingenieur theses fail when the non-technical half becomes a passenger.

## 5. Where to start — the next three weeks

1. **Clarify the assignment in writing with BMLV.** One page: question, deliverable, data sources, and critically — *what may be published*. A defence-adjacent thesis that turns out to be non-publishable can't enter a single competition. Settle this in week one, not month five.
2. **Apply for OpenSky Trino access immediately**, with BMLV backing as a governmental organisation. Lead time is weeks, and it's not auto-approved.
3. **Meanwhile, download one month of OPDI Parquet** and get a notebook running end to end on Austrian airspace. No approval needed, so your project can't be blocked. If you can't produce an interesting plot from one month of OPDI data in two weeks, your scope is wrong — find that out now.
4. **Then pick the USP** based on what the data actually supports, not what sounds good in a proposal.

## 6. Competitions — calendar reality

Jugend Innovativ's next round opens in October with a submission deadline of 30 November 2026 — that's about eleven weeks away, and you register the *project*, not the finished work. The project report follows at the end of January, and that report is what the jury uses to decide who reaches the Bundesfinale; total prize money is €52,500. Categories are Design, Engineering, Science, Entrepreneurship, ICT & Digital, and Sustainability — you could plausibly enter ICT & Digital or Sustainability, and the choice should be deliberate.

The Bosch Innovationspreis is HTL-only: registration by early January, full submission by 10 April, teams of up to 6, and it requires a max-3-minute film about the project. Shoot footage as you go — reconstructing it in April is miserable. TÜV Austria also awards innovative, creative and sustainable projects by HTL graduates, and the Dr. Hans Riegel Fachpreise run regionally in Austria with spring deadlines (Vienna and Lower Austria around 30 April).

Register for Jugend Innovativ in October even though nothing is finished. The deadline will force your scope to be concrete by November, which is exactly the discipline a four-person thesis needs.
