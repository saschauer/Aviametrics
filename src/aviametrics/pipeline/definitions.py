"""Dagster definitions: one daily partition per day of adsb.lol archive data."""
import dagster as dg

from aviametrics.config import flights_path
from aviametrics.pipeline.core import build_flights, build_positions

daily = dg.DailyPartitionsDefinition(start_date="2025-01-01", end_offset=0)


@dg.asset(partitions_def=daily, group_name="adsblol", description="Austria (+buffer) positions, cleaned and enriched with Bundesland")
def positions(context: dg.AssetExecutionContext) -> dg.MaterializeResult:
    path = build_positions(context.partition_key, log=context.log.info)
    return dg.MaterializeResult(metadata={"path": path})


@dg.asset(partitions_def=daily, group_name="adsblol", deps=[positions], description="Flight segments (gap > 10 min = new flight)")
def flights(context: dg.AssetExecutionContext) -> dg.MaterializeResult:
    return dg.MaterializeResult(metadata={"path": build_flights(context.partition_key)})


@dg.asset_check(asset=flights, description="data quality: flights exist, no segment longer than 24 h, km plausible")
def flights_plausible(context) -> dg.AssetCheckResult:
    import duckdb, glob
    files = glob.glob(str(flights_path("*")))
    if not files:
        return dg.AssetCheckResult(passed=False, metadata={"reason": "no flight files"})
    n, too_long, max_km = duckdb.sql(f"SELECT count(*), count(*) FILTER (WHERE t_end - t_start > 86400), max(km) FROM read_parquet({files})").fetchone()
    return dg.AssetCheckResult(passed=n > 0 and too_long == 0, metadata={"segments": n, "segments_over_24h": too_long, "max_km": float(max_km or 0)})


defs = dg.Definitions(assets=[positions, flights], asset_checks=[flights_plausible])
