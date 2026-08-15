"""Rafraîchissement du cache Chronogolf centralisé."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from chronogolf_client import (
    ChronogolfClient,
    ImapConfig,
    ENV_FILE,
    load_imap_config,
)
from reservation_cache import DEFAULT_CACHE_PATH, save_reservations_cache

from dotenv import load_dotenv


@dataclass(frozen=True)
class ReservationRefreshResult:
    """Résultat d'un rafraîchissement de cache Chronogolf."""

    reservations_count: int
    updated_at: datetime


def refresh_reservation_cache(
    *,
    now: datetime | None = None,
    cache_path: Path | str = DEFAULT_CACHE_PATH,
    client_factory=ChronogolfClient,
    config: ImapConfig | None = None,
) -> ReservationRefreshResult:
    """Rafraîchit le cache Chronogolf et retourne un résultat structuré."""

    now = now or datetime.now()
    if config is None:
        load_dotenv(ENV_FILE)
        config = load_imap_config()

    client = client_factory(config)
    reservations = client.get_upcoming_reservations(reference=now, today=now.date())

    cache = save_reservations_cache(
        reservations,
        updated_at=now,
        cache_path=cache_path,
    )

    return ReservationRefreshResult(
        reservations_count=len(cache.reservations),
        updated_at=cache.updated_at,
    )
