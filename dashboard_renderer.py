"""Composition visuelle du tableau de bord EE04 (phase 1.6C)."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError


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

    overlay = Image.new("RGBA", IMAGE_SIZE, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    draw.rounded_rectangle(
        (482, 30, 784, 324),
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
        trimmed = text
        while trimmed and draw.textlength(f"{trimmed}…", font=font) > max_width:
            trimmed = trimmed[:-1]
        if trimmed:
            return f"{trimmed.rstrip()}…", font

    font = load_font(min_size)
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

    draw.text(
        (514, 44),
        "CONDITIONS ACTUELLES",
        font=load_font(14, bold=True),
        fill=MUTED_TEXT_COLOR,
    )
    weather_temperature_font = load_font(42, bold=True)
    draw.text(
        (514, 54),
        f"{weather_temperature} {weather_temperature_unit}".rstrip(),
        font=weather_temperature_font,
        fill=TEXT_COLOR,
    )
    condition, condition_font = _fit_weather_condition(draw, condition)
    weather_temperature_bbox = draw.textbbox(
        (514, 54),
        f"{weather_temperature} {weather_temperature_unit}".rstrip(),
        font=weather_temperature_font,
    )
    condition_y = weather_temperature_bbox[3] + 12
    draw.text(
        (514, condition_y),
        condition,
        font=condition_font,
        fill=TEXT_COLOR,
    )
    draw.text(
        (514, 164),
        f"Pluie : {weather_precip} {weather_precip_unit}".rstrip(),
        font=load_font(14),
        fill=MUTED_TEXT_COLOR,
    )
    draw.text(
        (514, 180),
        f"Min. {weather_low_temp} {weather_temp_unit} • Max. {weather_high_temp} {weather_temp_unit}"
        .replace("  ", " ")
        .rstrip(),
        font=load_font(14),
        fill=MUTED_TEXT_COLOR,
    )
    draw.text(
        (514, 196),
        f"Humidité : {weather_humidity} {weather_humidity_unit}".rstrip(),
        font=load_font(14),
        fill=MUTED_TEXT_COLOR,
    )
    draw.text(
        (514, 212),
        f"Pression : {weather_pressure} {weather_pressure_unit}".rstrip(),
        font=load_font(14),
        fill=MUTED_TEXT_COLOR,
    )
    draw.text(
        (514, 228),
        f"Vent : {weather_wind_direction} {weather_wind_speed} {weather_wind_unit}".rstrip(),
        font=load_font(14),
        fill=MUTED_TEXT_COLOR,
    )
    draw.line((514, 244, 746, 244), fill=(177, 132, 79), width=1)

    draw.text(
        (514, 254),
        "CAPTEUR EXTÉRIEUR",
        font=load_font(13, bold=True),
        fill=MUTED_TEXT_COLOR,
    )
    draw.text(
        (514, 264),
        f"{temperature} {temperature_unit}",
        font=load_font(23, bold=True),
        fill=TEXT_COLOR,
    )
    draw.text(
        (514, 290),
        f"Hum. {humidity} {humidity_unit}   Pre. {pressure} {pressure_unit}",
        font=load_font(14),
        fill=TEXT_COLOR,
    )


def _draw_mgm(draw: ImageDraw.ImageDraw) -> None:
    """Dessine la prochaine activité MGM fictive dans la bande inférieure."""

    draw.text(
        (24, 368),
        "PROCHAINE ACTIVITÉ MGM",
        font=load_font(11, bold=True),
        fill=MUTED_TEXT_COLOR,
    )
    draw.text(
        (24, 385),
        "Mercredi 22 juillet à 8 h 16",
        font=load_font(19, bold=True),
        fill=TEXT_COLOR,
    )
    draw.text(
        (24, 410),
        "Lorette • 4 joueurs",
        font=load_font(14, bold=True),
        fill=TEXT_COLOR,
    )
    draw.text(
        (24, 430),
        "Jean-François • Yvon • Robert • Alain",
        font=load_font(13),
        fill=TEXT_COLOR,
    )


def _draw_diagnostics(draw: ImageDraw.ImageDraw) -> None:
    """Dessine la dernière ligne de la bande, réservée au diagnostic."""

    draw.line((24, 453, 776, 453), fill=(213, 190, 157), width=1)
    draw.text(
        (24, 458),
        "Wi-Fi -63 dBm  •  MAJ 21:35  •  Serveur OK",
        font=load_font(9),
        fill=MUTED_TEXT_COLOR,
    )


def render_dashboard(
    background_path: str | Path = DEFAULT_BACKGROUND_PATH,
    bme280_data: Mapping[str, Any] | None = None,
    weather_data: Mapping[str, Any] | None = None,
) -> Image.Image:
    """Produit l'image complète du tableau de bord au format RGB 800 x 480."""

    resolved_background = Path(background_path)
    background = _load_background(resolved_background)
    image = _compose_canvas(background)
    image = _add_weather_panel(image)

    draw = ImageDraw.Draw(image)
    _draw_weather(draw, bme280_data, weather_data)
    _draw_mgm(draw)
    _draw_diagnostics(draw)
    return image
