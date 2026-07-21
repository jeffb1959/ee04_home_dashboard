"""Configuration locale du tableau de bord, sans secret dans le code."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping


PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_ENV_FILE = PROJECT_DIR / ".env"


def _read_env_file(path: Path) -> dict[str, str]:
    """Lit le sous-ensemble simple du format dotenv utilisé par le projet."""

    values: dict[str, str] = {}
    if not path.is_file():
        return values

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return values

    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()

        name, value = line.split("=", 1)
        name = name.strip()
        value = value.strip()
        if not name:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[name] = value

    return values


@dataclass(frozen=True)
class HomeAssistantConfig:
    """Paramètres nécessaires aux lectures Home Assistant du tableau de bord."""

    url: str
    token: str = field(repr=False)
    temperature_entity: str
    humidity_entity: str
    pressure_entity: str
    weather_entity: str = ""
    ec_weather_entity: str = ""
    ec_condition_entity: str = ""
    ec_temperature_entity: str = ""
    ec_humidity_entity: str = ""
    ec_pressure_entity: str = ""
    ec_wind_direction_text_entity: str = ""
    ec_wind_speed_entity: str = ""
    ec_precip_probability_entity: str = ""
    ec_high_temp_entity: str = ""
    ec_low_temp_entity: str = ""
    ec_summary_entity: str = ""
    ec_alerts_entity: str = ""
    ec_advisories_entity: str = ""
    ec_watches_entity: str = ""
    ec_bulletins_entity: str = ""

    @property
    def configured(self) -> bool:
        """Indique si tous les paramètres obligatoires sont présents."""

        return all(
            (
                self.url,
                self.token,
                self.temperature_entity,
                self.humidity_entity,
                self.pressure_entity,
            )
        )

    @property
    def entities(self) -> dict[str, str]:
        """Retourne les identifiants non sensibles utilisés par le client."""

        return {
            "temperature": self.temperature_entity,
            "humidity": self.humidity_entity,
            "pressure": self.pressure_entity,
        }

    @property
    def environment_canada_entities(self) -> dict[str, str]:
        """Retourne les identifiants Environnement Canada utilisés par le client."""

        return {
            "weather": self.ec_weather_entity,
            "condition": self.ec_condition_entity,
            "temperature": self.ec_temperature_entity,
            "humidity": self.ec_humidity_entity,
            "pressure": self.ec_pressure_entity,
            "wind_direction_text": self.ec_wind_direction_text_entity,
            "wind_speed": self.ec_wind_speed_entity,
            "precip_probability": self.ec_precip_probability_entity,
            "high_temp": self.ec_high_temp_entity,
            "low_temp": self.ec_low_temp_entity,
            "summary": self.ec_summary_entity,
            "alerts": self.ec_alerts_entity,
            "advisories": self.ec_advisories_entity,
            "watches": self.ec_watches_entity,
            "bulletins": self.ec_bulletins_entity,
        }

    @property
    def weather_configured(self) -> bool:
        """Indique si la source météo principale peut être interrogée."""

        return bool(self.url and self.token and self.weather_entity)

    @property
    def environment_canada_configured(self) -> bool:
        """Indique si la source Environnement Canada peut être interrogée."""

        return all(
            (
                self.url,
                self.token,
                self.ec_weather_entity,
                self.ec_condition_entity,
                self.ec_temperature_entity,
                self.ec_humidity_entity,
                self.ec_pressure_entity,
                self.ec_wind_direction_text_entity,
                self.ec_wind_speed_entity,
                self.ec_precip_probability_entity,
                self.ec_high_temp_entity,
                self.ec_low_temp_entity,
                self.ec_summary_entity,
                self.ec_alerts_entity,
                self.ec_advisories_entity,
                self.ec_watches_entity,
                self.ec_bulletins_entity,
            )
        )


def load_home_assistant_config(
    env_file: str | Path = DEFAULT_ENV_FILE,
    environ: Mapping[str, str] | None = None,
) -> HomeAssistantConfig:
    """Charge `.env`, puis laisse les variables du processus les surcharger."""

    file_values = _read_env_file(Path(env_file))
    process_values = os.environ if environ is None else environ

    def get_value(name: str) -> str:
        return process_values.get(name, file_values.get(name, "")).strip()

    return HomeAssistantConfig(
        url=get_value("HOME_ASSISTANT_URL").rstrip("/"),
        token=get_value("HOME_ASSISTANT_TOKEN"),
        temperature_entity=get_value("HA_ENTITY_TEMPERATURE"),
        humidity_entity=get_value("HA_ENTITY_HUMIDITY"),
        pressure_entity=get_value("HA_ENTITY_PRESSURE"),
        weather_entity=get_value("HA_ENTITY_WEATHER"),
        ec_weather_entity=get_value("HA_EC_WEATHER_ENTITY"),
        ec_condition_entity=get_value("HA_EC_CONDITION"),
        ec_temperature_entity=get_value("HA_EC_TEMPERATURE"),
        ec_humidity_entity=get_value("HA_EC_HUMIDITY"),
        ec_pressure_entity=get_value("HA_EC_PRESSURE"),
        ec_wind_direction_text_entity=get_value("HA_EC_WIND_DIRECTION_TEXT"),
        ec_wind_speed_entity=get_value("HA_EC_WIND_SPEED"),
        ec_precip_probability_entity=get_value("HA_EC_PRECIP_PROBABILITY"),
        ec_high_temp_entity=get_value("HA_EC_HIGH_TEMP"),
        ec_low_temp_entity=get_value("HA_EC_LOW_TEMP"),
        ec_summary_entity=get_value("HA_EC_SUMMARY"),
        ec_alerts_entity=get_value("HA_EC_ALERTS"),
        ec_advisories_entity=get_value("HA_EC_ADVISORIES"),
        ec_watches_entity=get_value("HA_EC_WATCHES"),
        ec_bulletins_entity=get_value("HA_EC_BULLETINS"),
    )
