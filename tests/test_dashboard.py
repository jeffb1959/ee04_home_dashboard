"""Tests des routes et du rendu du serveur EE04 Home Dashboard."""

from __future__ import annotations

from datetime import date, datetime, time
import sys
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

RACINE_PROJET = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE_PROJET))

import app as app_module
from activity_service import ActivityInfo
from dashboard_renderer import (
    ALERT_BANNER_BACKGROUND,
    DashboardDiagnostics,
    _format_activity_datetime,
    _format_activity_lines,
    _format_activity_participants,
    _format_activity_player_count,
    _format_diagnostics,
    render_dashboard,
)
from spectra6_converter import IMAGE_SIZE, convert_hybrid, is_protected_pixel


app = app_module.app


class FakeHomeAssistantClient:
    """Évite tout accès réseau dans les tests des routes Flask."""

    def get_bme280_data(self) -> dict:
        return {
            "temperature": {"value": None, "unit": "°C", "ok": False},
            "humidity": {"value": None, "unit": "%", "ok": False},
            "pressure": {"value": None, "unit": "hPa", "ok": False},
            "source": "fallback",
            "error": "simulation hors ligne",
        }

    def get_environment_canada_data(self) -> dict:
        return {
            "condition": {"value": "Données indisponibles", "ok": False},
            "temperature": {"value": None, "unit": "°C", "ok": False},
            "humidity": {"value": None, "unit": "%", "ok": False},
            "pressure": {"value": None, "unit": "hPa", "ok": False},
            "wind_direction_text": {"value": None, "ok": False},
            "wind_speed": {"value": None, "unit": "km/h", "ok": False},
            "precip_probability": {"value": None, "unit": "%", "ok": False},
            "high_temp": {"value": None, "unit": "°C", "ok": False},
            "low_temp": {"value": None, "unit": "°C", "ok": False},
            "summary": {"value": None, "ok": False},
            "alerts": {"alerts": 0, "advisories": 0, "watches": 0, "bulletins": 0, "active": False, "text": None},
            "source": "fallback",
            "error": "simulation hors ligne",
        }

    def get_weather_data(self) -> dict:
        return {
            "condition_raw": None,
            "condition_fr": "Données indisponibles",
            "temperature": {"value": None, "unit": "°C", "ok": False},
            "humidity": {"value": None, "unit": "%", "ok": False},
            "pressure": {"value": None, "unit": "", "ok": False},
            "source": "fallback",
            "error": "simulation hors ligne",
        }

    def health_status(self) -> dict:
        return {
            "configured": False,
            "last_fetch_ok": False,
            "source": "fallback",
            "entities": {
                "temperature": "",
                "humidity": "",
                "pressure": "",
            },
        }

    def weather_health_status(self) -> dict:
        return {
            "configured": False,
            "entity_id": "",
            "last_fetch_ok": False,
            "source": "fallback",
            "condition_raw": None,
            "condition_fr": "Données indisponibles",
        }

    def environment_canada_health_status(self) -> dict:
        return {
            "configured": False,
            "last_fetch_ok": False,
            "source": "fallback",
            "condition": "Données indisponibles",
            "alert_active": False,
            "alert_text": None,
            "entities": {},
        }


@pytest.fixture(autouse=True)
def isolate_home_assistant(monkeypatch: pytest.MonkeyPatch) -> None:
    """Rend les tests déterministes, quel que soit le `.env` de la machine."""

    monkeypatch.setattr(
        app_module, "home_assistant_client", FakeHomeAssistantClient()
    )


def test_health_returns_ok() -> None:
    """La route de santé doit confirmer que le service fonctionne."""

    with app.test_client() as client:
        response = client.get("/health")

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["status"] == "ok"
    assert payload["binary_size"] == 384000
    assert payload["home_assistant"]["source"] == "fallback"
    assert payload["weather"]["source"] == "fallback"
    assert payload["environment_canada"]["source"] == "fallback"
    assert "token" not in response.get_data(as_text=True).lower()


def test_dashboard_returns_an_800_by_480_png() -> None:
    """Le tableau de bord doit être un PNG aux dimensions de l'écran EE04."""

    with app.test_client() as client:
        response = client.get("/dashboard.png")

    assert response.status_code == 200
    assert response.mimetype == "image/png"

    with Image.open(BytesIO(response.data)) as image:
        assert image.format == "PNG"
        assert image.size == (800, 480)


def test_render_source_image_passes_activity_to_renderer_without_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La génération lit l'activité préparée sans déclencher Chronogolf."""

    activity = ActivityInfo(
        status="upcoming",
        date=date(2026, 8, 17),
        heure=time(8, 39),
        participants=["Alice Tremblay"],
        source_id="TEST-1234",
    )
    received: dict[str, Any] = {}

    monkeypatch.setattr(app_module, "get_display_activity", lambda: activity)

    def _fake_renderer(**kwargs: Any) -> Image.Image:
        received.update(kwargs)
        return Image.new("RGB", IMAGE_SIZE)

    def _forbidden_refresh() -> None:
        raise AssertionError("Aucun rafraîchissement Chronogolf pendant le rendu")

    monkeypatch.setattr(app_module, "render_dashboard", _fake_renderer)
    monkeypatch.setattr(app_module, "refresh_reservation_cache", _forbidden_refresh)

    image = app_module._render_source_image()

    assert image.size == IMAGE_SIZE
    assert received["activity"] is activity
    assert received["diagnostics"].screen_rssi is None


@pytest.mark.parametrize(
    ("header_value", "expected"),
    [
        ("-63", -63),
        (None, None),
        ("invalide", None),
        ("-121", None),
        ("1", None),
    ],
)
def test_parse_screen_rssi_is_defensive(
    header_value: str | None,
    expected: int | None,
) -> None:
    assert app_module._parse_screen_rssi(header_value) == expected


def test_diagnostics_format_real_values_without_fictitious_status() -> None:
    diagnostics = DashboardDiagnostics(
        screen_rssi=-63,
        generated_at=datetime(2026, 8, 15, 15, 13),
        mail_updated_at=datetime(2026, 8, 15, 8, 0),
    )

    formatted = _format_diagnostics(diagnostics)

    assert formatted == "Wi-Fi -63 dBm  •  MAJ 15:13  •  Courriel 15 août 08:00"
    assert "Serveur OK" not in formatted


def test_diagnostics_format_missing_values() -> None:
    diagnostics = DashboardDiagnostics(
        screen_rssi=None,
        generated_at=datetime(2026, 8, 15, 15, 13),
        mail_updated_at=None,
    )

    assert _format_diagnostics(diagnostics) == (
        "Wi-Fi -- dBm  •  MAJ 15:13  •  Courriel indisponible"
    )


def test_render_source_image_handles_missing_or_corrupt_mail_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _corrupt_cache() -> None:
        raise app_module.ReservationCacheError("cache invalide")

    monkeypatch.setattr(app_module, "load_reservations_cache", _corrupt_cache)

    image = app_module._render_source_image()

    assert image.size == IMAGE_SIZE


@pytest.mark.parametrize(
    ("path", "headers", "expected_rssi"),
    [
        ("/dashboard.bin?rssi=-61", {}, -61),
        ("/dashboard.bin?rssi=invalide", {}, None),
        ("/dashboard.bin?rssi=-121", {}, None),
        ("/dashboard.bin", {"X-EE04-RSSI": "-72"}, -72),
        (
            "/dashboard.bin?rssi=-61",
            {"X-EE04-RSSI": "-72"},
            -61,
        ),
    ],
)
def test_dashboard_binary_passes_request_rssi_to_its_generation(
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    headers: dict[str, str],
    expected_rssi: int | None,
) -> None:
    captured: list[int | None] = []

    class _Conversion:
        palette_indices = bytes(384000)
        preview = Image.new("RGB", IMAGE_SIZE)

    def _fake_generation(*, screen_rssi: int | None = None) -> _Conversion:
        captured.append(screen_rssi)
        return _Conversion()

    monkeypatch.setattr(app_module, "_generate_spectra6", _fake_generation)

    with app.test_client() as client:
        response = client.get(path, headers=headers)

    assert response.status_code == 200
    assert len(response.data) == 384000
    assert captured == [expected_rssi]


def test_dashboard_png_uses_optional_query_rssi(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received_rssi: list[int | None] = []

    def _fake_renderer(**kwargs: Any) -> Image.Image:
        received_rssi.append(kwargs["diagnostics"].screen_rssi)
        return Image.new("RGB", IMAGE_SIZE)

    monkeypatch.setattr(app_module, "render_dashboard", _fake_renderer)

    with app.test_client() as client:
        assert client.get("/dashboard.png").status_code == 200
        assert client.get("/dashboard.png?rssi=-63").status_code == 200

    assert received_rssi == [None, -63]


def test_activity_formatting_for_upcoming_activity() -> None:
    activity = ActivityInfo(
        status="upcoming",
        date=date(2026, 8, 17),
        heure=time(8, 39),
        participants=["Alice Tremblay", "Bob Martin", "Charles Gagnon"],
        source_id="TEST-1234",
    )

    assert _format_activity_datetime(activity) == "Lundi 17 août à 8 h 39"
    assert _format_activity_player_count(activity) == "3 joueurs"
    assert _format_activity_participants(activity) == (
        "Alice Tremblay • Bob Martin • Charles Gagnon"
    )
    assert "TEST-1234" not in " ".join(_format_activity_lines(activity))


def test_activity_formatting_for_today_and_single_player() -> None:
    activity = ActivityInfo(
        status="today",
        date=date(2026, 8, 17),
        heure=time(9, 0),
        participants=["Alice Tremblay"],
        source_id="TEST-1234",
    )

    assert _format_activity_datetime(activity) == "Aujourd'hui à 9 h 00"
    assert _format_activity_player_count(activity) == "1 joueur"


@pytest.mark.parametrize(
    ("activity", "expected_message"),
    [
        (
            ActivityInfo(
                status="none",
                date=None,
                heure=None,
                participants=[],
                source_id=None,
                message="Aucun départ cette semaine.",
            ),
            "Aucun départ cette semaine.",
        ),
        (
            ActivityInfo(
                status="unavailable",
                date=None,
                heure=None,
                participants=[],
                source_id=None,
                message="Départs indisponibles.",
            ),
            "Départs indisponibles.",
        ),
        (None, "Départs indisponibles."),
    ],
)
def test_activity_unavailable_states_have_a_safe_message(
    activity: ActivityInfo | None,
    expected_message: str,
) -> None:
    assert _format_activity_lines(activity) == (expected_message,)
    assert render_dashboard(activity=activity).size == IMAGE_SIZE


def test_dashboard_binary_has_expected_spectra6_format() -> None:
    """Le firmware doit recevoir exactement un index valide par pixel."""

    with app.test_client() as client:
        response = client.get("/dashboard.bin")

    assert response.status_code == 200
    assert "application/octet-stream" in response.content_type
    assert "dashboard.bin" in response.headers["Content-Disposition"]
    assert "no-store" in response.headers["Cache-Control"]
    assert len(response.data) == 384000
    assert all(0 <= index <= 5 for index in response.data)


def test_dashboard_spectra6_preview_is_an_800_by_480_png() -> None:
    """L'aperçu doit représenter le même format d'écran que le binaire."""

    with app.test_client() as client:
        response = client.get("/dashboard-spectra6.png")

    assert response.status_code == 200
    assert response.mimetype == "image/png"
    assert "no-store" in response.headers["Cache-Control"]

    with Image.open(BytesIO(response.data)) as image:
        assert image.format == "PNG"
        assert image.size == IMAGE_SIZE


def test_hybrid_conversion_keeps_protected_zones_black_and_white() -> None:
    """Les zones lisibles ne doivent employer que les index noir et blanc."""

    source = Image.new("RGB", IMAGE_SIZE, (255, 255, 255))
    source.paste((0, 0, 0), (500, 40, 640, 180))
    conversion = convert_hybrid(source)
    width, height = IMAGE_SIZE

    protected_indices = {
        conversion.palette_indices[y * width + x]
        for y in range(height)
        for x in range(width)
        if is_protected_pixel(x, y)
    }

    assert protected_indices == {0, 1}


def test_renderer_works_without_background(tmp_path: Path) -> None:
    """Un fond absent doit produire l'image de secours sans lever d'erreur."""

    missing_background = tmp_path / "background_absent.png"
    image = render_dashboard(background_path=missing_background)

    assert image.mode == "RGB"
    assert image.size == (800, 480)


def test_environment_alert_banner_is_hidden_when_inactive(tmp_path: Path) -> None:
    """Aucune alerte active ne doit afficher le bandeau rouge."""

    image = render_dashboard(
        background_path=tmp_path / "background_absent.png",
        weather_data={
            "condition": {"value": "Nuageux", "ok": True},
            "temperature": {"value": 20.0, "unit": "°C", "ok": True},
            "humidity": {"value": 60, "unit": "%", "ok": True},
            "pressure": {"value": 1010, "unit": "hPa", "ok": True},
            "wind_direction_text": {"value": "OSO", "ok": True},
            "wind_speed": {"value": 9, "unit": "km/h", "ok": True},
            "precip_probability": {"value": 10, "unit": "%", "ok": True},
            "high_temp": {"value": 23, "unit": "°C", "ok": True},
            "low_temp": {"value": 12, "unit": "°C", "ok": True},
            "summary": {"value": "", "ok": True},
            "alerts": {"alerts": 0, "advisories": 0, "watches": 0, "bulletins": 0, "active": False, "text": None},
            "source": "home_assistant_environment_canada",
            "error": None,
        },
    )

    assert image.getpixel((5, 5)) != ALERT_BANNER_BACKGROUND


def test_environment_alert_banner_is_visible_when_active(tmp_path: Path) -> None:
    """Un compteur d'alerte actif doit afficher un bandeau rouge unique."""

    image = render_dashboard(
        background_path=tmp_path / "background_absent.png",
        weather_data={
            "condition": {"value": "Pluvieux", "ok": True},
            "temperature": {"value": 20.0, "unit": "°C", "ok": True},
            "humidity": {"value": 60, "unit": "%", "ok": True},
            "pressure": {"value": 1010, "unit": "hPa", "ok": True},
            "wind_direction_text": {"value": "OSO", "ok": True},
            "wind_speed": {"value": 9, "unit": "km/h", "ok": True},
            "precip_probability": {"value": 10, "unit": "%", "ok": True},
            "high_temp": {"value": 23, "unit": "°C", "ok": True},
            "low_temp": {"value": 12, "unit": "°C", "ok": True},
            "summary": {"value": "", "ok": True},
            "alerts": {"alerts": 0, "advisories": 1, "watches": 0, "bulletins": 0, "active": True, "text": "1 avis"},
            "source": "home_assistant_environment_canada",
            "error": None,
        },
    )

    assert image.getpixel((5, 5)) == ALERT_BANNER_BACKGROUND


def test_refresh_route_without_authorization_returns_401(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(app_module, "load_refresh_token", lambda: "TOKEN_OK")

    with app.test_client() as client:
        response = client.post("/api/reservations/refresh")

    assert response.status_code == 401
    payload = response.get_json()
    assert payload == {"status": "error", "error": "unauthorized"}


def test_refresh_route_with_wrong_token_returns_401(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app_module, "load_refresh_token", lambda: "TOKEN_OK")

    with app.test_client() as client:
        response = client.post(
            "/api/reservations/refresh",
            headers={"Authorization": "Bearer TOKEN_WRONG"},
        )

    assert response.status_code == 401
    assert response.get_json() == {"status": "error", "error": "unauthorized"}


def test_refresh_route_with_valid_token_returns_ok_and_no_sensitive_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(app_module, "load_refresh_token", lambda: "TOKEN_OK")

    def _fake_refresh() -> Any:
        return app_module.ReservationRefreshResult(
            reservations_count=2,
            updated_at=datetime(2026, 8, 14, 22, 30, 0),
        )

    monkeypatch.setattr(app_module, "refresh_reservation_cache", _fake_refresh)

    with app.test_client() as client:
        response = client.post(
            "/api/reservations/refresh",
            headers={"Authorization": "Bearer TOKEN_OK"},
        )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["status"] == "ok"
    assert payload["reservations"] == 2
    assert payload["updated_at"] == "2026-08-14T22:30:00"
    assert "joueurs" not in payload
    assert "reservation_id" not in payload


def test_refresh_route_without_configured_token_returns_503(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app_module, "load_refresh_token", lambda: None)

    with app.test_client() as client:
        response = client.post(
            "/api/reservations/refresh",
            headers={"Authorization": "Bearer ANY"},
        )

    assert response.status_code == 503
    assert response.get_json() == {
        "status": "error",
        "error": "refresh_not_configured",
    }


def test_refresh_route_error_returns_503_and_does_not_log_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app_module, "load_refresh_token", lambda: "TOKEN_OK")

    def _failing_refresh() -> Any:
        raise Exception("failure including token TOKEN_OK")

    logs: list[str] = []

    def _fake_exception(message: str, *args: Any, **kwargs: Any) -> None:
        logs.append(message)

    monkeypatch.setattr(app_module.app.logger, "exception", _fake_exception)
    monkeypatch.setattr(app_module, "refresh_reservation_cache", _failing_refresh)

    with app.test_client() as client:
        response = client.post(
            "/api/reservations/refresh",
            headers={"Authorization": "Bearer TOKEN_OK"},
        )

    assert response.status_code == 503
    assert response.get_json() == {"status": "error", "error": "refresh_failed"}
    assert logs
    assert "TOKEN_OK" not in "".join(logs)


def test_refresh_route_rejects_get_with_405() -> None:
    with app.test_client() as client:
        response = client.get("/api/reservations/refresh")

    assert response.status_code == 405


def test_health_never_returns_refresh_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app_module, "load_refresh_token", lambda: "TOKEN_OK")

    with app.test_client() as client:
        response = client.get("/health")

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "TOKEN_OK" not in body


def test_non_refresh_routes_do_not_trigger_chronogolf_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(app_module, "load_refresh_token", lambda: "TOKEN_OK")

    refresh_called = 0

    def _forbidden_refresh() -> Any:
        nonlocal refresh_called
        refresh_called += 1
        raise AssertionError("refresh route should not be called")

    monkeypatch.setattr(app_module, "refresh_reservation_cache", _forbidden_refresh)

    with app.test_client() as client:
        assert client.get("/").status_code == 200
        assert client.get("/dashboard.png").status_code == 200
        assert client.get("/dashboard.bin").status_code == 200
        assert client.get("/dashboard-spectra6.png").status_code == 200

    assert refresh_called == 0
