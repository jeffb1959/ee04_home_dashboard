"""Routes Flask du tableau de bord EE04 (phase 1.6B)."""

from __future__ import annotations

import io
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
import hmac

from flask import Flask, Response, jsonify, send_file, url_for, request
from PIL import Image

from config import load_home_assistant_config, load_refresh_token
from dashboard_renderer import render_dashboard
from home_assistant_client import HomeAssistantClient
from spectra6_converter import BINARY_SIZE, ConversionResult, IMAGE_SIZE, convert_hybrid
from reservation_refresh import ReservationRefreshResult, refresh_reservation_cache


APP_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = APP_DIR / "output"
OUTPUT_PNG_FILE = OUTPUT_DIR / "dashboard.png"
OUTPUT_BINARY_FILE = OUTPUT_DIR / "dashboard.bin"
OUTPUT_SPECTRA6_FILE = OUTPUT_DIR / "dashboard_spectra6.png"

app = Flask(__name__)
home_assistant_client = HomeAssistantClient(load_home_assistant_config())


def add_no_cache_headers(response: Response) -> Response:
    """Empêche le client de réutiliser une ancienne réponse."""

    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


def _render_source_image() -> Image.Image:
    """Génère et valide l'unique image RGB source d'une requête."""

    bme280_data = home_assistant_client.get_bme280_data()
    weather_data = home_assistant_client.get_environment_canada_data()
    image = render_dashboard(
        bme280_data=bme280_data,
        weather_data=weather_data,
    )
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


def _extract_bearer_token(header_value: str | None) -> str | None:
    """Extrait un jeton Bearer si le format est valide."""

    if not header_value:
        return None

    prefix = "Bearer "
    if not header_value.startswith(prefix):
        return None

    token = header_value[len(prefix) :].strip()
    return token or None


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
    """Expose l'état du service sans révéler le jeton Home Assistant."""

    return jsonify(
        status="ok",
        service="ee04_home_dashboard",
        phase="1.6C",
        binary_format="spectra6-indexed-1-byte-per-pixel",
        binary_size=BINARY_SIZE,
        home_assistant=home_assistant_client.health_status(),
        weather=home_assistant_client.weather_health_status(),
        environment_canada=home_assistant_client.environment_canada_health_status(),
    )


@app.post("/api/reservations/refresh")
def api_refresh_reservations() -> Response:
    """Déclenche un rafraîchissement HTTP de façon sécurisée."""

    configured_token = load_refresh_token()
    if not configured_token:
        return (
            jsonify(
                status="error",
                error="refresh_not_configured",
            ),
            503,
        )

    request_token = _extract_bearer_token(request.headers.get("Authorization"))
    if request_token is None or not hmac.compare_digest(request_token, configured_token):
        return (
            jsonify(
                status="error",
                error="unauthorized",
            ),
            401,
        )

    try:
        refresh_result: ReservationRefreshResult = refresh_reservation_cache()
    except Exception:
        app.logger.exception("Échec du rafraîchissement Chronogolf.")
        return (
            jsonify(
                status="error",
                error="refresh_failed",
            ),
            503,
        )

    return jsonify(
        status="ok",
        reservations=refresh_result.reservations_count,
        updated_at=refresh_result.updated_at.isoformat(timespec="seconds"),
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050)
