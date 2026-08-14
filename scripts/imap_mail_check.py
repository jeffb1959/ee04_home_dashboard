"""Validation IMAP en lecture seule pour la boîte Vidéotron."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from email.header import decode_header
from email.parser import BytesParser
from email.policy import default as default_policy
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Iterable, Mapping, Sequence
import imaplib
import os
import socket
import ssl

from dotenv import dotenv_values, load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = PROJECT_ROOT / ".env"

CONFIRMATION_SUBJECT = "confirmation de réservation"
SEARCH_WINDOW_DAYS = 7
IMAP_MONTHS_EN = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)


@dataclass(frozen=True)
class ImapConfig:
    """Paramètres IMAP de la boîte Vidéotron."""

    host: str
    port: int
    user: str
    password: str


class ImapConfigError(ValueError):
    """Erreur de configuration IMAP."""


def load_imap_config(
    env_file: Path = ENV_FILE,
    environ: Mapping[str, str] | None = None,
) -> ImapConfig:
    """Charge la configuration IMAP depuis `.env` et l’environnement courant."""

    file_values = {
        key: str(value).strip()
        for key, value in dotenv_values(env_file).items()
        if value is not None
    }
    env_values = os.environ if environ is None else environ

    def get_value(name: str) -> str:
        value = env_values.get(name, "") if isinstance(env_values, Mapping) else ""
        value = str(value).strip() if value is not None else ""
        if value:
            return value
        return file_values.get(name, "")

    host = get_value("VIDEOTRON_IMAP_HOST")
    port_value = get_value("VIDEOTRON_IMAP_PORT")
    user = get_value("VIDEOTRON_IMAP_USER")
    password = get_value("VIDEOTRON_IMAP_PASSWORD")

    missing = [
        name
        for name, value in (
            ("VIDEOTRON_IMAP_HOST", host),
            ("VIDEOTRON_IMAP_PORT", port_value),
            ("VIDEOTRON_IMAP_USER", user),
            ("VIDEOTRON_IMAP_PASSWORD", password),
        )
        if not value
    ]
    if missing:
        raise ImapConfigError(
            "Variables de configuration IMAP manquantes: " + ", ".join(missing)
        )

    try:
        port = int(port_value)
    except ValueError as exc:
        raise ImapConfigError("VIDEOTRON_IMAP_PORT doit être un entier.") from exc
    if port <= 0:
        raise ImapConfigError("VIDEOTRON_IMAP_PORT doit être > 0.")

    return ImapConfig(host=host, port=port, user=user, password=password)


def format_imap_since_date(reference: datetime | None = None) -> str:
    """Retourne la date IMAP (since) au format `DD-MMM-YYYY`."""

    reference_date = (reference or datetime.now()).date() - timedelta(
        days=SEARCH_WINDOW_DAYS
    )
    month = IMAP_MONTHS_EN[reference_date.month - 1]
    return f"{reference_date.day:02d}-{month}-{reference_date.year}"


def format_display_since_date(reference: datetime | None = None) -> str:
    """Retourne la date de début en format ISO pour l’affichage humain."""

    reference_date = (reference or datetime.now()).date() - timedelta(
        days=SEARCH_WINDOW_DAYS
    )
    return reference_date.isoformat()


def decode_mime_subject(raw_subject: str | None) -> str:
    """Décode les sujets MIME contenant accents/UTF-8."""

    if not raw_subject:
        return ""
    fragments = []
    for value, charset in decode_header(raw_subject):
        if isinstance(value, bytes):
            fragments.append(value.decode(charset or "utf-8", errors="replace"))
        else:
            fragments.append(value)
    return "".join(fragments).strip()


def normalize_subject(subject: str) -> str:
    """Normalise un sujet pour une comparaison case-insensitive fiable."""

    return " ".join(subject.casefold().split())


def is_confirmation_subject(raw_subject: str | None) -> bool:
    """Retourne vrai si le sujet correspond à une confirmation de réservation."""

    normalized = normalize_subject(decode_mime_subject(raw_subject))
    target = normalize_subject(CONFIRMATION_SUBJECT)
    return normalized == target or f" {target} " in f" {normalized} "


def parse_message_date(raw_date: str | None) -> str:
    """Extrait une date de courriel au format AAAA-MM-JJ."""

    if not raw_date:
        return "Date inconnue"
    parsed = parsedate_to_datetime(raw_date)
    if parsed is None:
        return "Date inconnue"
    return parsed.date().isoformat()


def extract_headers(message_bytes: bytes) -> dict[str, str]:
    """Extrait uniquement les en-têtes utiles."""

    message = BytesParser(policy=default_policy).parsebytes(message_bytes)
    raw_subject = message["Subject"]
    raw_from = message["From"]
    raw_message_id = message["Message-ID"]
    return {
        "date": parse_message_date(message["Date"]),
        "subject": decode_mime_subject(raw_subject),
        "from": (str(raw_from).strip() if raw_from else "<expéditeur inconnu>"),
        "message_id": str(raw_message_id).strip() if raw_message_id else "",
    }


def iter_header_payload(fetch_payload: object) -> Iterable[bytes]:
    """Retourne les blocs de bytes utiles du résultat de `fetch`."""

    if not isinstance(fetch_payload, Sequence):
        return ()
    for item in fetch_payload:
        if isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], bytes):
            yield item[1]


def fetch_confirmation_headers(
    config: ImapConfig, reference: datetime | None = None
) -> tuple[str, int, list[dict[str, str]]]:
    """Récupère les en-têtes des messages de confirmation, sans modifier l’état."""

    search_date = format_imap_since_date(reference)
    confirmations: list[dict[str, str]] = []
    inspected = 0
    imap = None
    try:
        imap = imaplib.IMAP4_SSL(
            config.host,
            config.port,
            ssl_context=ssl.create_default_context(),
        )
        imap.login(config.user, config.password)
        print(f"Connexion IMAP réussie : {config.host}")

        status, _ = imap.select("INBOX", readonly=True)
        if status != "OK":
            raise RuntimeError("Impossible de sélectionner INBOX en lecture seule.")

        status, raw_ids = imap.search(None, "SINCE", search_date)
        if status != "OK":
            raise RuntimeError("La recherche IMAP a échoué.")
        message_ids = (
            raw_ids[0].decode("utf-8").split()
            if raw_ids and raw_ids[0]
            else []
        )

        for message_id in message_ids:
            fetch_status, fetch_data = imap.fetch(
                message_id,
                "(BODY.PEEK[HEADER.FIELDS (DATE SUBJECT FROM MESSAGE-ID)])",
            )
            if fetch_status != "OK" or not fetch_data:
                continue
            payload = b"".join(iter_header_payload(fetch_data))
            if not payload:
                continue
            message = extract_headers(payload)
            inspected += 1
            if is_confirmation_subject(message["subject"]):
                confirmations.append(message)

        return search_date, inspected, confirmations
    except (socket.gaierror, OSError) as exc:
        raise RuntimeError(f"Erreur réseau: {exc}") from exc
    except ssl.SSLError as exc:
        raise RuntimeError(f"Erreur SSL: {exc}") from exc
    except imaplib.IMAP4.error as exc:
        raise RuntimeError(f"Échec d’authentification IMAP: {exc}") from exc
    finally:
        if imap is not None:
            try:
                imap.close()
            except Exception:
                pass
            try:
                imap.logout()
            except Exception:
                pass


def format_confirmation_messages(messages: Sequence[Mapping[str, str]]) -> list[str]:
    """Formate une liste de messages pour affichage humain."""

    return [f"{message['date']} | {message['subject']}" for message in messages]


def print_report(
    search_date: str,
    examined: int,
    confirmations: Sequence[Mapping[str, str]],
) -> None:
    """Affiche un rapport lisible de la validation."""

    print(f"Recherche depuis : {search_date}")
    print(f"Messages examinés : {examined}")
    print(f"Confirmations de réservation trouvées : {len(confirmations)}")
    print()
    for index, line in enumerate(format_confirmation_messages(confirmations), start=1):
        print(f"{index}. {line}")


def main() -> int:
    """Point d’entrée script IMAP."""

    load_dotenv(ENV_FILE)
    try:
        config = load_imap_config()
    except ImapConfigError as exc:
        print(f"Configuration invalide: {exc}")
        return 1

    now = datetime.now()
    try:
        search_date, examined, confirmations = fetch_confirmation_headers(config, reference=now)
    except RuntimeError as exc:
        print(f"Erreur IMAP: {exc}")
        return 1

    print_report(format_display_since_date(now), examined, confirmations)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
