"""Tests unitaires pour `activity_service.py`."""

from __future__ import annotations

from datetime import date, datetime, time
from pathlib import Path
import sys

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import reservation_cache
import reservation_parser
import activity_service


def _save_cache(
    cache_path: Path,
    reservations: list[reservation_parser.GolfReservation],
    *,
    updated_at: str | None = None,
) -> None:
    kwargs = {}
    if updated_at is not None:
        kwargs["updated_at"] = datetime.fromisoformat(updated_at)
    reservation_cache.save_reservations_cache(
        reservations,
        cache_path=cache_path,
        **kwargs,
    )


def _reservation(
    *,
    day: int,
    heure: tuple[int, int],
    players: list[str],
    reservation_id: str,
) -> reservation_parser.GolfReservation:
    hour, minute = heure
    return reservation_parser.GolfReservation(
        date=date(2026, 8, day),
        heure=time(hour, minute),
        joueurs=players,
        reservation_id=reservation_id,
    )


def test_today_activity_is_selected(tmp_path: Path) -> None:
    cache_path = tmp_path / "reservation_cache.json"
    _save_cache(
        cache_path,
        [
            _reservation(
                day=18,
                heure=(8, 57),
                players=["Alice Tremblay", "Bob Martin", "Charles Gagnon"],
                reservation_id="TEST-18",
            ),
            _reservation(
                day=19,
                heure=(8, 12),
                players=["Diane Roy"],
                reservation_id="TEST-19",
            ),
        ],
    )

    activity = activity_service.get_display_activity(
        today=date(2026, 8, 18),
        cache_path=cache_path,
    )

    assert activity.status == "today"
    assert activity.date == date(2026, 8, 18)
    assert activity.heure == time(8, 57)
    assert activity.participants == ["Alice Tremblay", "Bob Martin", "Charles Gagnon"]
    assert activity.source_id == "TEST-18"


def test_today_activity_is_kept_even_when_hour_is_passed(tmp_path: Path) -> None:
    cache_path = tmp_path / "reservation_cache.json"
    _save_cache(
        cache_path,
        [
            _reservation(
                day=18,
                heure=(8, 12),
                players=["Alice Tremblay", "Bob Martin"],
                reservation_id="PAST-HOUR",
            )
        ],
    )

    activity = activity_service.get_display_activity(
        today=date(2026, 8, 18),
        cache_path=cache_path,
    )

    assert activity.status == "today"
    assert activity.heure == time(8, 12)


def test_next_reservation_is_selected_when_no_today_booking(tmp_path: Path) -> None:
    cache_path = tmp_path / "reservation_cache.json"
    _save_cache(
        cache_path,
        [
            _reservation(
                day=18,
                heure=(8, 57),
                players=["Alice"],
                reservation_id="R18",
            ),
            _reservation(
                day=20,
                heure=(9, 3),
                players=["Bob"],
                reservation_id="R20",
            ),
        ],
    )

    activity = activity_service.get_display_activity(
        today=date(2026, 8, 17),
        cache_path=cache_path,
    )

    assert activity.status == "upcoming"
    assert activity.date == date(2026, 8, 18)
    assert activity.heure == time(8, 57)


def test_past_reservations_are_ignored(tmp_path: Path) -> None:
    cache_path = tmp_path / "reservation_cache.json"
    _save_cache(
        cache_path,
        [
            _reservation(
                day=18,
                heure=(8, 57),
                players=["Alice"],
                reservation_id="PAST",
            ),
            _reservation(
                day=22,
                heure=(7, 57),
                players=["Bob"],
                reservation_id="FUTURE",
            ),
        ],
    )

    activity = activity_service.get_display_activity(
        today=date(2026, 8, 20),
        cache_path=cache_path,
    )

    assert activity.status == "upcoming"
    assert activity.date == date(2026, 8, 22)


def test_future_reservations_sorted_correctly(tmp_path: Path) -> None:
    cache_path = tmp_path / "reservation_cache.json"
    _save_cache(
        cache_path,
        [
            _reservation(
                day=20,
                heure=(18, 0),
                players=["Bob"],
                reservation_id="R20-18",
            ),
            _reservation(
                day=19,
                heure=(8, 30),
                players=["Alice"],
                reservation_id="R19-8",
            ),
            _reservation(
                day=19,
                heure=(7, 10),
                players=["Charles"],
                reservation_id="R19-7",
            ),
        ],
    )

    activity = activity_service.get_display_activity(
        today=date(2026, 8, 18),
        cache_path=cache_path,
    )

    assert activity.date == date(2026, 8, 19)
    assert activity.heure == time(7, 10)
    assert activity.source_id == "R19-7"


def test_unsorted_cache_is_supported(tmp_path: Path) -> None:
    cache_path = tmp_path / "reservation_cache.json"
    _save_cache(
        cache_path,
        [
            _reservation(
                day=22,
                heure=(7, 10),
                players=["Alice"],
                reservation_id="R22",
            ),
            _reservation(
                day=18,
                heure=(8, 57),
                players=["Bob"],
                reservation_id="R18",
            ),
            _reservation(
                day=19,
                heure=(8, 12),
                players=["Charles"],
                reservation_id="R19",
            ),
        ],
    )

    activity = activity_service.get_display_activity(
        today=date(2026, 8, 17),
        cache_path=cache_path,
    )

    assert activity.date == date(2026, 8, 18)


def test_multiple_today_reservations_select_earliest_hour(tmp_path: Path) -> None:
    cache_path = tmp_path / "reservation_cache.json"
    _save_cache(
        cache_path,
        [
            _reservation(
                day=18,
                heure=(12, 0),
                players=["Bob"],
                reservation_id="LATE",
            ),
            _reservation(
                day=18,
                heure=(8, 15),
                players=["Alice"],
                reservation_id="EARLY",
            ),
            _reservation(
                day=18,
                heure=(10, 5),
                players=["Charles"],
                reservation_id="MIDDLE",
            ),
        ],
    )

    activity = activity_service.get_display_activity(
        today=date(2026, 8, 18),
        cache_path=cache_path,
    )

    assert activity.status == "today"
    assert activity.heure == time(8, 15)
    assert activity.source_id == "EARLY"


def test_no_activity_returns_none_status(tmp_path: Path) -> None:
    cache_path = tmp_path / "reservation_cache.json"
    _save_cache(cache_path, [])

    activity = activity_service.get_display_activity(
        today=date(2026, 8, 18),
        cache_path=cache_path,
    )

    assert activity.status == "none"
    assert activity.date is None
    assert activity.heure is None
    assert activity.participants == []
    assert activity.message == "Aucun départ cette semaine."


def test_only_past_reservations_return_none(tmp_path: Path) -> None:
    cache_path = tmp_path / "reservation_cache.json"
    _save_cache(
        cache_path,
        [
            _reservation(
                day=16,
                heure=(8, 57),
                players=["Alice"],
                reservation_id="OLD",
            )
        ],
    )

    activity = activity_service.get_display_activity(
        today=date(2026, 8, 18),
        cache_path=cache_path,
    )

    assert activity.status == "none"
    assert activity.message == "Aucun départ cette semaine."


def test_unavailable_if_cache_missing(tmp_path: Path) -> None:
    activity = activity_service.get_display_activity(
        today=date(2026, 8, 18),
        cache_path=tmp_path / "reservation_cache.json",
    )

    assert activity.status == "unavailable"
    assert activity.date is None
    assert activity.heure is None
    assert activity.participants == []
    assert activity.message == "Départs indisponibles."


def test_unavailable_if_cache_corrupted(tmp_path: Path) -> None:
    cache_path = tmp_path / "reservation_cache.json"
    cache_path.write_text("{ invalid json }", encoding="utf-8")

    activity = activity_service.get_display_activity(
        today=date(2026, 8, 18),
        cache_path=cache_path,
    )

    assert activity.status == "unavailable"
    assert activity.message == "Départs indisponibles."


def test_participants_are_copied_and_isolated(tmp_path: Path) -> None:
    cache_path = tmp_path / "reservation_cache.json"
    players = ["Alice", "Bob"]
    reservation = _reservation(
        day=18,
        heure=(9, 0),
        players=players,
        reservation_id="R18",
    )
    _save_cache(cache_path, [reservation])

    activity = activity_service.get_display_activity(
        today=date(2026, 8, 18),
        cache_path=cache_path,
    )

    activity.participants.append("CHANGED")
    assert reservation.joueurs == ["Alice", "Bob"]
    assert activity.status == "today"


def test_source_id_reuses_reservation_id(tmp_path: Path) -> None:
    cache_path = tmp_path / "reservation_cache.json"
    _save_cache(
        cache_path,
        [
            _reservation(
                day=18,
                heure=(9, 0),
                players=["Alice"],
                reservation_id="R-18-ID",
            )
        ],
    )

    activity = activity_service.get_display_activity(
        today=date(2026, 8, 18),
        cache_path=cache_path,
    )

    assert activity.source_id == "R-18-ID"


def test_no_imap_or_chronogolf_is_called(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import chronogolf_client

    def _failing_factory(*args, **kwargs):  # pragma: no cover
        raise AssertionError("Chronogolf should not be called")

    monkeypatch.setattr(chronogolf_client, "ChronogolfClient", _failing_factory)
    monkeypatch.setattr(chronogolf_client, "load_imap_config", _failing_factory)

    cache_path = tmp_path / "reservation_cache.json"
    _save_cache(
        cache_path,
        [
            _reservation(
                day=18,
                heure=(8, 10),
                players=["Alice"],
                reservation_id="R18",
            )
        ],
    )

    activity = activity_service.get_display_activity(
        today=date(2026, 8, 18),
        cache_path=cache_path,
    )

    assert activity.status == "today"


def test_types_date_and_time_are_preserved(tmp_path: Path) -> None:
    cache_path = tmp_path / "reservation_cache.json"
    reservation = _reservation(
        day=18,
        heure=(8, 10),
        players=["Alice"],
        reservation_id="R18",
    )
    _save_cache(cache_path, [reservation])

    activity = activity_service.get_display_activity(
        today=date(2026, 8, 18),
        cache_path=cache_path,
    )

    assert isinstance(activity.date, date)
    assert isinstance(activity.heure, time)


def test_specific_fallback_upcoming_and_today_scenarios(tmp_path: Path) -> None:
    cache_path = tmp_path / "reservation_cache.json"
    reservations = [
        _reservation(
            day=18,
            heure=(8, 57),
            players=["Alice", "Bob", "Charles"],
            reservation_id="R-18",
        ),
        _reservation(
            day=19,
            heure=(8, 12),
            players=["Diane", "Eve", "Françoise"],
            reservation_id="R-19",
        ),
    ]
    _save_cache(cache_path, reservations)

    first = activity_service.get_display_activity(
        today=date(2026, 8, 17),
        cache_path=cache_path,
    )
    second = activity_service.get_display_activity(
        today=date(2026, 8, 18),
        cache_path=cache_path,
    )

    assert first.status == "upcoming"
    assert first.date == date(2026, 8, 18)
    assert first.heure == time(8, 57)

    assert second.status == "today"
    assert second.date == date(2026, 8, 18)
    assert second.heure == time(8, 57)
