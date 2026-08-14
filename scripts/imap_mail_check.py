"""Validation IMAP en lecture seule pour la boîte Vidéotron."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from email.parser import BytesParser
from email.policy import default as default_policy
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Iterable, Mapping
import imaplib
import os
import sys
import socket
import ssl

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = PROJECT_ROOT / ".env"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import reservation_parser
from dotenv import dotenv_values, load_dotenv

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

    reference_date = (reference or datetime.now()).date() - timedelta(days=SEARCH_WINDOW_DAYS)
    month = IMAP_MONTHS_EN[reference_date.month - 1]
    return f"{reference_date.day:02d}-{month}-{reference_date.year}"


def decode_mime_subject(raw_subject: str | None) -> str:
    from email.header import decode_header

    if not raw_subject:
        return ""
    fragments = []
    for value, charset in decode_header(raw_subject):
        if isinstance(value, bytes):
            fragments.append(value.decode(charset or "utf-8", errors="replace"))
        else:
            fragments.append(value)
    return "".join(fragments).strip()


def _normalize_subject(subject: str) -> str:
    return " ".join(subject.casefold().split())


def is_confirmation_subject(raw_subject: str | None) -> bool:
    """Retourne vrai si le sujet correspond à une confirmation de réservation."""

    normalized = _normalize_subject(decode_mime_subject(raw_subject))
    target = _normalize_subject(CONFIRMATION_SUBJECT)
    return normalized == target or f" {target} " in f" {normalized} "


def _parse_imap_message_date(value: str | None) -> datetime | None:
    if not value:
        return None
    return parsedate_to_datetime(value)


def _extract_headers(message_bytes: bytes) -> dict[str, str | datetime | None]:
    message = BytesParser(policy=default_policy).parsebytes(message_bytes)
    raw_subject = message["Subject"]
    raw_date = message["Date"]
    return {
        "subject": decode_mime_subject(str(raw_subject) if raw_subject else ""),
        "received_at": _parse_imap_message_date(str(raw_date) if raw_date else None),
    }


def _iter_payload(message_fetch_payload: object) -> Iterable[bytes]:
    if not isinstance(message_fetch_payload, (tuple, list)):
        return ()
    payload = []
    for item in message_fetch_payload:
        if isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], bytes):
            payload.append(item[1])
    return tuple(payload)


def fetch_confirmation_reservations(
    config: ImapConfig, reference: datetime | None = None
) -> tuple[str, int, int, list[reservation_parser.GolfReservation]]:
    """Collecte les réservations à partir des confirmations Chronogolf."""

    search_date = format_imap_since_date(reference)
    inspected = 0
    confirmation_count = 0
    reservations: list[reservation_parser.GolfReservation] = []
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

        message_ids = raw_ids[0].decode("utf-8").split() if raw_ids and raw_ids[0] else []

        for message_id in message_ids:
            header_status, header_data = imap.fetch(
                message_id,
                "(BODY.PEEK[HEADER.FIELDS (SUBJECT DATE)])",
            )
            if header_status != "OK" or not header_data:
                continue

            header_payload = b"".join(_iter_payload(header_data))
            if not header_payload:
                continue
            headers = _extract_headers(header_payload)
            inspected += 1

            if not is_confirmation_subject(str(headers["subject"])):
                continue
            confirmation_count += 1

            try:
                body_status, body_data = imap.fetch(message_id, "(BODY.PEEK[])")
                if body_status != "OK" or not body_data:
                    raise RuntimeError("Message sans contenu.")
                body_bytes = b"".join(_iter_payload(body_data))
                if not body_bytes:
                    raise RuntimeError("Corps vide.")
                message_body = reservation_parser.extract_confirmation_body_text(body_bytes)
                reservation = reservation_parser.parse_confirmation_reservation(
                    message_body,
                    received_at=headers["received_at"],
                )
                reservations.append(reservation)
            except reservation_parser.ReservationParseError as exc:
                print(f"Confirmation ignorée : {exc}")
            except RuntimeError:
                print("Confirmation ignorée : données de réservation incomplètes")
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

    return search_date, inspected, confirmation_count, reservations


def _format_since_display(reference: datetime | None = None) -> str:
    reference_date = (reference or datetime.now()).date() - timedelta(days=SEARCH_WINDOW_DAYS)
    return reference_date.isoformat()


def _print_report(
    search_date: str,
    examined: int,
    confirmations: int,
    reservations: list[reservation_parser.GolfReservation],
) -> None:
    print(f"Recherche depuis : {search_date}")
    print(f"\nMessages examinés : {examined}")
    print(f"Confirmations trouvées : {confirmations}")
    print(f"Réservations actuelles ou futures : {len(reservations)}")
    print()

    for index, reservation in enumerate(reservations, start=1):
        players = ", ".join(reservation.joueurs)
        print(f"{index}. {reservation.date} {reservation.heure.strftime('%H:%M')}")
        print(f"   {len(reservation.joueurs)} joueurs : {players}")
        print(f"   ID : {reservation.reservation_id}")


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
        search_date, examined, confirmations, reservations = fetch_confirmation_reservations(
            config,
            reference=now,
        )
        upcoming = reservation_parser.filter_upcoming_reservations(
            reservations,
            today=now.date(),
        )
        deduped = reservation_parser.deduplicate_reservations(upcoming)
        sorted_reservations = reservation_parser.sort_reservations(deduped)
    except RuntimeError as exc:
        print(f"Erreur IMAP: {exc}")
        return 1

    _print_report(
        _format_since_display(now),
        examined,
        confirmations,
        sorted_reservations,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
