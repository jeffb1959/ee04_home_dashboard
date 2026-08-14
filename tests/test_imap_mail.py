"""Tests unitaires pour `scripts/imap_mail_check.py`."""

from __future__ import annotations

from datetime import datetime
from email.header import Header
from pathlib import Path
import sys

import pytest

RACINE_PROJET = Path(__file__).resolve().parents[1]
SCRIPT_DIR = RACINE_PROJET / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import imap_mail_check


def test_load_imap_config_requires_host_port_user_and_password(tmp_path: Path) -> None:
    """Les 4 paramètres requis doivent être fournis."""

    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            (
                "VIDEOTRON_IMAP_HOST=imap.videotron.ca",
                "VIDEOTRON_IMAP_PORT=993",
            )
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        imap_mail_check.ImapConfigError, match="VIDEOTRON_IMAP_USER"
    ):
        imap_mail_check.load_imap_config(env_file=env_file, environ={})


def test_load_imap_config_prefers_environment_variables(tmp_path: Path) -> None:
    """Les variables d’environnement locales prévalent sur le `.env`."""

    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            (
                "VIDEOTRON_IMAP_HOST=file-host",
                "VIDEOTRON_IMAP_PORT=993",
                "VIDEOTRON_IMAP_USER=file-user",
                "VIDEOTRON_IMAP_PASSWORD=file-password",
            )
        ),
        encoding="utf-8",
    )

    config = imap_mail_check.load_imap_config(
        env_file=env_file,
        environ={
            "VIDEOTRON_IMAP_HOST": "env-host",
            "VIDEOTRON_IMAP_PORT": "143",
            "VIDEOTRON_IMAP_USER": "env-user",
            "VIDEOTRON_IMAP_PASSWORD": "",
        },
    )

    assert config.host == "env-host"
    assert config.port == 143
    assert config.user == "env-user"
    assert config.password == "file-password"


def test_load_imap_port_conversion_and_validation(tmp_path: Path) -> None:
    """Le port doit être un entier positif."""

    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            (
                "VIDEOTRON_IMAP_HOST=imap.videotron.ca",
                "VIDEOTRON_IMAP_PORT=not-an-int",
                "VIDEOTRON_IMAP_USER=user",
                "VIDEOTRON_IMAP_PASSWORD=pass",
            )
        ),
        encoding="utf-8",
    )

    with pytest.raises(imap_mail_check.ImapConfigError, match="VIDEOTRON_IMAP_PORT"):
        imap_mail_check.load_imap_config(env_file=env_file, environ={})


def test_imap_search_date_is_seven_days_ago() -> None:
    """La date de recherche doit couvrir les 7 derniers jours."""

    date_reference = datetime(2026, 8, 13, 14, 0, 0)
    assert imap_mail_check.format_imap_since_date(date_reference) == "06-Aug-2026"


def test_decode_mime_subject_with_utf8_accents() -> None:
    """Le décodage MIME doit bien restituer les accents en UTF-8."""

    encoded_subject = str(Header("Confirmation de réservation", "utf-8"))
    assert (
        imap_mail_check.decode_mime_subject(encoded_subject) == "Confirmation de réservation"
    )


def test_confirmation_subject_is_case_and_encoding_insensitive() -> None:
    """La reconnaissance tolère encodage MIME et la casse."""

    encoded_subject = str(Header("Confirmation de réservation", "utf-8"))
    assert imap_mail_check.is_confirmation_subject(encoded_subject)
    assert imap_mail_check.is_confirmation_subject("CoNfIrMaTiOn dE rÉservation")


def test_non_confirmation_subject_is_rejected() -> None:
    """Un autre sujet ne doit pas être retenu."""

    assert not imap_mail_check.is_confirmation_subject(
        "Demande d'information sur le parcours"
    )
