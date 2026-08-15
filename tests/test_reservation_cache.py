"""Tests unitaires pour `reservation_cache.py`."""

from __future__ import annotations

from datetime import date, time, datetime
from pathlib import Path
import json
import os
import sys

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import reservation_cache
import reservation_parser


def _sample_reservation(
    *,
    day: int,
    reservation_id: str,
) -> reservation_parser.GolfReservation:
    return reservation_parser.GolfReservation(
        date=date(2026, 8, day),
        heure=time(8, 57),
        joueurs=["Alice Tremblay", "Bob Martin", "Charles Gagnon"],
        reservation_id=reservation_id,
    )


def test_save_and_load_single_reservation(tmp_path: Path) -> None:
    cache_path = tmp_path / "data" / "reservation_cache.json"
    reservation = _sample_reservation(day=18, reservation_id="TEST-1234")

    reservation_cache.save_reservations_cache([reservation], cache_path=cache_path)
    loaded = reservation_cache.load_reservations_cache(cache_path=cache_path)

    assert loaded is not None
    assert len(loaded.reservations) == 1
    assert loaded.reservations[0] == reservation


def test_load_cache_rebuilds_date_and_time_types(tmp_path: Path) -> None:
    cache_path = tmp_path / "reservation_cache.json"
    reservation = _sample_reservation(day=19, reservation_id="TEST-5678")

    reservation_cache.save_reservations_cache([reservation], cache_path=cache_path)
    loaded = reservation_cache.load_reservations_cache(cache_path=cache_path)

    assert loaded is not None
    assert isinstance(loaded.reservations[0].date, date)
    assert isinstance(loaded.reservations[0].heure, time)


def test_reservation_date_is_preserved(tmp_path: Path) -> None:
    cache_path = tmp_path / "reservation_cache.json"
    reservation = _sample_reservation(day=20, reservation_id="TEST-20")

    reservation_cache.save_reservations_cache([reservation], cache_path=cache_path)
    loaded = reservation_cache.load_reservations_cache(cache_path=cache_path)

    assert loaded is not None
    assert loaded.reservations[0].date == date(2026, 8, 20)


def test_reservation_time_is_preserved(tmp_path: Path) -> None:
    cache_path = tmp_path / "reservation_cache.json"
    reservation = _sample_reservation(day=21, reservation_id="TEST-21")

    reservation_cache.save_reservations_cache([reservation], cache_path=cache_path)
    loaded = reservation_cache.load_reservations_cache(cache_path=cache_path)

    assert loaded is not None
    assert loaded.reservations[0].heure == time(8, 57)


def test_reservation_players_are_preserved(tmp_path: Path) -> None:
    cache_path = tmp_path / "reservation_cache.json"
    reservation = _sample_reservation(day=22, reservation_id="TEST-22")

    reservation_cache.save_reservations_cache([reservation], cache_path=cache_path)
    loaded = reservation_cache.load_reservations_cache(cache_path=cache_path)

    assert loaded is not None
    assert loaded.reservations[0].joueurs == [
        "Alice Tremblay",
        "Bob Martin",
        "Charles Gagnon",
    ]


def test_reservation_id_is_preserved(tmp_path: Path) -> None:
    cache_path = tmp_path / "reservation_cache.json"
    reservation = _sample_reservation(day=23, reservation_id="RES-ID-99")

    reservation_cache.save_reservations_cache([reservation], cache_path=cache_path)
    loaded = reservation_cache.load_reservations_cache(cache_path=cache_path)

    assert loaded is not None
    assert loaded.reservations[0].reservation_id == "RES-ID-99"


def test_multiple_reservations_are_saved_and_loaded(tmp_path: Path) -> None:
    cache_path = tmp_path / "reservation_cache.json"
    reservations = [
        _sample_reservation(day=17, reservation_id="R1"),
        _sample_reservation(day=18, reservation_id="R2"),
    ]

    reservation_cache.save_reservations_cache(
        reservations,
        updated_at=datetime(2026, 8, 14, 12, 0, 0),
        cache_path=cache_path,
    )
    loaded = reservation_cache.load_reservations_cache(cache_path=cache_path)

    assert loaded is not None
    assert len(loaded.reservations) == 2
    assert [r.reservation_id for r in loaded.reservations] == ["R1", "R2"]


def test_empty_reservations_list_is_valid(tmp_path: Path) -> None:
    cache_path = tmp_path / "reservation_cache.json"

    reservation_cache.save_reservations_cache(
        [],
        updated_at=datetime(2026, 8, 14, 18, 0, 0),
        cache_path=cache_path,
    )
    loaded = reservation_cache.load_reservations_cache(cache_path=cache_path)

    assert loaded is not None
    assert loaded.reservations == []


def test_updated_at_is_stored(tmp_path: Path) -> None:
    cache_path = tmp_path / "reservation_cache.json"
    updated_at = datetime(2026, 8, 14, 20, 15, 0)

    reservation_cache.save_reservations_cache(
        [_sample_reservation(day=24, reservation_id="R4")],
        updated_at=updated_at,
        cache_path=cache_path,
    )
    loaded = reservation_cache.load_reservations_cache(cache_path=cache_path)

    assert loaded is not None
    assert loaded.updated_at == updated_at


def test_data_directory_is_created_automatically(tmp_path: Path) -> None:
    cache_path = tmp_path / "data" / "reservation_cache.json"
    assert not cache_path.parent.exists()

    reservation_cache.save_reservations_cache(
        [_sample_reservation(day=25, reservation_id="R5")],
        cache_path=cache_path,
    )

    assert cache_path.parent.is_dir()


def test_load_missing_cache_returns_none(tmp_path: Path) -> None:
    result = reservation_cache.load_reservations_cache(
        cache_path=tmp_path / "reservation_cache.json"
    )
    assert result is None


def test_corrupted_json_raises_cache_error(tmp_path: Path) -> None:
    cache_path = tmp_path / "reservation_cache.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text("{ invalid json }", encoding="utf-8")

    with pytest.raises(reservation_cache.ReservationCacheError):
        reservation_cache.load_reservations_cache(cache_path=cache_path)


def test_unknown_version_raises_cache_error(tmp_path: Path) -> None:
    cache_path = tmp_path / "reservation_cache.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(
            {
                "version": 99,
                "updated_at": "2026-08-14T20:15:00",
                "reservations": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(reservation_cache.ReservationCacheError):
        reservation_cache.load_reservations_cache(cache_path=cache_path)


def test_invalid_reservation_payload_raises_cache_error(tmp_path: Path) -> None:
    cache_path = tmp_path / "reservation_cache.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(
            {
                "version": 1,
                "updated_at": "2026-08-14T20:15:00",
                "reservations": [{"date": "2026-08-01", "heure": "08:57"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(reservation_cache.ReservationCacheError):
        reservation_cache.load_reservations_cache(cache_path=cache_path)


def test_save_is_atomic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cache_path = tmp_path / "reservation_cache.json"
    replace_calls: list[tuple[Path, Path]] = []

    original_replace = reservation_cache.os.replace

    def fake_replace(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
        replace_calls.append((Path(src), Path(dst)))
        original_replace(src, dst)

    monkeypatch.setattr(reservation_cache.os, "replace", fake_replace)

    reservation_cache.save_reservations_cache(
        [_sample_reservation(day=26, reservation_id="R6")],
        cache_path=cache_path,
    )

    assert len(replace_calls) == 1
    assert replace_calls[0][1] == cache_path
    assert replace_calls[0][0] != cache_path


def test_cache_does_not_store_private_fields(tmp_path: Path) -> None:
    cache_path = tmp_path / "reservation_cache.json"
    reservation_cache.save_reservations_cache(
        [_sample_reservation(day=27, reservation_id="R7")],
        cache_path=cache_path,
    )
    raw = json.loads(cache_path.read_text(encoding="utf-8"))

    for entry in raw["reservations"]:
        assert set(entry.keys()) == {
            "date",
            "heure",
            "joueurs",
            "reservation_id",
        }


def test_reservations_cache_file_permissions_are_restrictive_if_possible(tmp_path: Path) -> None:
    cache_path = tmp_path / "reservation_cache.json"
    reservation_cache.save_reservations_cache(
        [_sample_reservation(day=28, reservation_id="R8")],
        cache_path=cache_path,
    )

    if os.name != "nt":
        assert oct(cache_path.stat().st_mode & 0o777) == "0o600"
