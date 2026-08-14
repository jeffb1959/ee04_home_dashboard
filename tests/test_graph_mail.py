"""Tests unitaires indépendants pour `scripts/graph_mail_check.py`."""

from __future__ import annotations

from pathlib import Path
import sys

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import graph_mail_check


def test_load_graph_config_requires_client_and_tenant_id(tmp_path: Path) -> None:
    """Les deux variables obligatoires doivent être fournies."""

    env_file = tmp_path / ".env"
    env_file.write_text("MS_GRAPH_TENANT_ID=tenant", encoding="utf-8")

    with pytest.raises(graph_mail_check.GraphConfigError, match="MS_GRAPH_CLIENT_ID"):
        graph_mail_check.load_graph_config(env_file=env_file, environ={})


def test_load_graph_config_prefers_environment_over_file(tmp_path: Path) -> None:
    """Les variables d’environnement localement définies prévalent sur le `.env`."""

    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            (
                "MS_GRAPH_CLIENT_ID=file-client-id",
                "MS_GRAPH_TENANT_ID=file-tenant-id",
                "MS_GRAPH_ACCOUNT=file-account@multifab.com",
            )
        ),
        encoding="utf-8",
    )

    config = graph_mail_check.load_graph_config(
        env_file=env_file,
        environ={
            "MS_GRAPH_CLIENT_ID": "env-client-id",
            "MS_GRAPH_TENANT_ID": "env-tenant-id",
            "MS_GRAPH_ACCOUNT": "",
        },
    )

    assert config.client_id == "env-client-id"
    assert config.tenant_id == "env-tenant-id"
    assert config.account == "file-account@multifab.com"

def test_format_message_line_highlights_chronogolf_sender() -> None:
    """L’expéditeur Chronogolf doit être mis en évidence explicitement."""

    message = {
        "receivedDateTime": "2026-07-21T11:47:00Z",
        "from": {
            "emailAddress": {
                "name": "Chronogolf",
                "address": "notifications@chronogolf.ca",
            }
        },
        "subject": "Réservation Chronogolf",
        "isRead": False,
    }

    line = graph_mail_check.format_message_line(message)

    assert "[CHRONOGOLF]" in line
    assert "2026-07-21 11:47" in line
    assert "notifications@chronogolf.ca" in line
    assert "Non lu" in line


def test_format_message_line_uses_safe_defaults_when_fields_are_missing() -> None:
    """Les champs manquants ne doivent jamais casser l’affichage."""

    message = {"isRead": True}
    line = graph_mail_check.format_message_line(message)

    assert "Date inconnue" in line
    assert "<expéditeur inconnu>" in line
    assert "(sans sujet)" in line
    assert "Lu" in line
