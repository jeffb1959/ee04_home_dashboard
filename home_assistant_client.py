"""Client REST résilient pour les données Home Assistant du tableau de bord."""

from __future__ import annotations

import json
import logging
import math
import os
import threading
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from config import HomeAssistantConfig


LOGGER = logging.getLogger(__name__)
PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_CACHE_PATH = PROJECT_DIR / "data" / "home_assistant_cache.json"
DEFAULT_TIMEOUT_SECONDS = 5.0

MEASUREMENTS = ("temperature", "humidity", "pressure")
DEFAULT_UNITS = {
    "temperature": "°C",
    "humidity": "%",
    "pressure": "hPa",
}
WEATHER_MEASUREMENTS = (
    "temperature",
    "humidity",
    "pressure",
    "wind_speed",
    "wind_bearing",
    "cloud_coverage",
    "uv_index",
)
WEATHER_DEFAULT_UNITS = {
    "temperature": "°C",
    "humidity": "%",
    "pressure": "",
    "wind_speed": "",
    "wind_bearing": "",
    "cloud_coverage": "%",
    "uv_index": "",
}
WEATHER_UNIT_ATTRIBUTES = {
    "temperature": "temperature_unit",
    "humidity": None,
    "pressure": "pressure_unit",
    "wind_speed": "wind_speed_unit",
    "wind_bearing": None,
    "cloud_coverage": None,
    "uv_index": None,
}
WEATHER_CONDITION_TRANSLATIONS = {
    "clear-night": "Nuit claire",
    "cloudy": "Nuageux",
    "fog": "Brouillard",
    "hail": "Grêle",
    "lightning": "Orage",
    "lightning-rainy": "Orages et pluie",
    "partlycloudy": "Partiellement nuageux",
    "pouring": "Pluie abondante",
    "rainy": "Pluvieux",
    "snowy": "Neige",
    "snowy-rainy": "Neige et pluie",
    "sunny": "Ensoleillé",
    "windy": "Venteux",
    "windy-variant": "Variable venteux",
    "exceptional": "Conditions exceptionnelles",
}
EC_NUMERIC_FIELDS = (
    "temperature",
    "humidity",
    "pressure",
    "wind_speed",
    "precip_probability",
    "high_temp",
    "low_temp",
)
EC_TEXT_FIELDS = (
    "condition",
    "wind_direction_text",
    "summary",
)
EC_ALERT_FIELDS = ("alerts", "advisories", "watches", "bulletins")
EC_DEFAULT_UNITS = {
    "temperature": "°C",
    "humidity": "%",
    "pressure": "hPa",
    "wind_speed": "km/h",
    "precip_probability": "%",
    "high_temp": "°C",
    "low_temp": "°C",
}


class HomeAssistantError(RuntimeError):
    """Erreur attendue et présentable sans information sensible."""


def _is_unavailable_value(value: str) -> bool:
    """Détecte les états HA non exploitables."""

    normalized = str(value or "").strip().lower()
    return normalized in {"unknown", "unavailable", ""}


def _parse_float(raw: Any) -> float | None:
    """Convertit proprement une valeur textuelle en float."""

    if isinstance(raw, bool) or raw is None:
        return None
    if isinstance(raw, (int, float)):
        if not math.isfinite(raw):
            return None
        return float(raw)
    if isinstance(raw, str):
        cleaned = raw.strip().replace(",", ".")
        if not cleaned or cleaned.lower() in {"nan", "inf", "+inf", "-inf"}:
            return None
        try:
            value = float(cleaned)
        except ValueError:
            return None
        return value if math.isfinite(value) else None
    return None


def _parse_int(raw: Any) -> int | None:
    """Convertit proprement une valeur d'alerte vers un entier."""

    value = _parse_float(raw)
    if value is None:
        return None
    return int(round(value))


def translate_weather_condition(condition: str | None) -> str:
    """Traduit un état météo Home Assistant, sans masquer un état inconnu."""

    raw_condition = str(condition or "").strip()
    if not raw_condition:
        return "Inconnu"
    return WEATHER_CONDITION_TRANSLATIONS.get(raw_condition.lower(), raw_condition)


class HomeAssistantClient:
    """Lit les entités Home Assistant et conserve leur dernière valeur valide."""

    def __init__(
        self,
        config: HomeAssistantConfig,
        *,
        cache_path: str | Path = DEFAULT_CACHE_PATH,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        urlopen_function: Callable[..., Any] = urlopen,
    ) -> None:
        self.config = config
        self.cache_path = Path(cache_path)
        self.timeout = timeout
        self._urlopen = urlopen_function
        self._lock = threading.Lock()
        self._last_fetch_ok = False
        self._last_source = "fallback"
        self._weather_last_fetch_ok = False
        self._weather_last_source = "fallback"
        self._weather_condition_raw = None
        self._weather_condition_fr = "Données indisponibles"
        self._environment_canada_last_fetch_ok = False
        self._environment_canada_last_source = "fallback"
        self._environment_canada_last_condition = "Données indisponibles"
        self._environment_canada_last_alert_active = False
        self._environment_canada_last_alert_text = None

    def fetch_entity(self, entity_id: str) -> dict[str, Any]:
        """Retourne l'état brut d'une entité depuis l'API REST Home Assistant."""

        if not self.config.url or not self.config.token:
            raise HomeAssistantError("configuration Home Assistant incomplète")
        if not entity_id:
            raise HomeAssistantError("identifiant d'entité Home Assistant absent")

        entity_url = f"{self.config.url}/api/states/{quote(entity_id, safe='')}"
        request = Request(
            entity_url,
            headers={
                "Authorization": f"Bearer {self.config.token}",
                "Accept": "application/json",
            },
            method="GET",
        )

        try:
            with self._urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            if error.code in (401, 403):
                message = "jeton Home Assistant invalide ou non autorisé"
            elif error.code == 404:
                message = f"entité Home Assistant introuvable: {entity_id}"
            else:
                message = f"Home Assistant a répondu HTTP {error.code}"
            raise HomeAssistantError(message) from error
        except URLError as error:
            raise HomeAssistantError("Home Assistant est inaccessible") from error
        except (OSError, TimeoutError) as error:
            raise HomeAssistantError("Home Assistant est inaccessible") from error
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as error:
            raise HomeAssistantError("réponse Home Assistant invalide") from error

        if not isinstance(payload, dict):
            raise HomeAssistantError("réponse Home Assistant invalide")

        attributes = payload.get("attributes")
        if not isinstance(attributes, dict):
            attributes = {}
        return {
            "state": str(payload.get("state", "")),
            "unit_of_measurement": attributes.get("unit_of_measurement"),
            "attributes": attributes,
            "last_updated": payload.get("last_updated"),
        }

    def _read_cache(self) -> dict[str, Any]:
        """Lit un cache valide; un cache absent ou corrompu est simplement ignoré."""

        try:
            payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            LOGGER.exception("Impossible de lire le cache Home Assistant")
            return {}
        return payload if isinstance(payload, dict) else {}

    def _write_cache(self, cache_entries: dict[str, Any]) -> None:
        """Écrit le cache atomiquement pour ne jamais laisser un JSON partiel."""

        cache_payload = {
            **cache_entries,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "source_status": "live",
        }
        temporary_path: Path | None = None
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            with NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.cache_path.parent,
                prefix=f".{self.cache_path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary_file:
                json.dump(cache_payload, temporary_file, ensure_ascii=False, indent=2)
                temporary_file.write("\n")
                temporary_path = Path(temporary_file.name)
            os.replace(temporary_path, self.cache_path)
        except OSError:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            LOGGER.exception("Impossible d'écrire le cache Home Assistant")

    @staticmethod
    def _cached_measurement(
        cache: dict[str, Any], name: str
    ) -> dict[str, Any] | None:
        cached = cache.get(name)
        if not isinstance(cached, dict):
            return None
        value = cached.get("value")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return {
            "value": float(value),
            "unit": str(cached.get("unit") or DEFAULT_UNITS[name]),
            "ok": True,
            "cached": True,
            "last_updated": cached.get("last_updated"),
        }

    @staticmethod
    def _placeholder(name: str) -> dict[str, Any]:
        return {
            "value": None,
            "unit": DEFAULT_UNITS[name],
            "ok": False,
            "cached": False,
            "last_updated": None,
        }

    @staticmethod
    def _environment_canada_placeholder(
        name: str,
        *,
        is_text: bool,
    ) -> dict[str, Any]:
        if is_text:
            return {
                "value": None,
                "ok": False,
                "cached": False,
                "last_updated": None,
            }
        return {
            "value": None,
            "unit": EC_DEFAULT_UNITS.get(name, ""),
            "ok": False,
            "cached": False,
            "last_updated": None,
        }

    def _cached_environment_canada_measurement(
        self,
        cached: dict[str, Any],
        name: str,
        *,
        is_text: bool,
    ) -> dict[str, Any] | None:
        """Valide une mesure d’Environnement Canada présente dans le cache."""

        value = cached.get(name)
        if not isinstance(value, dict):
            return None

        raw_value = value.get("value")
        if is_text:
            if raw_value is None or _is_unavailable_value(raw_value):
                return None
            return {
                "value": str(raw_value),
                "ok": True,
                "cached": True,
                "last_updated": value.get("last_updated"),
            }

        if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
            return None
        numeric_value = float(raw_value)
        if not math.isfinite(numeric_value):
            return None

        return {
            "value": numeric_value,
            "unit": str(value.get("unit") or EC_DEFAULT_UNITS.get(name, "")),
            "ok": True,
            "cached": True,
            "last_updated": value.get("last_updated"),
        }

    @staticmethod
    def _build_alert_text(alerts: dict[str, int]) -> str | None:
        """Construit un message court à partir des compteurs actifs."""

        parts: list[str] = []
        labels = {
            "alerts": ("alerte", "alertes"),
            "advisories": ("avis", "avis"),
            "watches": ("veille", "veilles"),
            "bulletins": ("bulletin", "bulletins"),
        }
        for key, singular_plural in labels.items():
            count = alerts.get(key, 0)
            if count <= 0:
                continue
            singular, plural = singular_plural
            label = singular if count == 1 else plural
            parts.append(f"{count} {label}")
        if not parts:
            return None
        return " / ".join(parts)

    def _fetch_environment_canada_numeric(
        self,
        *,
        name: str,
        entity_id: str,
    ) -> dict[str, Any]:
        """Lit une mesure numérique d’Environnement Canada."""

        entity = self.fetch_entity(entity_id)
        raw_state = str(entity["state"]).strip()
        if _is_unavailable_value(raw_state):
            raise HomeAssistantError(
                f"état non disponible pour {entity_id or name}: {raw_state or 'vide'}"
            )
        numeric_value = _parse_float(raw_state)
        if numeric_value is None:
            raise HomeAssistantError(
                f"état non numérique pour {entity_id or name}: {raw_state}"
            )

        return {
            "value": numeric_value,
            "unit": str(entity["unit_of_measurement"] or EC_DEFAULT_UNITS.get(name, "")),
            "ok": True,
            "cached": False,
            "last_updated": entity["last_updated"],
        }

    def _fetch_environment_canada_text(
        self,
        *,
        name: str,
        entity_id: str,
    ) -> dict[str, Any]:
        """Lit une mesure texte d’Environnement Canada."""

        entity = self.fetch_entity(entity_id)
        raw_state = str(entity["state"]).strip()
        if _is_unavailable_value(raw_state):
            raise HomeAssistantError(
                f"état non disponible pour {entity_id or name}: {raw_state or 'vide'}"
            )
        return {
            "value": raw_state,
            "ok": True,
            "cached": False,
            "last_updated": entity["last_updated"],
        }

    def _fetch_environment_canada_alert_count(self, *, name: str, entity_id: str) -> int:
        """Lit un compteur d’alerte d’Environnement Canada."""

        entity = self.fetch_entity(entity_id)
        raw_state = str(entity["state"]).strip()
        if _is_unavailable_value(raw_state):
            raise HomeAssistantError(
                f"compteur d'alerte indisponible ({name}) : {raw_state or 'vide'}"
            )
        parsed = _parse_int(raw_state)
        if parsed is None:
            raise HomeAssistantError(
                f"compteur d'alerte non numérique ({name}) : {raw_state}"
            )
        if parsed < 0:
            raise HomeAssistantError(
                f"compteur d'alerte invalide ({name}) : {raw_state}"
            )
        return parsed

    @staticmethod
    def _build_alert_payload(
        weather_cache: dict[str, Any],
        counts: dict[str, int],
        source: str,
    ) -> dict[str, Any]:
        """Transforme des compteurs en structure attendue pour le rendu."""

        alerts_payload: dict[str, Any] = {
            "alerts": counts.get("alerts", 0),
            "advisories": counts.get("advisories", 0),
            "watches": counts.get("watches", 0),
            "bulletins": counts.get("bulletins", 0),
            "active": False,
            "text": None,
        }
        if any(value > 0 for value in alerts_payload.values() if isinstance(value, int)):
            alerts_payload["active"] = True
            alerts_payload["text"] = HomeAssistantClient._build_alert_text(
                counts
            )

        if (
            source in {"cache", "live", "fallback"}
            and isinstance(weather_cache.get("alerts"), dict)
        ):
            # Conserve un texte cohérent quand la lecture échoue après passage en cache.
            cached_text = weather_cache.get("alerts", {}).get("text")
            if not alerts_payload["active"] and isinstance(cached_text, str):
                alerts_payload["text"] = cached_text
                alerts_payload["active"] = bool(cached_text)

        return alerts_payload

    def _environment_canada_fallback(
        self,
        cache: dict[str, Any],
        *,
        error_message: str,
    ) -> dict[str, Any]:
        """Retourne le dernier relevé valide ou des placeholders Environnement Canada."""

        cached_environment = cache.get("environment_canada")
        if not isinstance(cached_environment, dict):
            cached_environment = {}

        result: dict[str, Any] = {}

        for name in EC_NUMERIC_FIELDS:
            cached = self._cached_environment_canada_measurement(
                cached_environment,
                name,
                is_text=False,
            )
            if cached is not None:
                result[name] = cached
            else:
                result[name] = self._environment_canada_placeholder(name, is_text=False)

        for name in EC_TEXT_FIELDS:
            cached = self._cached_environment_canada_measurement(
                cached_environment,
                name,
                is_text=True,
            )
            if cached is not None:
                result[name] = cached
            else:
                result[name] = self._environment_canada_placeholder(name, is_text=True)

        counts = {
            name: int(cached_environment.get("alerts", {}).get(name, 0))
            for name in EC_ALERT_FIELDS
        }
        if all(
            isinstance(value, (int, float))
            for value in counts.values()
        ):
            counts = {name: int(value) for name, value in counts.items()}
        else:
            counts = {name: 0 for name in EC_ALERT_FIELDS}
        result["alerts"] = self._build_alert_payload(
            cached_environment,
            counts,
            "fallback",
        )
        result["source"] = "fallback"
        result["error"] = error_message

        self._environment_canada_last_fetch_ok = False
        self._environment_canada_last_source = "fallback"
        condition_value = (
            result["condition"]["value"]
            if isinstance(result["condition"].get("value"), str)
            else "Données indisponibles"
        )
        self._environment_canada_last_condition = condition_value
        self._environment_canada_last_alert_active = bool(
            result["alerts"].get("active")
        )
        self._environment_canada_last_alert_text = result["alerts"].get("text")
        return result

    def _environment_canada_from_legacy(
        self,
        legacy_weather: dict[str, Any],
    ) -> dict[str, Any]:
        """Transforme l’ancienne structure météo en structure Environnement Canada."""

        condition_value = legacy_weather.get("condition_fr") or "Données indisponibles"
        result: dict[str, Any] = {
            "condition": {
                "value": condition_value,
                "ok": condition_value != "Données indisponibles",
            },
            "temperature": legacy_weather.get("temperature", {}).copy(),
            "humidity": legacy_weather.get("humidity", {}).copy(),
            "pressure": legacy_weather.get("pressure", {}).copy(),
            "wind_direction_text": {
                "value": str(legacy_weather.get("wind_bearing", {}).get("value", "")),
                "ok": bool(legacy_weather.get("wind_bearing", {}).get("ok", False)),
            },
            "wind_speed": legacy_weather.get("wind_speed", {}).copy(),
            "precip_probability": {"value": None, "unit": "%", "ok": False},
            "high_temp": {"value": None, "unit": "°C", "ok": False},
            "low_temp": {"value": None, "unit": "°C", "ok": False},
            "summary": {"value": None, "ok": False},
            "alerts": self._build_alert_payload({}, {"alerts": 0, "advisories": 0, "watches": 0, "bulletins": 0}, "fallback"),
            "source": "home_assistant_weather_legacy",
            "error": legacy_weather.get("error"),
        }

        self._environment_canada_last_fetch_ok = (
            legacy_weather.get("source") == "home_assistant"
        )
        self._environment_canada_last_source = "live"
        self._environment_canada_last_condition = condition_value
        self._environment_canada_last_alert_active = False
        self._environment_canada_last_alert_text = None
        return result

    def get_bme280_data(self) -> dict[str, Any]:
        """Retourne les trois mesures, en direct, depuis le cache ou en repli."""

        with self._lock:
            cache = self._read_cache()
            result: dict[str, Any] = {}
            cache_for_write = {
                name: value
                for name in MEASUREMENTS
                if isinstance((value := cache.get(name)), dict)
            }
            if isinstance(cache.get("weather"), dict):
                cache_for_write["weather"] = cache["weather"]
            if isinstance(cache.get("environment_canada"), dict):
                cache_for_write["environment_canada"] = cache["environment_canada"]
            errors: list[str] = []
            live_count = 0
            cache_count = 0

            for name, entity_id in self.config.entities.items():
                try:
                    entity = self.fetch_entity(entity_id)
                    state = str(entity["state"]).strip()
                    if _is_unavailable_value(state):
                        raise HomeAssistantError(
                            f"état non disponible pour {entity_id or name}: {state or 'vide'}"
                        )
                    numeric_value = _parse_float(state)
                    if numeric_value is None:
                        raise HomeAssistantError(
                            f"état non numérique pour {entity_id or name}: {state}"
                        )

                    measurement = {
                        "value": numeric_value,
                        "unit": str(entity["unit_of_measurement"] or DEFAULT_UNITS[name]),
                        "ok": True,
                        "cached": False,
                        "last_updated": entity["last_updated"],
                    }
                    result[name] = measurement
                    cache_for_write[name] = {
                        "value": numeric_value,
                        "unit": measurement["unit"],
                        "last_updated": measurement["last_updated"],
                    }
                    live_count += 1
                except HomeAssistantError as error:
                    message = f"{name}: {error}"
                    errors.append(message)
                    LOGGER.warning("Lecture BME280 impossible (%s)", message)
                    cached = self._cached_measurement(cache, name)
                    if cached is not None:
                        result[name] = cached
                        cache_count += 1
                    else:
                        result[name] = self._placeholder(name)
                except Exception:
                    message = f"{name}: erreur Home Assistant inattendue"
                    errors.append(message)
                    LOGGER.exception("Lecture BME280 impossible (%s)", message)
                    cached = self._cached_measurement(cache, name)
                    if cached is not None:
                        result[name] = cached
                        cache_count += 1
                    else:
                        result[name] = self._placeholder(name)

            if live_count or cache_count:
                self._write_cache(cache_for_write)

            all_live = live_count == len(MEASUREMENTS)
            if all_live:
                source = "live"
            elif cache_count:
                source = "cache"
            else:
                source = "fallback"

            self._last_fetch_ok = all_live
            self._last_source = source
            result.update(
                source=source,
                error="; ".join(errors) if errors else None,
            )
            return result

    @staticmethod
    def _weather_unit(attributes: dict[str, Any], name: str) -> str:
        """Retourne l'unité météo fournie par Home Assistant ou son repli."""

        unit_attribute = WEATHER_UNIT_ATTRIBUTES[name]
        if unit_attribute:
            supplied_unit = attributes.get(unit_attribute)
            if supplied_unit:
                return str(supplied_unit)
        return WEATHER_DEFAULT_UNITS[name]

    @classmethod
    def _weather_placeholder(
        cls,
        name: str,
        attributes: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Crée une mesure météo absente en conservant son unité si connue."""

        unit = cls._weather_unit(attributes or {}, name)
        measurement: dict[str, Any] = {
            "value": None,
            "ok": False,
            "cached": False,
            "last_updated": None,
        }
        if unit or name in {"temperature", "humidity", "pressure", "wind_speed"}:
            measurement["unit"] = unit
        return measurement

    @classmethod
    def _live_weather_measurement(
        cls,
        attributes: dict[str, Any],
        name: str,
        last_updated: Any,
    ) -> dict[str, Any] | None:
        """Valide et normalise un attribut numérique de l'entité météo."""

        raw_value = attributes.get(name)
        if isinstance(raw_value, bool) or raw_value is None:
            return None
        numeric_value = _parse_float(raw_value)
        if numeric_value is None:
            return None

        unit = cls._weather_unit(attributes, name)
        measurement: dict[str, Any] = {
            "value": numeric_value,
            "ok": True,
            "cached": False,
            "last_updated": last_updated,
        }
        if unit or name in {"temperature", "humidity", "pressure", "wind_speed"}:
            measurement["unit"] = unit
        return measurement

    @classmethod
    def _cached_weather_measurement(
        cls,
        cached_weather: dict[str, Any],
        name: str,
    ) -> dict[str, Any] | None:
        """Valide une mesure de la section météo du cache local."""

        cached = cached_weather.get(name)
        if not isinstance(cached, dict):
            return None
        value = cached.get("value")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        numeric_value = float(value)
        if not math.isfinite(numeric_value):
            return None

        measurement: dict[str, Any] = {
            "value": numeric_value,
            "ok": True,
            "cached": True,
            "last_updated": cached.get("last_updated"),
        }
        unit = str(cached.get("unit") or WEATHER_DEFAULT_UNITS[name])
        if unit or name in {"temperature", "humidity", "pressure", "wind_speed"}:
            measurement["unit"] = unit
        return measurement

    def _weather_fallback(
        self,
        cache: dict[str, Any],
        error_message: str,
    ) -> dict[str, Any]:
        """Retourne la dernière météo valide ou des placeholders présentables."""

        cached_weather = cache.get("weather")
        if isinstance(cached_weather, dict):
            condition_raw = str(cached_weather.get("condition_raw") or "").strip()
        else:
            condition_raw = ""

        if condition_raw and condition_raw.lower() not in {"unknown", "unavailable"}:
            result: dict[str, Any] = {
                "condition_raw": condition_raw,
                "condition_fr": translate_weather_condition(condition_raw),
            }
            for name in WEATHER_MEASUREMENTS:
                measurement = self._cached_weather_measurement(cached_weather, name)
                if measurement is None:
                    result[name] = self._weather_placeholder(name)
                else:
                    result[name] = measurement

            result.update(source="cache", error=error_message)
            self._weather_last_source = "cache"
            self._weather_condition_raw = condition_raw
            self._weather_condition_fr = result["condition_fr"]
            return result

        result = {
            "condition_raw": None,
            "condition_fr": "Données indisponibles",
        }
        for name in WEATHER_MEASUREMENTS:
            result[name] = self._weather_placeholder(name)
        result.update(source="fallback", error=error_message)
        self._weather_last_source = "fallback"
        self._weather_condition_raw = None
        self._weather_condition_fr = "Données indisponibles"
        return result

    def get_weather_data(self) -> dict[str, Any]:
        """Retourne la météo actuelle en direct, depuis le cache ou en repli."""

        with self._lock:
            cache = self._read_cache()
            entity_id = self.config.weather_entity
            try:
                entity = self.fetch_entity(entity_id)
                condition_raw = str(entity.get("state") or "").strip()
                if _is_unavailable_value(condition_raw):
                    raise HomeAssistantError(
                        "état météo non disponible pour "
                        f"{entity_id or 'l’entité configurée'}: {condition_raw or 'vide'}"
                    )

                attributes = entity.get("attributes")
                if not isinstance(attributes, dict):
                    attributes = {}
                last_updated = entity.get("last_updated")
                result: dict[str, Any] = {
                    "condition_raw": condition_raw,
                    "condition_fr": translate_weather_condition(condition_raw),
                }
                attribute_errors: list[str] = []

                cached_weather = cache.get("weather")
                if not isinstance(cached_weather, dict):
                    cached_weather = {}
                weather_for_cache = {
                    **cached_weather,
                    "condition_raw": condition_raw,
                    "condition_fr": result["condition_fr"],
                    "last_updated": last_updated,
                }

                for name in WEATHER_MEASUREMENTS:
                    measurement = self._live_weather_measurement(
                        attributes, name, last_updated
                    )
                    if measurement is None:
                        result[name] = self._weather_placeholder(name, attributes)
                        attribute_errors.append(
                            f"attribut météo invalide ou absent: {name}"
                        )
                        continue
                    result[name] = measurement
                    weather_for_cache[name] = {
                        key: value
                        for key, value in measurement.items()
                        if key in {"value", "unit", "last_updated"}
                    }

                cache_for_write = {
                    name: value
                    for name in MEASUREMENTS
                    if isinstance((value := cache.get(name)), dict)
                }
                if isinstance(cache.get("environment_canada"), dict):
                    cache_for_write["environment_canada"] = cache["environment_canada"]
                cache_for_write["weather"] = weather_for_cache
                self._write_cache(cache_for_write)

                if attribute_errors:
                    LOGGER.warning(
                        "Lecture météo Home Assistant partielle (%s)",
                        "; ".join(attribute_errors),
                    )
                self._weather_last_fetch_ok = True
                self._weather_last_source = "live"
                self._weather_condition_raw = condition_raw
                self._weather_condition_fr = result["condition_fr"]
                result.update(
                    source="home_assistant",
                    error="; ".join(attribute_errors) if attribute_errors else None,
                )
                return result
            except HomeAssistantError as error:
                message = str(error)
                LOGGER.warning("Lecture météo Home Assistant impossible (%s)", message)
            except Exception:
                message = "erreur Home Assistant inattendue"
                LOGGER.exception("Lecture météo Home Assistant impossible (%s)", message)

            self._weather_last_fetch_ok = False
            return self._weather_fallback(cache, message)

    def get_environment_canada_data(self) -> dict[str, Any]:
        """Retourne la météo Environnement Canada en direct, puis via cache."""

        if not self.config.environment_canada_configured:
            legacy_weather = self.get_weather_data()
            return self._environment_canada_from_legacy(legacy_weather)

        with self._lock:
            cache = self._read_cache()
            ec_cache = cache.get("environment_canada")
            if not isinstance(ec_cache, dict):
                ec_cache = {}
            errors: list[str] = []
            measurement: dict[str, Any] = {}
            cached_count = 0
            live_count = 0
            cache_for_write = {
                name: value
                for name in MEASUREMENTS
                if isinstance((value := cache.get(name)), dict)
            }
            if isinstance(cache.get("weather"), dict):
                cache_for_write["weather"] = cache["weather"]

            try:
                # L'entité météo principale est conservée pour rester compatible
                # avec la configuration historique; elle ne remplace pas `condition`.
                self.fetch_entity(self.config.ec_weather_entity)
            except HomeAssistantError as error:
                errors.append(f"weather: {error}")
            except Exception:
                errors.append("weather: erreur Home Assistant inattendue")

            for name in EC_NUMERIC_FIELDS:
                entity_id = getattr(self.config, f"ec_{name}_entity")
                try:
                    value = self._fetch_environment_canada_numeric(
                        name=name,
                        entity_id=entity_id,
                    )
                    measurement[name] = value
                    live_count += 1
                except HomeAssistantError as error:
                    errors.append(f"{name}: {error}")
                    cached = self._cached_environment_canada_measurement(
                        ec_cache,
                        name,
                        is_text=False,
                    )
                    if cached is not None:
                        measurement[name] = cached
                        cached_count += 1
                    else:
                        measurement[name] = self._environment_canada_placeholder(
                            name,
                            is_text=False,
                        )
                except Exception:
                    errors.append(f"{name}: erreur Home Assistant inattendue")
                    LOGGER.exception("Lecture Environnement Canada impossible (%s)", name)
                    cached = self._cached_environment_canada_measurement(
                        ec_cache,
                        name,
                        is_text=False,
                    )
                    if cached is not None:
                        measurement[name] = cached
                        cached_count += 1
                    else:
                        measurement[name] = self._environment_canada_placeholder(
                            name,
                            is_text=False,
                        )

            for name in EC_TEXT_FIELDS:
                entity_id = getattr(self.config, f"ec_{name}_entity")
                try:
                    value = self._fetch_environment_canada_text(
                        name=name,
                        entity_id=entity_id,
                    )
                    measurement[name] = value
                    live_count += 1
                except HomeAssistantError as error:
                    errors.append(f"{name}: {error}")
                    cached = self._cached_environment_canada_measurement(
                        ec_cache,
                        name,
                        is_text=True,
                    )
                    if cached is not None:
                        measurement[name] = cached
                        cached_count += 1
                    else:
                        measurement[name] = self._environment_canada_placeholder(
                            name, is_text=True
                        )
                except Exception:
                    errors.append(f"{name}: erreur Home Assistant inattendue")
                    LOGGER.exception("Lecture Environnement Canada impossible (%s)", name)
                    cached = self._cached_environment_canada_measurement(
                        ec_cache,
                        name,
                        is_text=True,
                    )
                    if cached is not None:
                        measurement[name] = cached
                        cached_count += 1
                    else:
                        measurement[name] = self._environment_canada_placeholder(
                            name,
                            is_text=True,
                        )

            alerts_cache = ec_cache.get("alerts")
            if not isinstance(alerts_cache, dict):
                alerts_cache = {}
            alert_counts: dict[str, int] = {
                key: int(alerts_cache.get(key, 0))
                for key in EC_ALERT_FIELDS
            }
            for key in EC_ALERT_FIELDS:
                entity_id = getattr(self.config, f"ec_{key}_entity")
                try:
                    alert_counts[key] = self._fetch_environment_canada_alert_count(
                        name=key,
                        entity_id=entity_id,
                    )
                    live_count += 1
                except HomeAssistantError as error:
                    errors.append(f"{key}: {error}")
                    if key in alerts_cache and isinstance(alerts_cache.get(key), int):
                        cached_count += 1
                    else:
                        alert_counts[key] = 0
                except Exception:
                    errors.append(f"{key}: erreur Home Assistant inattendue")
                    LOGGER.exception("Lecture des compteurs d'alerte impossible (%s)", key)
                    if key in alerts_cache and isinstance(alerts_cache.get(key), int):
                        cached_count += 1
                    else:
                        alert_counts[key] = 0

            source = "live"
            expected_successes = len(EC_NUMERIC_FIELDS) + len(EC_TEXT_FIELDS) + len(
                EC_ALERT_FIELDS
            )
            if live_count < expected_successes:
                source = "cache" if cached_count else "fallback"

            alerts_payload = self._build_alert_payload(
                ec_cache,
                alert_counts,
                source,
            )

            environment_canada_cache = {}
            for key in EC_NUMERIC_FIELDS:
                if not measurement[key].get("ok"):
                    continue
                environment_canada_cache[key] = {
                    "value": measurement[key]["value"],
                    "unit": measurement[key].get("unit"),
                    "ok": measurement[key]["ok"],
                    "cached": measurement[key].get("cached", False),
                    "last_updated": measurement[key].get("last_updated"),
                }
            for key in EC_TEXT_FIELDS:
                if measurement[key].get("ok"):
                    environment_canada_cache[key] = {
                        "value": measurement[key]["value"],
                        "ok": measurement[key]["ok"],
                        "cached": measurement[key].get("cached", False),
                        "last_updated": measurement[key].get("last_updated"),
                    }
            environment_canada_cache["alerts"] = alert_counts
            environment_canada_cache["alerts_text"] = alerts_payload.get("text")
            cache_for_write["environment_canada"] = environment_canada_cache
            if live_count or cached_count:
                self._write_cache(cache_for_write)

            self._environment_canada_last_fetch_ok = source == "live"
            self._environment_canada_last_source = source
            condition_value = measurement["condition"]["value"]
            if isinstance(condition_value, str):
                self._environment_canada_last_condition = condition_value
            else:
                self._environment_canada_last_condition = "Données indisponibles"
            self._environment_canada_last_alert_active = bool(
                alerts_payload.get("active")
            )
            self._environment_canada_last_alert_text = alerts_payload.get("text")

            result: dict[str, Any] = {
                "condition": measurement["condition"],
                "temperature": measurement["temperature"],
                "humidity": measurement["humidity"],
                "pressure": measurement["pressure"],
                "wind_direction_text": measurement["wind_direction_text"],
                "wind_speed": measurement["wind_speed"],
                "precip_probability": measurement["precip_probability"],
                "high_temp": measurement["high_temp"],
                "low_temp": measurement["low_temp"],
                "summary": measurement["summary"],
                "alerts": alerts_payload,
                "source": "home_assistant_environment_canada",
                "error": "; ".join(errors) if errors else None,
            }
            return result

    def health_status(self) -> dict[str, Any]:
        """Expose l'état courant sans jamais inclure le jeton d'accès."""

        return {
            "configured": self.config.configured,
            "last_fetch_ok": self._last_fetch_ok,
            "source": self._last_source,
            "entities": self.config.entities,
        }

    def weather_health_status(self) -> dict[str, Any]:
        """Expose le diagnostic météo sans jamais inclure le jeton d'accès."""

        return {
            "configured": self.config.weather_configured,
            "entity_id": self.config.weather_entity,
            "last_fetch_ok": self._weather_last_fetch_ok,
            "source": self._weather_last_source,
            "condition_raw": self._weather_condition_raw,
            "condition_fr": self._weather_condition_fr,
        }

    def environment_canada_health_status(self) -> dict[str, Any]:
        """Expose le diagnostic Environnement Canada sans jamais inclure le jeton."""

        return {
            "configured": self.config.environment_canada_configured,
            "last_fetch_ok": self._environment_canada_last_fetch_ok,
            "source": self._environment_canada_last_source,
            "condition": self._environment_canada_last_condition,
            "alert_active": self._environment_canada_last_alert_active,
            "alert_text": self._environment_canada_last_alert_text,
            "entities": self.config.environment_canada_entities,
        }
