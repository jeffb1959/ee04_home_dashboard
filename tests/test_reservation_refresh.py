"""Tests unitaires pour `reservation_refresh.py`."""

from __future__ import annotations

from datetime import date, time, datetime
from pathlib import Path
import sys

import pytest

RACINE_PROJET = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE_PROJET))

from chronogolf_client import ChronogolfIMAPError, ImapConfig

import reservation_cache
import reservation_parser
import reservation_refresh


def _sample_reservation(
    *,
    day: int,
    reservation_id: str,
) -> reservation_parser.GolfReservation:
    return reservation_parser.GolfReservation(
        date=date(2026, 8, day),
        heure=time(8, 57),
        joueurs=["Alice Tremblay", "Bob Martin"],
        reservation_id=reservation_id,
    )


def _build_config() -> ImapConfig:
    return ImapConfig(
        host="imap.test",
        port=993,
        user="user@example.com",
        password="top-secret",
    )


class _FakeClient:
    def __init__(self, reservations: list[reservation_parser.GolfReservation]):
        self.reservations = reservations

    def get_upcoming_reservations(self, *, reference=None, today=None):
        return self.reservations


class _FailingClient:
    def __init__(self, _config: ImapConfig) -> None:
        self.config = _config

    def get_upcoming_reservations(self, *, reference=None, today=None):
        raise ChronogolfIMAPError("Erreur réseau")



def test_refresh_reservation_cache_with_reservations(tmp_path: Path) -> None:
    cache_path = tmp_path / "reservation_cache.json"
    reservation = _sample_reservation(day=18, reservation_id="TEST-1234")
    now = datetime(2026, 8, 14, 22, 30, 0)

    result = reservation_refresh.refresh_reservation_cache(
        now=now,
        cache_path=cache_path,
        client_factory=lambda config: _FakeClient([reservation]),
        config=_build_config(),
    )

    loaded = reservation_cache.load_reservations_cache(cache_path=cache_path)

    assert loaded is not None
    assert result.reservations_count == 1
    assert result.updated_at == now
    assert loaded.reservations[0] == reservation


def test_refresh_reservation_cache_with_no_reservations_writes_empty_cache(tmp_path: Path) -> None:
    cache_path = tmp_path / "reservation_cache.json"
    now = datetime(2026, 8, 14, 8, 0, 0)

    result = reservation_refresh.refresh_reservation_cache(
        now=now,
        cache_path=cache_path,
        client_factory=lambda config: _FakeClient([]),
        config=_build_config(),
    )

    loaded = reservation_cache.load_reservations_cache(cache_path=cache_path)

    assert loaded is not None
    assert result.reservations_count == 0
    assert loaded.reservations == []


def test_refresh_reservation_cache_keeps_existing_cache_on_error(tmp_path: Path) -> None:
    cache_path = tmp_path / "reservation_cache.json"
    reservation_cache.save_reservations_cache(
        [_sample_reservation(day=19, reservation_id="KEEP" )],
        cache_path=cache_path,
    )
    cache_before = cache_path.read_text(encoding="utf-8")

    with pytest.raises(ChronogolfIMAPError):
        reservation_refresh.refresh_reservation_cache(
            now=datetime(2026, 8, 14, 9, 0, 0),
            cache_path=cache_path,
            client_factory=_FailingClient,
            config=_build_config(),
        )

    assert cache_path.read_text(encoding="utf-8") == cache_before


def test_refresh_reservation_cache_without_existing_cache_does_not_create_one_on_error(tmp_path: Path) -> None:
    cache_path = tmp_path / "reservation_cache.json"

    with pytest.raises(ChronogolfIMAPError):
        reservation_refresh.refresh_reservation_cache(
            now=datetime(2026, 8, 14, 9, 0, 0),
            cache_path=cache_path,
            client_factory=_FailingClient,
            config=_build_config(),
        )

    assert not cache_path.exists()
