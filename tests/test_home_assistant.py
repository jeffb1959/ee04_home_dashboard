"""Tests de la configuration et du client Home Assistant BME280."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.error import URLError

import pytest


RACINE_PROJET = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE_PROJET))

import app as app_module
from config import HomeAssistantConfig, load_home_assistant_config
from dashboard_renderer import _format_measurement, _format_weather_measurement
from home_assistant_client import HomeAssistantClient, translate_weather_condition


class FakeResponse:
    """Réponse minimale compatible avec `urllib.request.urlopen`."""

    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def configured_settings(token: str = "secret-test-token") -> HomeAssistantConfig:
    return HomeAssistantConfig(
        url="http://homeassistant.local:8123",
        token=token,
        temperature_entity="sensor.bme280_temperature",
        humidity_entity="sensor.bme280_humidity",
        pressure_entity="sensor.bme280_pressure",
        weather_entity="weather.forecast_maison",
    )


def test_configuration_is_loaded_from_env_file(tmp_path: Path) -> None:
    """Le secret provient du `.env` et n'apparaît pas dans la représentation."""

    secret = "jeton-local-uniquement"
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            (
                "HOME_ASSISTANT_URL=http://ha.test:8123",
                f"HOME_ASSISTANT_TOKEN={secret}",
                "HA_ENTITY_TEMPERATURE=sensor.temperature",
                "HA_ENTITY_HUMIDITY=sensor.humidity",
                "HA_ENTITY_PRESSURE=sensor.pressure",
                "HA_ENTITY_WEATHER=weather.forecast_maison",
            )
        ),
        encoding="utf-8",
    )

    config = load_home_assistant_config(env_file=env_file, environ={})

    assert config.configured is True
    assert config.token == secret
    assert config.weather_entity == "weather.forecast_maison"
    assert config.weather_configured is True
    assert secret not in repr(config)
    assert secret not in (RACINE_PROJET / ".env.example").read_text(encoding="utf-8")


def test_fetch_entity_success_uses_bearer_token(tmp_path: Path) -> None:
    """Une entité valide retourne état, unité et date de mise à jour."""

    captured: dict = {}

    def fake_urlopen(request: object, timeout: float) -> FakeResponse:
        captured["authorization"] = request.get_header("Authorization")
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        return FakeResponse(
            {
                "state": "22.4",
                "attributes": {"unit_of_measurement": "°C"},
                "last_updated": "2026-07-20T18:10:00+00:00",
            }
        )

    client = HomeAssistantClient(
        configured_settings(),
        cache_path=tmp_path / "cache.json",
        urlopen_function=fake_urlopen,
    )

    entity = client.fetch_entity("sensor.bme280_temperature")

    assert entity == {
        "state": "22.4",
        "unit_of_measurement": "°C",
        "attributes": {"unit_of_measurement": "°C"},
        "last_updated": "2026-07-20T18:10:00+00:00",
    }
    assert captured["authorization"] == "Bearer secret-test-token"
    assert captured["url"].endswith("/api/states/sensor.bme280_temperature")


def test_unavailable_state_uses_placeholder_without_cache(tmp_path: Path) -> None:
    """L'état `unavailable` est refusé et remplacé sans casser le résultat."""

    def fake_urlopen(request: object, timeout: float) -> FakeResponse:
        return FakeResponse({"state": "unavailable", "attributes": {}})

    client = HomeAssistantClient(
        configured_settings(),
        cache_path=tmp_path / "cache.json",
        urlopen_function=fake_urlopen,
    )

    data = client.get_bme280_data()

    assert data["temperature"]["value"] is None
    assert data["temperature"]["ok"] is False
    assert data["source"] == "fallback"
    assert "état non disponible" in data["error"]


def test_successful_bme280_read_updates_cache(tmp_path: Path) -> None:
    """Trois lectures valides produisent une source live et un cache complet."""

    states = {
        "temperature": ("22.4", "°C"),
        "humidity": ("64", "%"),
        "pressure": ("1012", "hPa"),
    }

    def fake_urlopen(request: object, timeout: float) -> FakeResponse:
        name = next(name for name in states if name in request.full_url)
        state, unit = states[name]
        return FakeResponse(
            {
                "state": state,
                "attributes": {"unit_of_measurement": unit},
                "last_updated": "2026-07-20T18:20:00+00:00",
            }
        )

    cache_path = tmp_path / "home_assistant_cache.json"
    client = HomeAssistantClient(
        configured_settings(),
        cache_path=cache_path,
        urlopen_function=fake_urlopen,
    )

    data = client.get_bme280_data()
    cache = json.loads(cache_path.read_text(encoding="utf-8"))

    assert data["source"] == "live"
    assert data["error"] is None
    assert cache["temperature"]["value"] == 22.4
    assert cache["humidity"]["value"] == 64.0
    assert cache["pressure"]["value"] == 1012.0
    assert cache["updated_at"]
    assert cache["source_status"] == "live"


def test_cache_is_used_when_home_assistant_is_unreachable(tmp_path: Path) -> None:
    """Une panne réseau restitue la dernière valeur valide du cache local."""

    cache_path = tmp_path / "home_assistant_cache.json"
    cache_path.write_text(
        json.dumps(
            {
                "temperature": {"value": 21.8, "unit": "°C"},
                "humidity": {"value": 63, "unit": "%"},
                "pressure": {"value": 1009, "unit": "hPa"},
                "updated_at": "2026-07-20T17:00:00+00:00",
                "source_status": "live",
            }
        ),
        encoding="utf-8",
    )

    def failing_urlopen(request: object, timeout: float) -> FakeResponse:
        raise URLError("connexion refusée")

    client = HomeAssistantClient(
        configured_settings(),
        cache_path=cache_path,
        urlopen_function=failing_urlopen,
    )

    data = client.get_bme280_data()

    assert data["source"] == "cache"
    assert data["temperature"]["value"] == 21.8
    assert data["humidity"]["value"] == 63.0
    assert data["pressure"]["value"] == 1009.0
    assert all(data[name]["cached"] for name in ("temperature", "humidity", "pressure"))
    assert client.health_status()["last_fetch_ok"] is False


def test_health_exposes_entities_but_never_token(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`/health` publie le diagnostic utile, jamais le jeton sensible."""

    secret = "ne-jamais-exposer-ce-jeton"
    client = HomeAssistantClient(
        configured_settings(token=secret), cache_path=tmp_path / "cache.json"
    )
    monkeypatch.setattr(app_module, "home_assistant_client", client)

    with app_module.app.test_client() as flask_client:
        response = flask_client.get("/health")

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["home_assistant"]["configured"] is True
    assert payload["home_assistant"]["entities"]["temperature"] == (
        "sensor.bme280_temperature"
    )
    assert secret not in response.get_data(as_text=True)
    assert "token" not in payload["home_assistant"]
    assert payload["weather"]["configured"] is True
    assert payload["weather"]["entity_id"] == "weather.forecast_maison"
    assert "token" not in payload["weather"]


def test_bme280_values_use_french_readable_format() -> None:
    """Le rendu emploie la virgule et les arrondis attendus."""

    data = {
        "temperature": {"value": 22.4, "unit": "°C"},
        "humidity": {"value": 63.8, "unit": "%"},
        "pressure": {"value": 1011.7, "unit": "hPa"},
    }

    assert _format_measurement(data, "temperature") == ("22,4", "°C")
    assert _format_measurement(data, "humidity") == ("64", "%")
    assert _format_measurement(data, "pressure") == ("1012", "hPa")
    assert _format_measurement(None, "pressure") == ("----", "hPa")


def weather_payload(*, state: str = "cloudy", include_pressure: bool = True) -> dict:
    """Construit une réponse réaliste de `weather.forecast_maison`."""

    attributes = {
        "temperature": 21.5,
        "temperature_unit": "°C",
        "humidity": 79,
        "cloud_coverage": 92.2,
        "uv_index": 0.3,
        "pressure_unit": "inHg",
        "wind_bearing": 231,
        "wind_speed": 4.72,
        "wind_speed_unit": "mph",
    }
    if include_pressure:
        attributes["pressure"] = 29.82
    return {
        "state": state,
        "attributes": attributes,
        "last_updated": "2026-07-20T19:10:00+00:00",
    }


def test_weather_entity_success_and_cloudy_translation(tmp_path: Path) -> None:
    """L'entité météo complète est normalisée et mise en cache."""

    captured: dict = {}

    def fake_urlopen(request: object, timeout: float) -> FakeResponse:
        captured["url"] = request.full_url
        return FakeResponse(weather_payload())

    cache_path = tmp_path / "home_assistant_cache.json"
    client = HomeAssistantClient(
        configured_settings(),
        cache_path=cache_path,
        urlopen_function=fake_urlopen,
    )

    data = client.get_weather_data()
    cache = json.loads(cache_path.read_text(encoding="utf-8"))

    assert captured["url"].endswith("/api/states/weather.forecast_maison")
    assert data["condition_raw"] == "cloudy"
    assert data["condition_fr"] == "Nuageux"
    assert translate_weather_condition("cloudy") == "Nuageux"
    assert data["temperature"] == {
        "value": 21.5,
        "unit": "°C",
        "ok": True,
        "cached": False,
        "last_updated": "2026-07-20T19:10:00+00:00",
    }
    assert data["pressure"]["value"] == 29.82
    assert data["pressure"]["unit"] == "inHg"
    assert data["source"] == "home_assistant"
    assert data["error"] is None
    assert cache["weather"]["condition_raw"] == "cloudy"
    assert cache["weather"]["temperature"]["value"] == 21.5
    assert client.weather_health_status()["source"] == "live"


def test_unavailable_weather_state_uses_placeholders_without_cache(
    tmp_path: Path,
) -> None:
    """Un état météo indisponible ne casse pas le rendu et reste explicite."""

    def fake_urlopen(request: object, timeout: float) -> FakeResponse:
        return FakeResponse(weather_payload(state="unavailable"))

    client = HomeAssistantClient(
        configured_settings(),
        cache_path=tmp_path / "cache.json",
        urlopen_function=fake_urlopen,
    )

    data = client.get_weather_data()

    assert data["condition_raw"] is None
    assert data["condition_fr"] == "Données indisponibles"
    assert data["temperature"]["value"] is None
    assert data["temperature"]["ok"] is False
    assert data["source"] == "fallback"
    assert "état météo non disponible" in data["error"]


def test_missing_weather_pressure_keeps_other_live_values(tmp_path: Path) -> None:
    """Un attribut manquant devient un placeholder sans rejeter l'entité."""

    def fake_urlopen(request: object, timeout: float) -> FakeResponse:
        return FakeResponse(weather_payload(include_pressure=False))

    client = HomeAssistantClient(
        configured_settings(),
        cache_path=tmp_path / "cache.json",
        urlopen_function=fake_urlopen,
    )

    data = client.get_weather_data()

    assert data["temperature"]["value"] == 21.5
    assert data["pressure"] == {
        "value": None,
        "ok": False,
        "cached": False,
        "last_updated": None,
        "unit": "inHg",
    }
    assert data["source"] == "home_assistant"
    assert "pressure" in data["error"]


def test_weather_cache_is_used_when_home_assistant_is_unreachable(
    tmp_path: Path,
) -> None:
    """Une panne restitue les dernières données météo valides du cache."""

    cache_path = tmp_path / "home_assistant_cache.json"
    cache_path.write_text(
        json.dumps(
            {
                "weather": {
                    "condition_raw": "cloudy",
                    "condition_fr": "Nuageux",
                    "temperature": {"value": 21.5, "unit": "°C"},
                    "humidity": {"value": 79, "unit": "%"},
                    "pressure": {"value": 29.82, "unit": "inHg"},
                }
            }
        ),
        encoding="utf-8",
    )

    def failing_urlopen(request: object, timeout: float) -> FakeResponse:
        raise URLError("connexion refusée")

    client = HomeAssistantClient(
        configured_settings(),
        cache_path=cache_path,
        urlopen_function=failing_urlopen,
    )

    data = client.get_weather_data()

    assert data["source"] == "cache"
    assert data["condition_fr"] == "Nuageux"
    assert data["temperature"]["value"] == 21.5
    assert data["temperature"]["cached"] is True
    assert data["pressure"]["unit"] == "inHg"
    assert client.weather_health_status()["last_fetch_ok"] is False


def test_weather_values_use_french_readable_format() -> None:
    """Le panneau météo conserve les décimales utiles et les unités HA."""

    data = {
        "temperature": {"value": 21.5, "unit": "°C"},
        "humidity": {"value": 79, "unit": "%"},
        "pressure": {"value": 29.82, "unit": "inHg"},
    }

    assert _format_weather_measurement(data, "temperature") == ("21,5", "°C")
    assert _format_weather_measurement(data, "humidity") == ("79", "%")
    assert _format_weather_measurement(data, "pressure") == ("29,82", "inHg")
    assert _format_weather_measurement(None, "pressure") == ("--", "")
