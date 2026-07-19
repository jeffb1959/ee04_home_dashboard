"""Tests des routes et du rendu du serveur EE04 Home Dashboard."""

import sys
from io import BytesIO
from pathlib import Path

from PIL import Image

RACINE_PROJET = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE_PROJET))

from app import app
from dashboard_renderer import render_dashboard


def test_health_returns_ok() -> None:
    """La route de santé doit confirmer que le service fonctionne."""

    with app.test_client() as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.get_json()["status"] == "ok"


def test_dashboard_returns_an_800_by_480_png() -> None:
    """Le tableau de bord doit être un PNG aux dimensions de l'écran EE04."""

    with app.test_client() as client:
        response = client.get("/dashboard.png")

    assert response.status_code == 200
    assert response.mimetype == "image/png"

    with Image.open(BytesIO(response.data)) as image:
        assert image.format == "PNG"
        assert image.size == (800, 480)


def test_renderer_works_without_background(tmp_path: Path) -> None:
    """Un fond absent doit produire l'image de secours sans lever d'erreur."""

    missing_background = tmp_path / "background_absent.png"
    image = render_dashboard(background_path=missing_background)

    assert image.mode == "RGB"
    assert image.size == (800, 480)
