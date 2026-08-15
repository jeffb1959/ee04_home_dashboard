"""Tests unitaires pour `scripts/refresh_reservations.py`."""

from __future__ import annotations

from datetime import datetime, date, time
from pathlib import Path
import json
import sys

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT_DIR / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import reservation_parser
from chronogolf_client import ChronogolfIMAPError, ImapConfig, ImapConfigError

import refresh_reservations


def _cache_content(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class _FakeClient:
    def __init__(self, reservations):
        self.reservations = reservations

    def get_upcoming_reservations(self, *, reference=None, today=None):
        return self.reservations


class _FailingClient:
    def __init__(self, _config: ImapConfig) -> None:
        self.config = _config

    def get_upcoming_reservations(self, *, reference=None, today=None):
        raise ChronogolfIMAPError("network unavailable")


def _build_config() -> ImapConfig:
    return ImapConfig(
        host="imap.test",
        port=993,
        user="user@example.com",
        password="top-secret-password",
    )


def test_refresh_with_no_reservations_writes_empty_cache(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cache_path = tmp_path / "reservation_cache.json"

    code = refresh_reservations.refresh_reservations(
        now=datetime(2026, 8, 14, 9, 0, 0),
        cache_path=cache_path,
        client_factory=lambda config: _FakeClient([]),
        config=_build_config(),
    )

    captured = capsys.readouterr().out
    assert code == 0
    assert "0 réservations futures trouvées." in captured
    assert cache_path.exists()
    assert _cache_content(cache_path)["reservations"] == []


def test_refresh_success_with_reservations_updates_cache_and_summary(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cache_path = tmp_path / "reservation_cache.json"
    reservations = [
        reservation_parser.GolfReservation(
            date=date(2026, 8, 30),
            heure=time(9, 0),
            joueurs=["Alice", "Bob"],
            reservation_id="TEAM-1",
        )
    ]

    code = refresh_reservations.refresh_reservations(
        now=datetime(2026, 8, 14, 9, 0, 0),
        cache_path=cache_path,
        client_factory=lambda config: _FakeClient(reservations),
        config=_build_config(),
    )

    captured = capsys.readouterr().out
    assert code == 0
    assert "1 réservation future trouvée." in captured
    assert "Cache mis à jour" in captured


def test_successful_refresh_replaces_old_cache_with_empty_list(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cache_path = tmp_path / "reservation_cache.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(
            {
                "version": 1,
                "updated_at": "2026-08-14T10:00:00",
                "reservations": [
                    {
                        "date": "2026-08-15",
                        "heure": "08:57",
                        "joueurs": ["Ancien"],
                        "reservation_id": "OLD",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    code = refresh_reservations.refresh_reservations(
        now=datetime(2026, 8, 14, 9, 0, 0),
        cache_path=cache_path,
        client_factory=lambda config: _FakeClient([]),
        config=_build_config(),
    )

    assert code == 0
    cached = _cache_content(cache_path)
    assert cached["reservations"] == []


def test_imap_error_keeps_existing_cache(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cache_path = tmp_path / "reservation_cache.json"
    cache_content = {
        "version": 1,
        "updated_at": "2026-08-14T10:00:00",
        "reservations": [
            {
                "date": "2026-08-16",
                "heure": "08:57",
                "joueurs": ["Alice"],
                "reservation_id": "GOOD",
            }
        ],
    }
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(cache_content), encoding="utf-8")

    code = refresh_reservations.refresh_reservations(
        now=datetime(2026, 8, 14, 9, 0, 0),
        cache_path=cache_path,
        client_factory=lambda config: _FailingClient(config),
        config=_build_config(),
    )

    assert code != 0
    assert _cache_content(cache_path) == cache_content
    captured = capsys.readouterr().out
    assert "Dernier cache conservé." in captured


def test_imap_error_without_existing_cache_does_not_create_one(tmp_path: Path) -> None:
    cache_path = tmp_path / "reservation_cache.json"

    code = refresh_reservations.refresh_reservations(
        now=datetime(2026, 8, 14, 9, 0, 0),
        cache_path=cache_path,
        client_factory=lambda config: _FailingClient(config),
        config=_build_config(),
    )

    assert code != 0
    assert not cache_path.exists()


def test_refresh_does_not_expose_credentials_on_error(tmp_path: Path) -> None:
    config = _build_config()
    cache_path = tmp_path / "reservation_cache.json"

    from io import StringIO
    import contextlib

    output = StringIO()
    with contextlib.redirect_stdout(output):
        refresh_reservations.refresh_reservations(
            now=datetime(2026, 8, 14, 9, 0, 0),
            cache_path=cache_path,
            client_factory=lambda _config: _FailingClient(_config),
            config=config,
        )

    rendered = output.getvalue()
    assert config.password not in rendered
    assert "top-secret-password" not in rendered


def test_refresh_imap_error_returns_non_zero_exit_code() -> None:
    code = refresh_reservations.refresh_reservations(
        now=datetime(2026, 8, 14, 9, 0, 0),
        cache_path=Path("/tmp/does-not-exist/test.json"),
        client_factory=lambda config: _FailingClient(config),
        config=_build_config(),
    )

    assert code != 0
