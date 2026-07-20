"""Client REST minimal et résilient pour le BME280 de Home Assistant."""

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


class HomeAssistantError(RuntimeError):
    """Erreur attendue et présentable sans information sensible."""


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

    def fetch_entity(self, entity_id: str) -> dict[str, str | None]:
        """Retourne l'état brut d'une entité depuis l'API REST Home Assistant."""

        if not self.config.url or not self.config.token:
            raise HomeAssistantError("configuration Home Assistant incomplète")
        if not entity_id:
            raise HomeAssistantError("identifiant d'entité Home Assistant absent")

        entity_url = (
            f"{self.config.url}/api/states/{quote(entity_id, safe='')}"
        )
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

    def _write_cache(self, measurements: dict[str, dict[str, Any]]) -> None:
        """Écrit le cache atomiquement pour ne jamais laisser un JSON partiel."""

        cache_payload = {
            **measurements,
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
            errors: list[str] = []
            live_count = 0
            cache_count = 0

            for name, entity_id in self.config.entities.items():
                try:
                    entity = self.fetch_entity(entity_id)
                    state = str(entity["state"]).strip()
                    if state.lower() in {"unknown", "unavailable", ""}:
                        raise HomeAssistantError(
                            f"état non disponible pour {entity_id or name}: {state or 'vide'}"
                        )
                    try:
                        numeric_value = float(state)
                    except ValueError as error:
                        raise HomeAssistantError(
                            f"état non numérique pour {entity_id or name}: {state}"
                        ) from error
                    if not math.isfinite(numeric_value):
                        raise HomeAssistantError(
                            f"état non numérique pour {entity_id or name}: {state}"
                        )

                    measurement = {
                        "value": numeric_value,
                        "unit": str(
                            entity["unit_of_measurement"] or DEFAULT_UNITS[name]
                        ),
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
                    # Une réponse ou une panne réseau inattendue ne doit jamais
                    # interrompre le rendu Flask.
                    message = f"{name}: erreur Home Assistant inattendue"
                    errors.append(message)
                    LOGGER.exception("Lecture BME280 impossible (%s)", message)
                    cached = self._cached_measurement(cache, name)
                    if cached is not None:
                        result[name] = cached
                        cache_count += 1
                    else:
                        result[name] = self._placeholder(name)

            if live_count:
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

    def health_status(self) -> dict[str, Any]:
        """Expose l'état courant sans jamais inclure le jeton d'accès."""

        return {
            "configured": self.config.configured,
            "last_fetch_ok": self._last_fetch_ok,
            "source": self._last_source,
            "entities": self.config.entities,
        }
