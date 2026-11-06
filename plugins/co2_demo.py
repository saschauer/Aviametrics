"""Demo plugin: CO2 estimate per aircraft type – runs as an EXTERNAL client of the Aviametrics API.

Plugin contract (showcase): fetch data via HTTP (Arrow IPC), compute, return a table.
The CO2 factors below are ILLUSTRATIVE, not validated – the real plugin of the Wirtschaftsingenieure
uses a validated emission model (e.g. OpenAP).
"""
import httpx
import pandas as pd
import pyarrow as pa

KG_CO2_PER_KM = {"A20N": 8, "A21N": 10, "A319": 9, "A320": 9, "A321": 11, "B737": 9, "B738": 9, "B38M": 8,
                 "B39M": 9, "E190": 7, "E195": 7, "E290": 6, "E295": 6, "DH8D": 4, "AT76": 3, "AT75": 3,
                 "CRJ9": 6, "B789": 19, "B788": 18, "B77W": 25, "A359": 20, "A333": 21, "B763": 18, "A388": 34}


def run(api_url: str, day: str, role: str = "visitor") -> pd.DataFrame:
    r = httpx.get(f"{api_url}/v1/flights/{day}", params={"fmt": "arrow"}, headers={"X-Role": role}, timeout=120)
    r.raise_for_status()
    flights = pa.ipc.open_stream(r.content).read_all().to_pandas()
    df = flights.groupby("type", as_index=False).agg(flights=("icao", "count"), km=("km", "sum"))
    df["kg_co2_per_km"] = df["type"].map(KG_CO2_PER_KM)
    df = df.dropna(subset=["kg_co2_per_km"])
    df["t_co2"] = (df.km * df.kg_co2_per_km / 1000).round(1)
    return df.sort_values("t_co2", ascending=False)


if __name__ == "__main__":
    import sys
    print(run(sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000", sys.argv[2] if len(sys.argv) > 2 else "2026-11-03"))
