"""Tests des routes principales du serveur EE04 Home Dashboard."""

from io import BytesIO

from PIL import Image
from pathlib import Path
import sys

RACINE_PROJET = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE_PROJET))

from app import app


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
