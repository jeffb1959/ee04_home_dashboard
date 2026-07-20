"""Routes Flask du tableau de bord EE04 (phase 1.5A)."""

from __future__ import annotations

import io
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from flask import Flask, Response, jsonify, send_file, url_for
from PIL import Image

from dashboard_renderer import render_dashboard
from spectra6_converter import BINARY_SIZE, ConversionResult, IMAGE_SIZE, convert_hybrid


APP_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = APP_DIR / "output"
OUTPUT_PNG_FILE = OUTPUT_DIR / "dashboard.png"
OUTPUT_BINARY_FILE = OUTPUT_DIR / "dashboard.bin"
OUTPUT_SPECTRA6_FILE = OUTPUT_DIR / "dashboard_spectra6.png"

app = Flask(__name__)


def add_no_cache_headers(response: Response) -> Response:
    """Empêche le client de réutiliser une ancienne réponse."""

    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


def _render_source_image() -> Image.Image:
    """Génère et valide l'unique image RGB source d'une requête."""

    image = render_dashboard()
    if image.size != IMAGE_SIZE:
        raise ValueError(
            f"Le renderer doit produire une image {IMAGE_SIZE[0]} x {IMAGE_SIZE[1]}"
        )
    return image.convert("RGB")


def _encode_png(image: Image.Image) -> bytes:
    """Encode une image Pillow en mémoire sans relire un fichier déjà tramé."""

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _save_atomically(destination: Path, data: bytes) -> None:
    """Écrit un artefact complet avant de remplacer sa version précédente."""

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with NamedTemporaryFile(
            mode="wb",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_file.write(data)
            temporary_path = Path(temporary_file.name)
        os.replace(temporary_path, destination)
    except OSError:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise


def _generate_spectra6() -> ConversionResult:
    """Produit la source originale puis sa conversion hybride Spectra 6."""

    source_image = _render_source_image()
    return convert_hybrid(source_image)


@app.get("/")
def index() -> str:
    """Affiche une page d'accueil minimale avec un lien vers l'image."""

    dashboard_url = url_for("dashboard_png")
    binary_url = url_for("dashboard_binary")
    preview_url = url_for("dashboard_spectra6_png")
    return f"""<!doctype html>
<html lang="fr">
  <head><meta charset="utf-8"><title>EE04 Home Dashboard</title></head>
  <body>
    <h1>EE04 Home Dashboard</h1>
    <p>Le serveur EE04 Home Dashboard fonctionne.</p>
    <p><a href="{dashboard_url}">Afficher le tableau de bord PNG</a></p>
    <p><a href="{preview_url}">Afficher l'aperçu Spectra 6</a></p>
    <p><a href="{binary_url}">Télécharger le binaire Spectra 6</a></p>
  </body>
</html>
"""


@app.get("/dashboard.png")
def dashboard_png() -> Response | tuple[Response, int]:
    """Génère, sauvegarde et retourne la dernière image du tableau de bord."""

    try:
        image = _render_source_image()
        png_data = _encode_png(image)
        _save_atomically(OUTPUT_PNG_FILE, png_data)

        response = send_file(
            io.BytesIO(png_data),
            mimetype="image/png",
            download_name="dashboard.png",
        )
        return add_no_cache_headers(response)
    except Exception:  # La frontière HTTP transforme toute panne en réponse propre.
        app.logger.exception("Impossible de générer ou sauvegarder dashboard.png")
        return jsonify(error="Impossible de générer le tableau de bord"), 500


@app.get("/dashboard.bin")
def dashboard_binary() -> Response | tuple[Response, int]:
    """Retourne un index Spectra 6 par pixel, dans l'ordre ligne par ligne."""

    try:
        conversion = _generate_spectra6()
        binary_data = conversion.palette_indices
        if len(binary_data) != BINARY_SIZE:
            raise ValueError(f"Le binaire doit mesurer {BINARY_SIZE} octets")
        _save_atomically(OUTPUT_BINARY_FILE, binary_data)

        response = send_file(
            io.BytesIO(binary_data),
            mimetype="application/octet-stream",
            as_attachment=True,
            download_name="dashboard.bin",
        )
        return add_no_cache_headers(response)
    except Exception:  # Voir dashboard_png : Flask reste disponible après l'erreur.
        app.logger.exception("Impossible de générer ou sauvegarder dashboard.bin")
        return jsonify(error="Impossible de générer le binaire Spectra 6"), 500


@app.get("/dashboard-spectra6.png")
def dashboard_spectra6_png() -> Response | tuple[Response, int]:
    """Retourne un aperçu navigateur de la conversion hybride Spectra 6."""

    try:
        conversion = _generate_spectra6()
        png_data = _encode_png(conversion.preview)
        _save_atomically(OUTPUT_SPECTRA6_FILE, png_data)

        response = send_file(
            io.BytesIO(png_data),
            mimetype="image/png",
            download_name="dashboard_spectra6.png",
        )
        return add_no_cache_headers(response)
    except Exception:  # La journalisation conserve le détail côté serveur.
        app.logger.exception(
            "Impossible de générer ou sauvegarder dashboard_spectra6.png"
        )
        return jsonify(error="Impossible de générer l'aperçu Spectra 6"), 500


@app.get("/health")
def health() -> Response:
    """Expose l'état minimal du service pour les vérifications automatiques."""

    return jsonify(
        status="ok",
        service="ee04_home_dashboard",
        phase="1.1",
        binary_format="spectra6-indexed-1-byte-per-pixel",
        binary_size=BINARY_SIZE,
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050)
