"""Sélection d'activité à afficher à partir du cache local."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Callable, Literal

from reservation_cache import DEFAULT_CACHE_PATH, ReservationCacheError, load_reservations_cache

ActivityStatus = Literal["today", "upcoming", "none", "unavailable"]


@dataclass(frozen=True)
class ActivityInfo:
    """Informations structurées à afficher à l'écran."""

    status: ActivityStatus
    date: date | None
    heure: time | None
    participants: list[str]
    source_id: str | None = None
    message: str | None = None


def _from_reservation(
    *,
    status: ActivityStatus,
    reservation,
) -> ActivityInfo:
    """Conserve une conversion explicite depuis une réservation d'affichage."""

    return ActivityInfo(
        status=status,
        date=reservation.date,
        heure=reservation.heure,
        participants=list(reservation.joueurs),
        source_id=reservation.reservation_id,
        message=None,
    )


def _empty_for_week() -> ActivityInfo:
    """Retourne un état sans activité pour la semaine courante."""

    return ActivityInfo(
        status="none",
        date=None,
        heure=None,
        participants=[],
        message="Aucun départ cette semaine.",
    )


def _unavailable() -> ActivityInfo:
    """Retourne un état indiquant l'indisponibilité des données."""

    return ActivityInfo(
        status="unavailable",
        date=None,
        heure=None,
        participants=[],
        message="Départs indisponibles.",
    )


def get_display_activity(
    *,
    now: datetime | None = None,
    today: date | None = None,
    cache_path: Path | str = DEFAULT_CACHE_PATH,
    cache_loader: Callable[..., object] = load_reservations_cache,
) -> ActivityInfo:
    """Retourne l'activité à afficher selon les règles métier actuelles."""

    if now is not None:
        current_datetime = now
    elif today is not None:
        current_datetime = datetime.combine(today, time.min)
    else:
        current_datetime = datetime.now()

    current_day = current_datetime.date()
    try:
        cache = cache_loader(cache_path=cache_path)
    except ReservationCacheError:
        return _unavailable()

    if cache is None:
        return _unavailable()

    reservations = cache.reservations

    available_reservations = [
        reservation
        for reservation in reservations
        if current_datetime < datetime.combine(reservation.date, reservation.heure)
        + timedelta(hours=5)
    ]
    if not available_reservations:
        return _empty_for_week()

    reservation = min(available_reservations, key=lambda value: (value.date, value.heure))
    if reservation.date == current_day:
        return _from_reservation(status="today", reservation=reservation)
    return _from_reservation(status="upcoming", reservation=reservation)
