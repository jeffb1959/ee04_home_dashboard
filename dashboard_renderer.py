"""Composition visuelle du tableau de bord EE04 (phase 1.1)."""

from __future__ import annotations

from pathlib import Path

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


def load_font(
    size: int, *, bold: bool = False
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
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
    except TypeError:  # Compatibilité défensive avec d'anciennes versions.
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
        (494, 35, 766, 319),
        radius=16,
        fill=WEATHER_PANEL_FILL,
        outline=PANEL_OUTLINE,
        width=1,
    )

    return Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")


def _draw_weather(draw: ImageDraw.ImageDraw) -> None:
    """Dessine les données météo fictives dans la zone de droite."""

    draw.text((514, 50), "MÉTÉO", font=load_font(14, bold=True), fill=MUTED_TEXT_COLOR)
    draw.text((514, 75), "Québec", font=load_font(25, bold=True), fill=TEXT_COLOR)
    draw.text((514, 106), "23 °C", font=load_font(45, bold=True), fill=TEXT_COLOR)
    draw.text((514, 158), "Beau temps", font=load_font(20), fill=TEXT_COLOR)
    draw.text(
        (514, 190),
        "Max 26 °C  •  Min 17 °C",
        font=load_font(15),
        fill=MUTED_TEXT_COLOR,
    )
    draw.line((514, 219, 746, 219), fill=(177, 132, 79), width=1)

    draw.text(
        (514, 232),
        "EXTÉRIEUR",
        font=load_font(13, bold=True),
        fill=MUTED_TEXT_COLOR,
    )
    draw.text((514, 252), "22,4 °C", font=load_font(25, bold=True), fill=TEXT_COLOR)
    draw.text((630, 257), "Humidité 64 %", font=load_font(14), fill=TEXT_COLOR)
    draw.text((514, 291), "Pression 1012 hPa", font=load_font(14), fill=TEXT_COLOR)


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
) -> Image.Image:
    """Produit l'image complète du tableau de bord au format RGB 800 x 480."""

    resolved_background = Path(background_path)
    background = _load_background(resolved_background)
    image = _compose_canvas(background)
    image = _add_weather_panel(image)

    draw = ImageDraw.Draw(image)
    _draw_weather(draw)
    _draw_mgm(draw)
    _draw_diagnostics(draw)
    return image
