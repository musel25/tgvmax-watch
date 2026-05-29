"""SNCF TGVmax open-data API client.

Dataset: https://ressources.data.sncf.com/explore/dataset/tgvmax/
We pull all trains where `od_happy_card == "OUI"` (Max Jeune seat available)
inside a date range, with origin or destination matching a Paris-area station.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date

import httpx

API = "https://ressources.data.sncf.com/api/explore/v2.1/catalog/datasets/tgvmax/records"
PAGE_LIMIT = 100  # API hard cap


@dataclass(frozen=True)
class Train:
    date: date
    train_no: str
    origin: str
    destination: str
    dep: str  # "HH:MM"
    arr: str
    entity: str
    axe: str
    price_eur: float | None = None  # None = free Max Jeune seat; float = paid fare (EUR)

    @classmethod
    def from_record(cls, r: dict) -> "Train":
        return cls(
            date=date.fromisoformat(r["date"]),
            train_no=r["train_no"],
            origin=r["origine"],
            destination=r["destination"],
            dep=r["heure_depart"],
            arr=r["heure_arrivee"],
            entity=r.get("entity", ""),
            axe=r.get("axe", ""),
        )


def _quote(s: str) -> str:
    return '"' + s.replace('"', '\\"') + '"'


def _in_clause(field: str, values: list[str]) -> str:
    return f"{field} in ({', '.join(_quote(v) for v in values)})"


def fetch_oui(
    origins: list[str],
    destinations: list[str],
    start: date,
    end: date,
    client: httpx.Client | None = None,
) -> list[Train]:
    """All TGVmax-eligible trains from any origin to any destination, within [start, end]."""
    where = " AND ".join([
        'od_happy_card="OUI"',
        _in_clause("origine", origins),
        _in_clause("destination", destinations),
        f"date>=date'{start.isoformat()}'",
        f"date<=date'{end.isoformat()}'",
    ])
    owned = client is None
    client = client or httpx.Client(timeout=30.0)
    try:
        out: list[Train] = []
        offset = 0
        while True:
            for attempt in range(4):
                try:
                    r = client.get(
                        API,
                        params={
                            "where": where,
                            "limit": PAGE_LIMIT,
                            "offset": offset,
                            "order_by": "date,heure_depart",
                        },
                    )
                    r.raise_for_status()
                    break
                except httpx.HTTPError:
                    if attempt == 3:
                        raise
                    time.sleep(1.5 * (attempt + 1))
            data = r.json()
            results = data.get("results", [])
            out.extend(Train.from_record(x) for x in results)
            if len(results) < PAGE_LIMIT:
                break
            offset += PAGE_LIMIT
            if offset > 10_000:  # safety
                break
        return out
    finally:
        if owned:
            client.close()


def dataset_date_range(client: httpx.Client | None = None) -> tuple[date, date]:
    """Inspect the dataset for its current min/max date — useful sanity check."""
    owned = client is None
    client = client or httpx.Client(timeout=30.0)
    try:
        lo = client.get(API, params={"limit": 1, "order_by": "date asc"}).json()
        hi = client.get(API, params={"limit": 1, "order_by": "date desc"}).json()
        return (
            date.fromisoformat(lo["results"][0]["date"]),
            date.fromisoformat(hi["results"][0]["date"]),
        )
    finally:
        if owned:
            client.close()
