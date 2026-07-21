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
        ec_weather_entity="weather.ec_meteo",
        ec_condition_entity="sensor.ec_condition",
        ec_temperature_entity="sensor.ec_temperature",
        ec_humidity_entity="sensor.ec_humidity",
        ec_pressure_entity="sensor.ec_pressure",
        ec_wind_direction_text_entity="sensor.ec_wind_direction",
        ec_wind_speed_entity="sensor.ec_wind_speed",
        ec_precip_probability_entity="sensor.ec_precip_probability",
        ec_high_temp_entity="sensor.ec_high_temp",
        ec_low_temp_entity="sensor.ec_low_temp",
        ec_summary_entity="sensor.ec_summary",
        ec_alerts_entity="sensor.ec_alerts",
        ec_advisories_entity="sensor.ec_advisories",
        ec_watches_entity="sensor.ec_watches",
        ec_bulletins_entity="sensor.ec_bulletins",
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
                "HA_EC_WEATHER_ENTITY=weather.ec_meteo",
                "HA_EC_CONDITION=sensor.ec_condition",
                "HA_EC_TEMPERATURE=sensor.ec_temperature",
                "HA_EC_HUMIDITY=sensor.ec_humidity",
                "HA_EC_PRESSURE=sensor.ec_pressure",
                "HA_EC_WIND_DIRECTION_TEXT=sensor.ec_wind_direction",
                "HA_EC_WIND_SPEED=sensor.ec_wind_speed",
                "HA_EC_PRECIP_PROBABILITY=sensor.ec_precip",
                "HA_EC_HIGH_TEMP=sensor.ec_high",
                "HA_EC_LOW_TEMP=sensor.ec_low",
                "HA_EC_SUMMARY=sensor.ec_summary",
                "HA_EC_ALERTS=sensor.ec_alerts",
                "HA_EC_ADVISORIES=sensor.ec_advisories",
                "HA_EC_WATCHES=sensor.ec_watches",
                "HA_EC_BULLETINS=sensor.ec_bulletins",
            )
        ),
        encoding="utf-8",
    )

    config = load_home_assistant_config(env_file=env_file, environ={})

    assert config.configured is True
    assert config.token == secret
    assert config.weather_entity == "weather.forecast_maison"
    assert config.ec_condition_entity == "sensor.ec_condition"
    assert config.ec_alerts_entity == "sensor.ec_alerts"
    assert config.environment_canada_configured is True
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
    assert payload["weather"]["configured"] is True
    assert payload["environment_canada"]["configured"] is True
    assert "token" not in str(payload)
    assert secret not in response.get_data(as_text=True)


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


def test_unavailable_weather_state_uses_placeholders_without_cache(tmp_path: Path) -> None:
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
    """Une panne restitue les dernières données météo valides du cache local."""

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


def _ec_payload(entity_id: str, *, value: object) -> dict:
    """Construit une entité Home Assistant simulée pour Environnement Canada."""

    if entity_id in {"sensor.ec_humidity"}:
        unit = "%"
    elif entity_id == "sensor.ec_pressure":
        unit = "hPa"
    elif "precip" in entity_id:
        unit = "%"
    elif entity_id == "sensor.ec_wind_speed":
        unit = "km/h"
    else:
        unit = "°C"

    if isinstance(value, str) or isinstance(value, bool):
        return {"state": str(value), "attributes": {}, "last_updated": "2026-07-20T19:45:00+00:00"}
    return {"state": str(value), "attributes": {"unit_of_measurement": unit}, "last_updated": "2026-07-20T19:45:00+00:00"}


def test_environment_canada_reading_success_and_cache(tmp_path: Path) -> None:
    """La lecture Environnement Canada met à jour le cache et renvoie une structure cohérente."""

    settings = configured_settings()
    entity_data = {
        "weather.forecast_maison": "cloudy",
        "sensor.ec_condition": "Généralement nuageux",
        "sensor.ec_temperature": 18.8,
        "sensor.ec_humidity": 77,
        "sensor.ec_pressure": 1011,
        "sensor.ec_wind_direction": "OSO",
        "sensor.ec_wind_speed": 11,
        "sensor.ec_precip_probability": 30,
        "sensor.ec_high_temp": 25,
        "sensor.ec_low_temp": 15,
        "sensor.ec_summary": "Pluies faibles",
        "sensor.ec_alerts": 1,
        "sensor.ec_advisories": 2,
        "sensor.ec_watches": 0,
        "sensor.ec_bulletins": 0,
    }

    def fake_urlopen(request: object, timeout: float) -> FakeResponse:
        if request.full_url.endswith(f"/api/states/{settings.ec_weather_entity}"):
            return FakeResponse(
                {
                    "entity_id": settings.ec_weather_entity,
                    "state": "cloudy",
                    "attributes": {
                        "temperature": 18.8,
                        "temperature_unit": "°C",
                        "humidity": 77,
                        "pressure": 1011,
                        "pressure_unit": "hPa",
                        "wind_bearing": 253,
                        "wind_speed": 11,
                        "wind_speed_unit": "km/h",
                        "visibility": 24.1,
                        "visibility_unit": "km",
                        "precipitation_unit": "mm",
                    },
                    "last_updated": "2026-07-21T00:00:00+00:00",
                }
            )
        for entity, value in entity_data.items():
            if request.full_url.endswith(f"/api/states/{entity}"):
                return FakeResponse(_ec_payload(entity, value=value))
        if request.full_url.endswith("/api/states/weather.forecast_maison"):
            return FakeResponse(weather_payload())
        raise AssertionError(f"Entity demandée inattendue: {request.full_url}")

    cache_path = tmp_path / "home_assistant_cache.json"
    client = HomeAssistantClient(
        settings,
        cache_path=cache_path,
        urlopen_function=fake_urlopen,
    )

    data = client.get_environment_canada_data()
    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    alerts = data["alerts"]

    assert data["source"] == "home_assistant_environment_canada"
    assert data["condition"]["value"] == "Généralement nuageux"
    assert data["condition"]["ok"] is True
    assert data["temperature"]["value"] == 18.8
    assert data["precip_probability"]["value"] == 30
    assert data["high_temp"]["value"] == 25
    assert data["low_temp"]["value"] == 15
    assert data["wind_direction_text"]["value"] == "OSO"
    assert data["wind_speed"]["value"] == 11
    assert alerts["alerts"] == 1
    assert alerts["advisories"] == 2
    assert alerts["active"] is True
    assert alerts["text"] == "1 alerte / 2 avis"
    assert data["error"] is None
    assert cache["environment_canada"]["condition"]["value"] == "Généralement nuageux"
    assert cache["environment_canada"]["alerts"]["alerts"] == 1


def test_environment_canada_all_alert_counters_zero_no_text(tmp_path: Path) -> None:
    """Aucun compteur actif laisse l'alerte inactive et sans bandeau."""

    entity_data = {
        "sensor.ec_condition": "Pluie",
        "sensor.ec_temperature": 12.0,
        "sensor.ec_humidity": 55,
        "sensor.ec_pressure": 1008,
        "sensor.ec_wind_direction": "N",
        "sensor.ec_wind_speed": 9,
        "sensor.ec_precip_probability": 22,
        "sensor.ec_high_temp": 13,
        "sensor.ec_low_temp": 10,
        "sensor.ec_summary": "OK",
        "sensor.ec_alerts": 0,
        "sensor.ec_advisories": 0,
        "sensor.ec_watches": 0,
        "sensor.ec_bulletins": 0,
    }

    def fake_urlopen(request: object, timeout: float) -> FakeResponse:
        for entity, value in entity_data.items():
            if request.full_url.endswith(f"/api/states/{entity}"):
                return FakeResponse(_ec_payload(entity, value=value))
        raise AssertionError(request.full_url)

    client = HomeAssistantClient(
        configured_settings(),
        cache_path=tmp_path / "cache.json",
        urlopen_function=fake_urlopen,
    )

    data = client.get_environment_canada_data()

    assert data["alerts"]["active"] is False
    assert data["alerts"]["text"] is None


def test_environment_canada_fallback_uses_cache_when_unreachable(tmp_path: Path) -> None:
    """Une panne réseau conserve les dernières valeurs valides Environnement Canada."""

    cache_path = tmp_path / "home_assistant_cache.json"
    cache_payload = {
        "environment_canada": {
            "condition": {"value": "Couvert", "ok": True},
            "temperature": {"value": 16, "unit": "°C", "ok": True},
            "humidity": {"value": 69, "unit": "%", "ok": True},
            "pressure": {"value": 1005, "unit": "hPa", "ok": True},
            "wind_direction_text": {"value": "N", "ok": True},
            "wind_speed": {"value": 9, "unit": "km/h", "ok": True},
            "precip_probability": {"value": 5, "unit": "%", "ok": True},
            "high_temp": {"value": 19, "unit": "°C", "ok": True},
            "low_temp": {"value": 8, "unit": "°C", "ok": True},
            "summary": {"value": "Cache", "ok": True},
            "alerts": {
                "alerts": 0,
                "advisories": 0,
                "watches": 0,
                "bulletins": 0,
            },
            "last_updated": "2026-07-20T19:42:00+00:00",
        }
    }
    cache_path.write_text(json.dumps(cache_payload), encoding="utf-8")

    def failing_urlopen(request: object, timeout: float) -> FakeResponse:
        raise URLError("connexion refusée")

    client = HomeAssistantClient(
        configured_settings(),
        cache_path=cache_path,
        urlopen_function=failing_urlopen,
    )

    data = client.get_environment_canada_data()

    assert data["source"] == "home_assistant_environment_canada"
    assert data["condition"]["value"] == "Couvert"
    assert data["temperature"]["value"] == 16.0
    assert data["alerts"]["text"] is None


def test_environment_canada_unknown_and_unavailable_states_become_placeholders(tmp_path: Path) -> None:
    """States `unknown` ou `unavailable` déclenchent les placeholders ciblés."""

    def fake_urlopen(request: object, timeout: float) -> FakeResponse:
        if request.full_url.endswith("/api/states/sensor.ec_condition"):
            return FakeResponse({"state": "unknown", "attributes": {}, "last_updated": None})
        if request.full_url.endswith("/api/states/sensor.ec_temperature"):
            return FakeResponse({"state": "unavailable", "attributes": {}, "last_updated": None})
        if request.full_url.endswith("/api/states/sensor.ec_humidity"):
            return FakeResponse({"state": "", "attributes": {}, "last_updated": None})
        if request.full_url.endswith("/api/states/sensor.ec_pressure"):
            return FakeResponse({"state": "", "attributes": {"unit_of_measurement": "hPa"}})
        if request.full_url.endswith("/api/states/sensor.ec_wind_direction"):
            return FakeResponse({"state": "OSO", "attributes": {}})
        if request.full_url.endswith("/api/states/sensor.ec_wind_speed"):
            return FakeResponse({"state": "11", "attributes": {"unit_of_measurement": "km/h"}})
        if request.full_url.endswith("/api/states/sensor.ec_precip_probability"):
            return FakeResponse({"state": "30", "attributes": {"unit_of_measurement": "%"}})
        if request.full_url.endswith("/api/states/sensor.ec_high_temp"):
            return FakeResponse({"state": "25", "attributes": {"unit_of_measurement": "°C"}})
        if request.full_url.endswith("/api/states/sensor.ec_low_temp"):
            return FakeResponse({"state": "15", "attributes": {"unit_of_measurement": "°C"}})
        if request.full_url.endswith("/api/states/sensor.ec_summary"):
            return FakeResponse({"state": "OK", "attributes": {}})
        if request.full_url.endswith("/api/states/sensor.ec_alerts"):
            return FakeResponse({"state": "0", "attributes": {"unit_of_measurement": ""}})
        if request.full_url.endswith("/api/states/sensor.ec_advisories"):
            return FakeResponse({"state": "0", "attributes": {"unit_of_measurement": ""}})
        if request.full_url.endswith("/api/states/sensor.ec_watches"):
            return FakeResponse({"state": "0", "attributes": {"unit_of_measurement": ""}})
        if request.full_url.endswith("/api/states/sensor.ec_bulletins"):
            return FakeResponse({"state": "0", "attributes": {"unit_of_measurement": ""}})
        raise AssertionError(request.full_url)

    client = HomeAssistantClient(
        configured_settings(),
        cache_path=tmp_path / "cache.json",
        urlopen_function=fake_urlopen,
    )
    data = client.get_environment_canada_data()

    assert data["condition"]["ok"] is False
    assert data["condition"]["value"] is None
    assert data["temperature"]["ok"] is False
    assert data["humidity"]["ok"] is False
    assert data["source"] == "home_assistant_environment_canada"
