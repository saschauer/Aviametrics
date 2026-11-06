"""Table layer: the only module that knows HOW tables are stored.

ducklake : DuckLake table format – metadata catalog in SQLite, data as Parquet files partitioned by day,
           snapshots and atomic (transactional) writes.
parquet  : plain Hive-style day folders (data/positions/day=YYYY-MM-DD/positions.parquet).
Switch in config/default.toml → [storage] table_layer.
"""
import duckdb

from aviametrics.config import CFG, DATA

MODE = CFG.get("storage", {}).get("table_layer", "parquet")
LAKE = DATA / "lake"
CATALOG = LAKE / "catalog.sqlite"


def connect() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    if MODE == "ducklake":
        LAKE.mkdir(parents=True, exist_ok=True)
        con.sql("INSTALL ducklake; LOAD ducklake; INSTALL sqlite; LOAD sqlite")
        con.sql(f"ATTACH 'ducklake:sqlite:{CATALOG}' AS lake (DATA_PATH '{LAKE}/')")
    return con


def one(con, sql: str):
    """First row of a query, reading the result completely (DuckDB 2.0 forbids leaving results unfinished)."""
    rows = con.execute(sql).fetchall()
    return rows[0] if rows else None


def _file(table: str, day: str) -> str:
    return str(DATA / table / f"day={day}" / f"{table}.parquet")


def src(table: str, day: str) -> str:
    """SQL fragment that reads one day of a table."""
    if MODE == "ducklake":
        return f"(SELECT * EXCLUDE (day) FROM lake.{table} WHERE day = DATE '{day}')"
    return f"'{_file(table, day)}'"


def _exists(con, table: str) -> bool:
    return one(con, f"SELECT count(*) FROM duckdb_tables() WHERE database_name = 'lake' AND table_name = '{table}'")[0] > 0


def has(con, table: str, day: str) -> bool:
    if MODE == "ducklake":
        return _exists(con, table) and one(con, f"SELECT count(*) > 0 FROM lake.{table} WHERE day = DATE '{day}'")[0]
    import os
    return os.path.exists(_file(table, day))


def days(con) -> list[str]:
    if MODE == "ducklake":
        if not _exists(con, "positions"):
            return []
        return [str(r[0]) for r in con.sql("SELECT DISTINCT day FROM lake.positions ORDER BY 1").fetchall()]
    return sorted(p.parent.name.removeprefix("day=") for p in (DATA / "positions").glob("day=*/positions.parquet"))


def write(con, table: str, day: str, select_sql: str) -> str:
    """Replace one day of `table` with the result of `select_sql` – atomically in DuckLake."""
    if MODE == "ducklake":
        if not _exists(con, table):
            con.sql(f"CREATE TABLE lake.{table} AS SELECT *, DATE '{day}' AS day FROM ({select_sql}) LIMIT 0")
            con.sql(f"ALTER TABLE lake.{table} SET PARTITIONED BY (day)")
        con.sql("BEGIN TRANSACTION")
        con.sql(f"DELETE FROM lake.{table} WHERE day = DATE '{day}'")
        con.sql(f"INSERT INTO lake.{table} SELECT *, DATE '{day}' AS day FROM ({select_sql})")
        con.sql("COMMIT")
        return f"lake.{table} (day={day})"
    import os
    f = _file(table, day)
    os.makedirs(os.path.dirname(f), exist_ok=True)
    con.sql(f"COPY ({select_sql}) TO '{f}' (FORMAT parquet, COMPRESSION zstd)")
    return f


# ------------------------------------------------------------------ result conversion (stable across DuckDB 1.x / 2.x)
def to_arrow(rel):
    import pyarrow as pa
    for m in ("to_arrow_table", "fetch_arrow_table", "arrow"):
        if hasattr(rel, m):
            r = getattr(rel, m)()
            return r.read_all() if isinstance(r, pa.RecordBatchReader) else r
    raise RuntimeError("no Arrow conversion available")


def to_records(rel) -> list[dict]:
    cols = [c[0] for c in rel.description] if getattr(rel, "description", None) else rel.columns
    return [dict(zip(cols, row)) for row in rel.fetchall()]
