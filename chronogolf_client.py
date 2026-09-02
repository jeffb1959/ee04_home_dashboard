"""Client IMAP pour récupérer les confirmations Chronogolf."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, date, timedelta
from email.header import decode_header
from email.parser import BytesParser
from email.policy import default as default_policy
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Callable, Iterable, Mapping
import imaplib
import os
import ssl
import socket

from dotenv import dotenv_values

import reservation_parser

PROJECT_ROOT = Path(__file__).resolve().parent
ENV_FILE = PROJECT_ROOT / ".env"
CONFIRMATION_SUBJECTS = (
    "confirmation de réservation",
    "tee time booking confirmation",
)
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


class ImapConfigError(ValueError):
    """Erreur de configuration IMAP."""


class ChronogolfIMAPError(RuntimeError):
    """Erreur réseau/serveur IMAP pour Chronogolf."""


ImapConnection = object


@dataclass(frozen=True)
class ImapConfig:
    """Paramètres IMAP de la boîte Vidéotron."""

    host: str
    port: int
    user: str
    password: str


@dataclass(frozen=True)
class ChronogolfFetchResult:
    """Résultat de la récupération IMAP avec métriques."""

    search_since: date
    messages_examined: int
    confirmations_found: int
    confirmations_ignored: int
    reservations: list[reservation_parser.GolfReservation]


def _search_start_date(reference: datetime | None = None) -> date:
    return (reference or datetime.now()).date() - timedelta(days=SEARCH_WINDOW_DAYS)


def format_imap_since_date(reference: datetime | None = None) -> str:
    """Retourne la date IMAP (since) au format `DD-MMM-YYYY`."""

    start_date = _search_start_date(reference)
    month = IMAP_MONTHS_EN[start_date.month - 1]
    return f"{start_date.day:02d}-{month}-{start_date.year}"


def decode_mime_subject(raw_subject: str | None) -> str:
    """Décode un sujet MIME potentiellement encodé."""

    if not raw_subject:
        return ""
    fragments: list[str] = []
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
    return any(
        normalized == target or f" {target} " in f" {normalized} "
        for subject in CONFIRMATION_SUBJECTS
        if (target := _normalize_subject(subject))
    )


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


def _parse_imap_message_date(value: str | None) -> datetime | None:
    if not value:
        return None
    return parsedate_to_datetime(value)


def _extract_headers(message_bytes: bytes) -> tuple[str, datetime | None]:
    message = BytesParser(policy=default_policy).parsebytes(message_bytes)
    raw_subject = message["Subject"]
    raw_date = message["Date"]
    return (
        decode_mime_subject(str(raw_subject) if raw_subject else ""),
        _parse_imap_message_date(str(raw_date) if raw_date else None),
    )


def _iter_payload(message_fetch_payload: object) -> Iterable[bytes]:
    if not isinstance(message_fetch_payload, (tuple, list)):
        return ()
    for item in message_fetch_payload:
        if isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], bytes):
            yield item[1]


def _default_imap_factory(
    host: str,
    port: int,
) -> imaplib.IMAP4_SSL:
    return imaplib.IMAP4_SSL(
        host,
        port,
        ssl_context=ssl.create_default_context(),
    )


class ChronogolfClient:
    """Client IMAP dédié aux réservations Chronogolf futures."""

    def __init__(
        self,
        config: ImapConfig,
        *,
        imap_factory: Callable[..., ImapConnection] = _default_imap_factory,
    ) -> None:
        self._config = config
        self._imap_factory = imap_factory

    def get_upcoming_reservations_with_report(
        self,
        reference: datetime | None = None,
        today: date | None = None,
    ) -> ChronogolfFetchResult:
        """Retourne les réservations utiles avec métriques de diagnostic."""

        return _get_reservations(
            config=self._config,
            reference=reference,
            today=today,
            imap_factory=self._imap_factory,
        )

    def get_upcoming_reservations(
        self,
        reference: datetime | None = None,
        today: date | None = None,
    ) -> list[reservation_parser.GolfReservation]:
        """Retourne uniquement la liste des réservations."""

        return self.get_upcoming_reservations_with_report(
            reference=reference,
            today=today,
        ).reservations


def get_upcoming_reservations_with_report(
    config: ImapConfig,
    *,
    reference: datetime | None = None,
    today: date | None = None,
    imap_factory: Callable[..., ImapConnection] = _default_imap_factory,
) -> ChronogolfFetchResult:
    """Fonction utilitaire pour récupérer les réservations Chronogolf."""

    return _get_reservations(
        config=config,
        reference=reference,
        today=today,
        imap_factory=imap_factory,
    )


def get_upcoming_reservations(
    config: ImapConfig,
    *,
    reference: datetime | None = None,
    today: date | None = None,
    imap_factory: Callable[..., ImapConnection] = _default_imap_factory,
) -> list[reservation_parser.GolfReservation]:
    """Retourne uniquement les réservations utiles."""

    return get_upcoming_reservations_with_report(
        config=config,
        reference=reference,
        today=today,
        imap_factory=imap_factory,
    ).reservations


def _get_reservations(
    *, 
    config: ImapConfig,
    reference: datetime | None,
    today: date | None,
    imap_factory: Callable[..., ImapConnection],
) -> ChronogolfFetchResult:
    search_date = _search_start_date(reference)
    search_query = format_imap_since_date(reference)

    messages_examined = 0
    confirmations_found = 0
    confirmations_ignored = 0
    reservations: list[reservation_parser.GolfReservation] = []

    imap = None
    try:
        try:
            imap = imap_factory(config.host, config.port)
        except TypeError:
            imap = imap_factory(config)
        imap.login(config.user, config.password)

        status, _ = imap.select("INBOX", readonly=True)  # type: ignore[attr-defined]
        if status != "OK":
            raise ChronogolfIMAPError("Impossible de sélectionner INBOX en lecture seule.")

        status, raw_ids = imap.search(None, "SINCE", search_query)  # type: ignore[attr-defined]
        if status != "OK":
            raise ChronogolfIMAPError("La recherche IMAP a échoué.")

        message_ids = (
            raw_ids[0].decode("utf-8").split()
            if raw_ids and raw_ids[0] is not None
            else []
        )

        for message_id in message_ids:
            header_status, header_data = imap.fetch(  # type: ignore[attr-defined]
                message_id,
                "(BODY.PEEK[HEADER.FIELDS (SUBJECT DATE)])",
            )
            if header_status != "OK" or not header_data:
                continue

            header_payload = b"".join(_iter_payload(header_data))
            if not header_payload:
                continue

            raw_subject, received_at = _extract_headers(header_payload)
            messages_examined += 1
            if not is_confirmation_subject(raw_subject):
                continue

            confirmations_found += 1
            body_status, body_data = imap.fetch(  # type: ignore[attr-defined]
                message_id,
                "(BODY.PEEK[])",
            )

            if body_status != "OK" or not body_data:
                confirmations_ignored += 1
                continue

            body_payload = b"".join(_iter_payload(body_data))
            if not body_payload:
                confirmations_ignored += 1
                continue

            try:
                body_text = reservation_parser.extract_confirmation_body_text(body_payload)
                reservation = reservation_parser.parse_confirmation_reservation(
                    body_text,
                    received_at=received_at,
                )
            except reservation_parser.ReservationParseError:
                confirmations_ignored += 1
                continue

            reservations.append(reservation)

    except (socket.gaierror, OSError) as exc:
        raise ChronogolfIMAPError("Erreur réseau IMAP.") from exc
    except ssl.SSLError as exc:
        raise ChronogolfIMAPError("Erreur SSL IMAP.") from exc
    except imaplib.IMAP4.error as exc:
        raise ChronogolfIMAPError("Échec d’authentification IMAP.") from exc
    finally:
        if imap is not None:
            try:
                imap.close()  # type: ignore[attr-defined]
            except Exception:
                pass
            try:
                imap.logout()  # type: ignore[attr-defined]
            except Exception:
                pass

    limit = today or date.today()
    upcoming = reservation_parser.filter_upcoming_reservations(
        reservations,
        today=limit,
    )
    deduplicated = reservation_parser.deduplicate_reservations(upcoming)
    sorted_reservations = reservation_parser.sort_reservations(deduplicated)

    return ChronogolfFetchResult(
        search_since=search_date,
        messages_examined=messages_examined,
        confirmations_found=confirmations_found,
        confirmations_ignored=confirmations_ignored,
        reservations=sorted_reservations,
    )
