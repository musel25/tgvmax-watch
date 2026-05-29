"""Live paid-fare lookup from SNCF Connect's internal search API.

The TGVmax open dataset has no prices. To surface cheap paid options for the
user's priority cities we query SNCF Connect directly. This module is the only
place that talks to a non-open-data SNCF endpoint; it is kept behind a narrow
PriceProvider interface so the transport (plain HTTP vs headless browser) can
change without touching the rest of the pipeline.
"""

from __future__ import annotations

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
