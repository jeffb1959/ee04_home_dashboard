"""Routes Flask du tableau de bord EE04 (phase 1.1)."""

from __future__ import annotations

import io
import os
from pathlib import Path

from flask import Flask, Response, jsonify, send_file, url_for

from dashboard_renderer import render_dashboard


APP_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = APP_DIR / "output"
OUTPUT_FILE = OUTPUT_DIR / "dashboard.png"

app = Flask(__name__)


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
        image = render_dashboard()
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

    return jsonify(status="ok", service="ee04_home_dashboard", phase="1.1")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050)
