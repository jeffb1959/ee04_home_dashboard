"""Tests de l'API lumière tube vintage."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

RACINE_PROJET = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE_PROJET))

import app as app_module
from home_assistant_client import HomeAssistantError


class FakeHomeAssistantClient:
    """Client Home Assistant minimisé pour /api/tube-vintage."""

    def __init__(self) -> None:
        self.state = ""
        self.error: Exception | None = None
        self.entity_id: str | None = None

    def fetch_entity(self, entity_id: str) -> dict[str, str]:
        self.entity_id = entity_id
        if self.error is not None:
            raise self.error
        return {"state": self.state}


@pytest.fixture
def tube_vintage_client(monkeypatch: pytest.MonkeyPatch) -> FakeHomeAssistantClient:
    """Injecte un client Home Assistant test-friendly."""

    client = FakeHomeAssistantClient()
    monkeypatch.setattr(app_module, "home_assistant_client", client)
    return client


def test_api_tube_vintage_returns_jour(tube_vintage_client: FakeHomeAssistantClient) -> None:
    """La valeur JOUR doit être exposée strictement sous la clé period."""

    tube_vintage_client.state = "JOUR"

    with app_module.app.test_client() as client:
        response = client.get("/api/tube-vintage")

    payload = response.get_json()

    assert response.status_code == 200
    assert payload == {"period": "JOUR"}
    assert tube_vintage_client.entity_id == "sensor.periode_tube_vintage"
    assert response.headers["Cache-Control"] == (
        "no-store, no-cache, must-revalidate, max-age=0"
    )


def test_api_tube_vintage_returns_soir(tube_vintage_client: FakeHomeAssistantClient) -> None:
    """La valeur SOIR doit être exposée strictement sous la clé period."""

    tube_vintage_client.state = "soir "

    with app_module.app.test_client() as client:
        response = client.get("/api/tube-vintage")

    assert response.status_code == 200
    assert response.get_json() == {"period": "SOIR"}


def test_api_tube_vintage_returns_nuit(tube_vintage_client: FakeHomeAssistantClient) -> None:
    """La valeur NUIT doit être exposée strictement sous la clé period."""

    tube_vintage_client.state = "  nuit\n"

    with app_module.app.test_client() as client:
        response = client.get("/api/tube-vintage")

    assert response.status_code == 200
    assert response.get_json() == {"period": "NUIT"}


def test_api_tube_vintage_returns_only_period_for_valid_state(
    tube_vintage_client: FakeHomeAssistantClient,
) -> None:
    """La réponse valide ne doit contenir aucune donnée accessoire."""

    tube_vintage_client.state = "JOUR"

    with app_module.app.test_client() as client:
        response = client.get("/api/tube-vintage")

    payload = response.get_json()

    assert response.status_code == 200
    assert list(payload.keys()) == ["period"]


@pytest.mark.parametrize("state", ["MATIN", "soirée", "", "  "])
def test_api_tube_vintage_invalid_state_returns_503(
    state: str,
    tube_vintage_client: FakeHomeAssistantClient,
) -> None:
    """Une valeur inattendue ne doit jamais être inventée."""

    tube_vintage_client.state = state

    with app_module.app.test_client() as client:
        response = client.get("/api/tube-vintage")

    assert response.status_code == 503
    assert response.get_json() == {"error": "periode tube vintage indisponible"}


@pytest.mark.parametrize("state", ["unknown", "unavailable"])
def test_api_tube_vintage_unknown_or_unavailable_returns_503(
    state: str,
    tube_vintage_client: FakeHomeAssistantClient,
) -> None:
    """unknown ou unavailable doivent être refusés proprement."""

    tube_vintage_client.state = state

    with app_module.app.test_client() as client:
        response = client.get("/api/tube-vintage")

    assert response.status_code == 503
    assert response.get_json() == {"error": "periode tube vintage indisponible"}


def test_api_tube_vintage_home_assistant_error_returns_503(
    tube_vintage_client: FakeHomeAssistantClient,
) -> None:
    """Une erreur Home Assistant doit provoquer une erreur HTTP 503 propre."""

    tube_vintage_client.error = HomeAssistantError("Home Assistant inaccessible")

    with app_module.app.test_client() as client:
        response = client.get("/api/tube-vintage")

    assert response.status_code == 503
    assert response.get_json() == {"error": "periode tube vintage indisponible"}
