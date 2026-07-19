"""Serveur minimal de génération du tableau de bord EE04 (phase 1.0)."""

from __future__ import annotations

import io
import os
import socket
from datetime import datetime
from pathlib import Path

from flask import Flask, Response, jsonify, send_file, url_for
from PIL import Image, ImageDraw, ImageFont


APP_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = APP_DIR / "output"
OUTPUT_FILE = OUTPUT_DIR / "dashboard.png"

IMAGE_SIZE = (800, 480)
BACKGROUND_COLOR = (250, 246, 232)  # Crème clair
TEXT_COLOR = (42, 47, 51)

app = Flask(__name__)


def get_local_ip() -> str:
    """Retourne l'adresse IP locale, avec une valeur sûre en cas d'échec."""

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp_socket:
            # Aucune donnée n'est envoyée : connect() permet seulement de
            # connaître l'interface utilisée pour joindre cette adresse.
            udp_socket.connect(("8.8.8.8", 80))
            return str(udp_socket.getsockname()[0])
    except OSError:
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError:
            return "127.0.0.1"


def load_font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Charge une police Raspberry Pi OS, puis la police Pillow en repli."""

    filename = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    font_paths = (
        Path("/usr/share/fonts/truetype/dejavu") / filename,
        Path("/usr/share/fonts/dejavu") / filename,
    )

    for font_path in font_paths:
        try:
            return ImageFont.truetype(str(font_path), size=size)
        except (OSError, ValueError):
            continue

    # Pillow fournit cette police même si aucune police système n'est installée.
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Compatibilité défensive avec d'anciennes versions.
        return ImageFont.load_default()


def build_dashboard_image() -> Image.Image:
    """Construit l'image 800 x 480 affichée par le tableau de bord."""

    image = Image.new("RGB", IMAGE_SIZE, BACKGROUND_COLOR)
    draw = ImageDraw.Draw(image)

    title_font = load_font(42, bold=True)
    subtitle_font = load_font(30, bold=True)
    body_font = load_font(24)

    generated_at = datetime.now().astimezone()
    lines = (
        ("EE04 HOME DASHBOARD", title_font, 54),
        ("Phase 1.0", subtitle_font, 145),
        ("Serveur actif", subtitle_font, 205),
        (f"Adresse IP locale : {get_local_ip()}", body_font, 300),
        (
            f"Date et heure locales : {generated_at.strftime('%Y-%m-%d %H:%M:%S %Z')}",
            body_font,
            352,
        ),
    )

    for text, font, y_position in lines:
        # anchor="ma" centre chaque ligne horizontalement selon sa ligne de base.
        draw.text((IMAGE_SIZE[0] // 2, y_position), text, font=font, fill=TEXT_COLOR, anchor="ma")

    return image


def add_no_cache_headers(response: Response) -> Response:
    """Empêche le navigateur de réutiliser une ancienne image."""

    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.get("/")
def index() -> str:
    """Affiche une page d'accueil minimale avec un lien vers l'image."""

    dashboard_url = url_for("dashboard_png")
    return f"""<!doctype html>
<html lang="fr">
  <head><meta charset="utf-8"><title>EE04 Home Dashboard</title></head>
  <body>
    <h1>EE04 Home Dashboard</h1>
    <p>Le serveur EE04 Home Dashboard fonctionne.</p>
    <p><a href="{dashboard_url}">Afficher le tableau de bord PNG</a></p>
  </body>
</html>
"""


@app.get("/dashboard.png")
def dashboard_png() -> Response | tuple[Response, int]:
    """Génère, sauvegarde et retourne la dernière image du tableau de bord."""

    try:
        image = build_dashboard_image()
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        png_data = buffer.getvalue()

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        temporary_file = OUTPUT_FILE.with_suffix(".png.tmp")
        temporary_file.write_bytes(png_data)
        os.replace(temporary_file, OUTPUT_FILE)

        response = send_file(
            io.BytesIO(png_data),
            mimetype="image/png",
            download_name="dashboard.png",
        )
        return add_no_cache_headers(response)
    except (OSError, ValueError):
        app.logger.exception("Impossible de générer ou sauvegarder dashboard.png")
        return jsonify(error="Impossible de générer le tableau de bord"), 500


@app.get("/health")
def health() -> Response:
    """Expose l'état minimal du service pour les vérifications automatiques."""

    return jsonify(status="ok", service="ee04_home_dashboard", phase="1.0")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050)
