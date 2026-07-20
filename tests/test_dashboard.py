"""Tests des routes et du rendu du serveur EE04 Home Dashboard."""

import sys
from io import BytesIO
from pathlib import Path

from PIL import Image

RACINE_PROJET = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE_PROJET))

from app import app
from dashboard_renderer import render_dashboard
from spectra6_converter import IMAGE_SIZE, convert_hybrid, is_protected_pixel


def test_health_returns_ok() -> None:
    """La route de santé doit confirmer que le service fonctionne."""

    with app.test_client() as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.get_json()["status"] == "ok"
    assert response.get_json()["binary_size"] == 384000


def test_dashboard_returns_an_800_by_480_png() -> None:
    """Le tableau de bord doit être un PNG aux dimensions de l'écran EE04."""

    with app.test_client() as client:
        response = client.get("/dashboard.png")

    assert response.status_code == 200
    assert response.mimetype == "image/png"

    with Image.open(BytesIO(response.data)) as image:
        assert image.format == "PNG"
        assert image.size == (800, 480)


def test_dashboard_binary_has_expected_spectra6_format() -> None:
    """Le firmware doit recevoir exactement un index valide par pixel."""

    with app.test_client() as client:
        response = client.get("/dashboard.bin")

    assert response.status_code == 200
    assert "application/octet-stream" in response.content_type
    assert "dashboard.bin" in response.headers["Content-Disposition"]
    assert "no-store" in response.headers["Cache-Control"]
    assert len(response.data) == 384000
    assert all(0 <= index <= 5 for index in response.data)


def test_dashboard_spectra6_preview_is_an_800_by_480_png() -> None:
    """L'aperçu doit représenter le même format d'écran que le binaire."""

    with app.test_client() as client:
        response = client.get("/dashboard-spectra6.png")

    assert response.status_code == 200
    assert response.mimetype == "image/png"
    assert "no-store" in response.headers["Cache-Control"]

    with Image.open(BytesIO(response.data)) as image:
        assert image.format == "PNG"
        assert image.size == IMAGE_SIZE


def test_hybrid_conversion_keeps_protected_zones_black_and_white() -> None:
    """Les zones lisibles ne doivent employer que les index noir et blanc."""

    source = Image.new("RGB", IMAGE_SIZE, (255, 255, 255))
    source.paste((0, 0, 0), (500, 40, 640, 180))
    conversion = convert_hybrid(source)
    width, height = IMAGE_SIZE

    protected_indices = {
        conversion.palette_indices[y * width + x]
        for y in range(height)
        for x in range(width)
        if is_protected_pixel(x, y)
    }

    assert protected_indices == {0, 1}


def test_renderer_works_without_background(tmp_path: Path) -> None:
    """Un fond absent doit produire l'image de secours sans lever d'erreur."""

    missing_background = tmp_path / "background_absent.png"
    image = render_dashboard(background_path=missing_background)

    assert image.mode == "RGB"
    assert image.size == (800, 480)
