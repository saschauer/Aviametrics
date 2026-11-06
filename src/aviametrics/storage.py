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


def _file(table: str, day: str) -> str:
    return str(DATA / table / f"day={day}" / f"{table}.parquet")


def src(table: str, day: str) -> str:
    """SQL fragment that reads one day of a table."""
    if MODE == "ducklake":
        return f"(SELECT * EXCLUDE (day) FROM lake.{table} WHERE day = DATE '{day}')"
    return f"'{_file(table, day)}'"


def _exists(con, table: str) -> bool:
    return con.sql(f"SELECT count(*) FROM duckdb_tables() WHERE database_name = 'lake' AND table_name = '{table}'").fetchone()[0] > 0


def has(con, table: str, day: str) -> bool:
    if MODE == "ducklake":
        return _exists(con, table) and con.sql(f"SELECT count(*) > 0 FROM lake.{table} WHERE day = DATE '{day}'").fetchone()[0]
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
