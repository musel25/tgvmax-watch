"""Live paid-fare lookup from SNCF Connect's internal search API.

The TGVmax open dataset has no prices. To surface cheap paid options for the
user's priority cities we query SNCF Connect directly. This module is the only
place that talks to a non-open-data SNCF endpoint; it is kept behind a narrow
PriceProvider interface so the transport (plain HTTP vs headless browser) can
change without touching the rest of the pipeline.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Protocol


@dataclass(frozen=True)
class PricedJourney:
    date: date
    train_no: str
    origin: str          # canonical dataset station string (e.g. "NICE VILLE")
    destination: str     # canonical dataset station string
    dep: str             # "HH:MM"
    arr: str             # "HH:MM"
    carrier: str         # "TGV INOUI" | "OUIGO" | "OUIGO TRAIN CLASSIQUE" | "INTERCITES"
    price_eur: float     # cheapest 2nd-class fare in EUR; > 0 (free seats are dropped)


class PriceProvider(Protocol):
    def search(
        self,
        origin: str,
        destination: str,
        day: date,
        window: tuple[str, str],
    ) -> list[PricedJourney]:
        """All journeys origin->destination on `day` departing within `window`,
        each with its cheapest 2nd-class fare. `origin`/`destination` are the
        canonical dataset station strings; the provider maps them to SNCF
        Connect codes internally and tags results with the same strings."""
        ...


def _parse_price_label(label: str) -> float:
    """'32,80 €' / '55 €' (non-breaking space, comma decimal) -> float EUR."""
    cleaned = (
        label
        .replace(" ", "")  # non-breaking space
        .replace(" ", "")       # regular space
        .replace("€", "")
        .strip()
        .replace(",", ".")
    )
    return float(cleaned)


def _proposal_price(prop: dict) -> float | None:
    """Cheapest 2nd-class offer for this proposal, or None if no offer (unavailable)."""
    offers = (prop.get("secondComfortClassOffers") or {}).get("offers") or []
    prices = [_parse_price_label(o["priceLabel"]) for o in offers if o.get("priceLabel")]
    return min(prices) if prices else None


def _carrier(prop: dict) -> str:
    """'Direct OUIGO' -> 'OUIGO', 'Direct TGV INOUI' -> 'TGV INOUI'."""
    desc = (prop.get("transporterDescription") or "").strip()
    return re.sub(r"^Direct\s+", "", desc).strip() or "TGV INOUI"


def parse_journeys(
    payload: dict, origin: str, destination: str, day: date
) -> list[PricedJourney]:
    """Parse a raw SNCF Connect /itineraries response into PricedJourneys.

    Journeys with no purchasable offer (sold out / past) are dropped. `origin`/
    `destination` are the canonical dataset station strings we searched for; we tag
    every result with them (the response uses SNCF Connect's own station names,
    which would not match the routing layer's station map).
    """
    proposals = (
        (payload.get("longDistance") or {}).get("proposals") or {}
    ).get("proposals") or []
    out: list[PricedJourney] = []
    for prop in proposals:
        price = _proposal_price(prop)
        if price is None:
            continue  # unavailable train
        travel_id = prop.get("travelId", "")
        train_no = travel_id.split("_", 1)[1] if "_" in travel_id else ""
        out.append(
            PricedJourney(
                date=day,
                train_no=train_no,
                origin=origin,
                destination=destination,
                dep=(prop.get("departure") or {}).get("timeLabel", ""),
                arr=(prop.get("arrival") or {}).get("timeLabel", ""),
                carrier=_carrier(prop),
                price_eur=price,
            )
        )
    return out
