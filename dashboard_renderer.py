"""Composition visuelle du tableau de bord EE04 (phase 1.6C)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, time
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError

from activity_service import ActivityInfo


PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_BACKGROUND_PATH = PROJECT_DIR / "assets" / "backgrounds" / "lundi_beau.png"

IMAGE_SIZE = (800, 480)
BACKGROUND_SIZE = (800, 360)
BOTTOM_BAND_HEIGHT = 120
FALLBACK_COLOR = (247, 240, 219)
TEXT_COLOR = (61, 46, 35)
MUTED_TEXT_COLOR = (104, 79, 55)
WEATHER_PANEL_FILL = (255, 249, 231, 208)
PANEL_OUTLINE = (143, 96, 45, 150)
BOTTOM_BAND_COLOR = (255, 249, 231)
SEPARATOR_COLOR = (177, 132, 79)
ALERT_BANNER_BACKGROUND = (204, 24, 34)
ALERT_BANNER_TEXT_LIGHT = (255, 255, 255)
ALERT_BANNER_TEXT_DARK = (20, 20, 20)

FRENCH_WEEKDAYS = (
    "lundi",
    "mardi",
    "mercredi",
    "jeudi",
    "vendredi",
    "samedi",
    "dimanche",
)
FRENCH_MONTHS = (
    "janvier",
    "février",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "août",
    "septembre",
    "octobre",
    "novembre",
    "décembre",
)


@dataclass(frozen=True)
class DashboardDiagnostics:
    """Informations techniques affichables, fournies par la couche Flask."""

    screen_rssi: int | None
    generated_at: datetime
    mail_updated_at: datetime | None


def load_font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Charge une police Unicode du Pi, puis la police Pillow en repli."""

    filenames = (
        ("DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf", "FreeSansBold.ttf")
        if bold
        else ("DejaVuSans.ttf", "LiberationSans-Regular.ttf", "FreeSans.ttf")
    )
    font_directories = (
        Path("/usr/share/fonts/truetype/dejavu"),
        Path("/usr/share/fonts/dejavu"),
        Path("/usr/share/fonts/truetype/liberation2"),
        Path("/usr/share/fonts/truetype/freefont"),
        PROJECT_DIR / "assets" / "fonts",
    )

    for directory in font_directories:
        for filename in filenames:
            try:
                return ImageFont.truetype(str(directory / filename), size=size)
            except (OSError, ValueError):
                continue

    # Ultime repli si les polices système et la copie locale sont absentes.
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _fallback_background(background_path: Path) -> Image.Image:
    """Crée un fond clair et explicite lorsque le fichier est indisponible."""

    image = Image.new("RGB", BACKGROUND_SIZE, FALLBACK_COLOR)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        (32, 45, 470, 185),
        radius=18,
        fill=(255, 252, 241),
        outline=(176, 132, 82),
        width=2,
    )
    draw.text(
        (55, 72),
        "ARRIÈRE-PLAN INTROUVABLE",
        font=load_font(25, bold=True),
        fill=TEXT_COLOR,
    )
    draw.text(
        (55, 115),
        "Image de secours utilisée",
        font=load_font(19),
        fill=MUTED_TEXT_COLOR,
    )
    draw.text(
        (55, 148),
        background_path.name,
        font=load_font(15),
        fill=MUTED_TEXT_COLOR,
    )
    return image


def _load_background(background_path: Path) -> Image.Image:
    """Charge le fond et l'adapte sans déformer son ratio."""

    try:
        with Image.open(background_path) as source:
            source.load()
            source_rgb = source.convert("RGB")

        if source_rgb.size == BACKGROUND_SIZE:
            return source_rgb

        # LANCZOS préserve les détails; ImageOps.fit conserve le ratio et ne
        # recadre que ce qui dépasse de la zone supérieure 800 x 360.
        return ImageOps.fit(
            source_rgb,
            BACKGROUND_SIZE,
            method=Image.Resampling.LANCZOS,
            # Le cadrage légèrement relevé préserve le haut de l'illustration.
            centering=(0.5, 0.35),
        )
    except (OSError, ValueError, UnidentifiedImageError):
        return _fallback_background(background_path)


def _compose_canvas(background: Image.Image) -> Image.Image:
    """Assemble l'illustration supérieure et la bande inférieure opaque."""

    image = Image.new("RGB", IMAGE_SIZE, BOTTOM_BAND_COLOR)
    image.paste(background, (0, 0))

    draw = ImageDraw.Draw(image)
    draw.line(
        (0, BACKGROUND_SIZE[1], IMAGE_SIZE[0], BACKGROUND_SIZE[1]),
        fill=SEPARATOR_COLOR,
        width=2,
    )
    return image


def _add_weather_panel(image: Image.Image) -> Image.Image:
    """Ajoute un panneau météo léger dans la partie illustrée."""
    card_x = 485
    card_y = 30
    card_width = 300
    card_height = 300

    overlay = Image.new("RGBA", IMAGE_SIZE, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    draw.rounded_rectangle(
        (card_x, card_y, card_x + card_width - 1, card_y + card_height - 1),
        radius=16,
        fill=WEATHER_PANEL_FILL,
        outline=PANEL_OUTLINE,
        width=1,
    )

    return Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")


def _format_measurement(data: Mapping[str, Any] | None, name: str) -> tuple[str, str]:
    """Formate une mesure BME280 ou son placeholder lisible."""

    default_units = {"temperature": "°C", "humidity": "%", "pressure": "hPa"}
    placeholders = {"temperature": "--", "humidity": "--", "pressure": "----"}
    measurement = data.get(name, {}) if data else {}
    unit = str(measurement.get("unit") or default_units[name])
    value = measurement.get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return placeholders[name], unit

    if name == "temperature":
        formatted = f"{value:.1f}".replace(".", ",")
        if formatted.endswith(",0"):
            formatted = formatted[:-2]
    else:
        formatted = f"{value:.0f}"
    return formatted, unit


def _format_weather_measurement(
    data: Mapping[str, Any] | None,
    name: str,
) -> tuple[str, str]:
    """Formate une mesure de l'entité météo avec une virgule décimale."""

    default_units = {"temperature": "°C", "humidity": "%", "pressure": ""}
    placeholders = {"temperature": "--", "humidity": "--", "pressure": "--"}
    measurement = data.get(name, {}) if data else {}
    unit = str(measurement.get("unit") or default_units[name])
    value = measurement.get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return placeholders[name], unit

    if name == "temperature":
        formatted = f"{value:.1f}".rstrip("0").rstrip(".")
    elif name == "humidity":
        formatted = f"{value:.0f}"
    else:
        formatted = f"{value:.2f}".rstrip("0").rstrip(".")
    return formatted.replace(".", ","), unit


def _format_environment_canada_measurement(
    data: Mapping[str, Any] | None,
    name: str,
) -> tuple[str, str]:
    """Formate les mesures Environnement Canada de façon lisible sur l'écran."""

    numeric_defaults = {
        "temperature": "--",
        "humidity": "--",
        "pressure": "--",
        "wind_speed": "--",
        "precip_probability": "--",
        "high_temp": "--",
        "low_temp": "--",
    }
    text_defaults = {
        "condition": "Données indisponibles",
        "wind_direction_text": "—",
        "summary": "",
    }
    measurement = data.get(name, {}) if data else {}
    value = measurement.get("value")
    unit = str(measurement.get("unit") or "").strip()

    if name in {"condition", "wind_direction_text", "summary"}:
        if isinstance(value, str) and value.strip():
            return value.strip(), unit
        return text_defaults[name], unit

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return numeric_defaults.get(name, "--"), unit

    if name in {"temperature", "high_temp", "low_temp"}:
        formatted = f"{value:.1f}".replace(".", ",")
        if formatted.endswith(",0"):
            formatted = formatted[:-2]
        return formatted, unit
    if name in {"humidity", "precip_probability"}:
        return f"{value:.0f}", unit
    return f"{value:.0f}", unit


def _contrast_text_color(background: tuple[int, int, int]) -> tuple[int, int, int]:
    """Choisit blanc/noir selon la luminance d'un fond."""

    red, green, blue = background
    luminance = 0.299 * red + 0.587 * green + 0.114 * blue
    return ALERT_BANNER_TEXT_DARK if luminance > 160 else ALERT_BANNER_TEXT_LIGHT


def _fit_weather_condition(
    draw: ImageDraw.ImageDraw,
    condition: str,
    max_width: int = 232,
) -> tuple[str, ImageFont.FreeTypeFont | ImageFont.ImageFont]:
    """Réduit puis tronque une condition pour la garder dans le panneau."""

    for size in range(19, 12, -1):
        font = load_font(size)
        if draw.textlength(condition, font=font) <= max_width:
            return condition, font

    font = load_font(13)
    shortened = condition
    while shortened and draw.textlength(f"{shortened}…", font=font) > max_width:
        shortened = shortened[:-1]
    return f"{shortened.rstrip()}…", font


def _fit_single_line_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    max_width: int,
    *,
    min_size: int = 11,
    max_size: int = 16,
) -> tuple[str, ImageFont.FreeTypeFont | ImageFont.ImageFont]:
    """Ajuste la taille puis tronque proprement un texte sur une ligne."""

    for size in range(max_size, min_size - 1, -1):
        font = load_font(size, bold=True)
        if draw.textlength(text, font=font) <= max_width:
            return text, font

    font = load_font(min_size, bold=True)
    trimmed = text
    while trimmed and draw.textlength(f"{trimmed}…", font=font) > max_width:
        trimmed = trimmed[:-1]
    return f"{trimmed.rstrip()}…", font


def _draw_alert_banner(draw: ImageDraw.ImageDraw, alert_text: str) -> int:
    """Dessine un bandeau rouge unique en haut d'écran lorsque nécessaire."""

    full_text = f"ALERTE MÉTÉO : {alert_text}"
    fit_text, fit_font = _fit_single_line_text(
        draw,
        full_text,
        max_width=770,
        min_size=12,
        max_size=24,
    )

    banner_height = 36
    draw.rectangle((0, 0, 799, banner_height - 1), fill=ALERT_BANNER_BACKGROUND)
    text_color = _contrast_text_color(ALERT_BANNER_BACKGROUND)
    draw.text((12, 8), fit_text, font=fit_font, fill=text_color)
    return banner_height


def _draw_weather(
    draw: ImageDraw.ImageDraw,
    bme280_data: Mapping[str, Any] | None,
    weather_data: Mapping[str, Any] | None,
) -> None:
    """Dessine la météo principale et les mesures extérieures BME280."""

    alerts = (weather_data or {}).get("alerts") if weather_data else {}
    if isinstance(alerts, Mapping):
        if alerts.get("active") and alerts.get("text"):
            _draw_alert_banner(draw, str(alerts.get("text")))

    condition_data = (weather_data or {}).get("condition", {})
    condition = str(condition_data.get("value") or "Données indisponibles")

    weather_temperature, weather_temperature_unit = (
        _format_environment_canada_measurement(weather_data, "temperature")
    )
    weather_humidity, weather_humidity_unit = (
        _format_environment_canada_measurement(weather_data, "humidity")
    )
    weather_pressure, weather_pressure_unit = (
        _format_environment_canada_measurement(weather_data, "pressure")
    )
    weather_precip, weather_precip_unit = (
        _format_environment_canada_measurement(weather_data, "precip_probability")
    )
    weather_low_temp, weather_temp_unit = _format_environment_canada_measurement(
        weather_data, "low_temp"
    )
    weather_high_temp, _ = _format_environment_canada_measurement(weather_data, "high_temp")
    weather_wind_direction, _ = _format_environment_canada_measurement(
        weather_data, "wind_direction_text"
    )
    weather_wind_speed, weather_wind_unit = (
        _format_environment_canada_measurement(weather_data, "wind_speed")
    )

    temperature, temperature_unit = _format_measurement(bme280_data, "temperature")
    humidity, humidity_unit = _format_measurement(bme280_data, "humidity")
    pressure, pressure_unit = _format_measurement(bme280_data, "pressure")

    card_x = 485
    card_y = 30
    card_width = 300
    card_height = 300
    content_x = card_x + 14
    content_right = card_x + card_width - 12
    content_width = content_right - content_x

    section_title_font = load_font(14, bold=True)
    main_title = "CONDITIONS ACTUELLES"
    section_title_y = card_y + 14
    draw.text(
        (content_x, section_title_y),
        main_title,
        font=section_title_font,
        fill=MUTED_TEXT_COLOR,
    )
    section_title_bbox = draw.textbbox((content_x, section_title_y), main_title, font=section_title_font)

    main_temp_text, main_temp_font = _fit_single_line_text(
        draw,
        f"{weather_temperature} {weather_temperature_unit}".rstrip(),
        max_width=content_width,
        min_size=42,
        max_size=56,
    )
    main_temp_y = section_title_bbox[3] + 8
    draw.text((content_x, main_temp_y), main_temp_text, font=main_temp_font, fill=TEXT_COLOR)
    main_temp_bbox = draw.textbbox((content_x, main_temp_y), main_temp_text, font=main_temp_font)

    condition, condition_font = _fit_weather_condition(
        draw,
        condition,
        max_width=content_width,
    )
    condition_y = main_temp_bbox[3] + 8
    draw.text((content_x, condition_y), condition, font=condition_font, fill=TEXT_COLOR)
    condition_bbox = draw.textbbox((content_x, condition_y), condition, font=condition_font)

    detail_font = load_font(13)
    detail_y = condition_bbox[3] + 10
    weather_lines = (
        f"Pluie : {weather_precip} {weather_precip_unit}".rstrip(),
        f"Min. {weather_low_temp} {weather_temp_unit} • Max. {weather_high_temp} {weather_temp_unit}"
        .replace("  ", " ")
        .rstrip(),
        f"Humidité : {weather_humidity} {weather_humidity_unit}".rstrip(),
        f"Pression : {weather_pressure} {weather_pressure_unit}".rstrip(),
        f"Vent : {weather_wind_direction} {weather_wind_speed} {weather_wind_unit}".rstrip(),
    )
    for line in weather_lines:
        draw.text((content_x, detail_y), line, font=detail_font, fill=MUTED_TEXT_COLOR)
        detail_y += 16

    separator_y = min(card_y + card_height - 73, detail_y + 4)
    draw.line((content_x, separator_y, content_right, separator_y), fill=(177, 132, 79), width=1)

    sensor_title = "CAPTEUR EXTÉRIEUR"
    sensor_title_y = separator_y + 8
    draw.text(
        (content_x, sensor_title_y),
        sensor_title,
        font=load_font(13, bold=True),
        fill=MUTED_TEXT_COLOR,
    )
    sensor_title_bbox = draw.textbbox((content_x, sensor_title_y), sensor_title, font=load_font(13, bold=True))
    sensor_temp_text = f"{temperature} {temperature_unit}".rstrip()
    sensor_temp_text, sensor_temp_font = _fit_single_line_text(
        draw,
        sensor_temp_text,
        max_width=content_width,
        min_size=28,
        max_size=34,
    )
    sensor_temp_y = sensor_title_bbox[3] + 4
    draw.text((content_x, sensor_temp_y), sensor_temp_text, font=sensor_temp_font, fill=TEXT_COLOR)
    compact_sensor_text = f"Hum. {humidity} {humidity_unit}   Pre. {pressure} {pressure_unit}"
    compact_sensor_text, compact_sensor_font = _fit_single_line_text(
        draw,
        compact_sensor_text,
        max_width=content_width,
        min_size=11,
        max_size=13,
    )
    compact_sensor_y = draw.textbbox(
        (content_x, sensor_temp_y),
        sensor_temp_text,
        font=sensor_temp_font,
    )[3] + 6
    draw.text((content_x, compact_sensor_y), compact_sensor_text, font=compact_sensor_font, fill=TEXT_COLOR)


def _format_activity_time(activity_time: time) -> str:
    """Formate une heure d'activité sans dépendre de la locale système."""

    return f"{activity_time.hour} h {activity_time.minute:02d}"


def _format_activity_datetime(activity: ActivityInfo) -> str:
    """Formate la date d'activité selon son état déjà déterminé par le service."""

    if activity.heure is None:
        return ""

    formatted_time = _format_activity_time(activity.heure)
    if activity.status == "today":
        return f"Aujourd'hui à {formatted_time}"
    if activity.status != "upcoming" or activity.date is None:
        return ""

    weekday = FRENCH_WEEKDAYS[activity.date.weekday()].capitalize()
    month = FRENCH_MONTHS[activity.date.month - 1]
    return f"{weekday} {activity.date.day} {month} à {formatted_time}"


def _format_activity_player_count(activity: ActivityInfo) -> str:
    """Retourne le nombre de participants avec l'accord approprié."""

    count = len(activity.participants)
    return f"{count} joueur" if count == 1 else f"{count} joueurs"


def _format_activity_participants(activity: ActivityInfo) -> str:
    """Préserve les participants fournis par le service, dans leur ordre."""

    return " • ".join(activity.participants)


def _format_activity_lines(activity: ActivityInfo | None) -> tuple[str, ...]:
    """Produit uniquement les lignes publiques destinées à la bande MGM."""

    if activity is None or activity.status == "unavailable":
        return ((activity.message if activity and activity.message else "Départs indisponibles."),)
    if activity.status == "none":
        return (activity.message or "Aucun départ cette semaine.",)

    datetime_line = _format_activity_datetime(activity)
    if not datetime_line:
        return ("Départs indisponibles.",)
    return (
        datetime_line,
        _format_activity_player_count(activity),
        _format_activity_participants(activity),
    )


def _draw_mgm(draw: ImageDraw.ImageDraw, activity: ActivityInfo | None) -> None:
    """Dessine l'activité MGM fournie par le service dans la bande inférieure."""

    draw.text(
        (24, 368),
        "PROCHAINE ACTIVITÉ MGM",
        font=load_font(11, bold=True),
        fill=MUTED_TEXT_COLOR,
    )
    lines = _format_activity_lines(activity)
    if len(lines) == 1:
        draw.text((24, 385), lines[0], font=load_font(19, bold=True), fill=TEXT_COLOR)
        return

    draw.text((24, 385), lines[0], font=load_font(19, bold=True), fill=TEXT_COLOR)
    draw.text((24, 410), lines[1], font=load_font(14, bold=True), fill=TEXT_COLOR)
    participants, participants_font = _fit_single_line_text(
        draw,
        lines[2],
        max_width=752,
        min_size=11,
        max_size=14,
    )
    draw.text((24, 430), participants, font=participants_font, fill=TEXT_COLOR)


def _format_mail_updated_at(updated_at: datetime | None) -> str:
    """Formate l'horodatage du cache Chronogolf sans dépendre de la locale."""

    if updated_at is None:
        return "Courriel indisponible"
    month = FRENCH_MONTHS[updated_at.month - 1]
    return f"Courriel {updated_at.day} {month} {updated_at:%H:%M}"


def _format_diagnostics(diagnostics: DashboardDiagnostics) -> str:
    """Construit l'unique ligne de diagnostic à partir de valeurs structurées."""

    rssi = "--" if diagnostics.screen_rssi is None else str(diagnostics.screen_rssi)
    return (
        f"Wi-Fi {rssi} dBm  •  MAJ {diagnostics.generated_at:%H:%M}  •  "
        f"{_format_mail_updated_at(diagnostics.mail_updated_at)}"
    )


def _draw_diagnostics(
    draw: ImageDraw.ImageDraw,
    diagnostics: DashboardDiagnostics,
) -> None:
    """Dessine la dernière ligne de la bande, réservée au diagnostic réel."""

    draw.line((24, 453, 776, 453), fill=(213, 190, 157), width=1)
    diagnostic_text, diagnostic_font = _fit_single_line_text(
        draw,
        _format_diagnostics(diagnostics),
        max_width=752,
        min_size=8,
        max_size=9,
    )
    draw.text(
        (24, 458),
        diagnostic_text,
        font=diagnostic_font,
        fill=MUTED_TEXT_COLOR,
    )


def render_dashboard(
    background_path: str | Path = DEFAULT_BACKGROUND_PATH,
    bme280_data: Mapping[str, Any] | None = None,
    weather_data: Mapping[str, Any] | None = None,
    activity: ActivityInfo | None = None,
    diagnostics: DashboardDiagnostics | None = None,
) -> Image.Image:
    """Produit l'image complète du tableau de bord au format RGB 800 x 480."""

    resolved_background = Path(background_path)
    background = _load_background(resolved_background)
    image = _compose_canvas(background)
    image = _add_weather_panel(image)

    draw = ImageDraw.Draw(image)
    _draw_weather(draw, bme280_data, weather_data)
    _draw_mgm(draw, activity)
    _draw_diagnostics(
        draw,
        diagnostics
        or DashboardDiagnostics(
            screen_rssi=None,
            generated_at=datetime.now(),
            mail_updated_at=None,
        ),
    )
    return image
