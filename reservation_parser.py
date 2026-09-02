"""Parser indépendant pour les confirmations de réservation Chronogolf."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from email.message import Message
from email.parser import BytesParser
from email.policy import default
from html.parser import HTMLParser
from typing import Iterable, Sequence
import html
import re
import unicodedata


class ReservationParseError(ValueError):
    """Erreur d’analyse d’une confirmation de réservation."""


@dataclass(frozen=True)
class GolfReservation:
    """Réservation Golf extraite d’un courriel Chronogolf."""

    date: date
    heure: time
    joueurs: list[str]
    reservation_id: str
    received_at: datetime | None = None


FR_MONTHS = {
    "janvier": 1,
    "fevrier": 2,
    "mars": 3,
    "avril": 4,
    "mai": 5,
    "juin": 6,
    "juillet": 7,
    "aout": 8,
    "août": 8,
    "septembre": 9,
    "octobre": 10,
    "novembre": 11,
    "decembre": 12,
    "décembre": 12,
}

EN_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}

ENGLISH_WEEKDAYS = {
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "mon", "tue", "tues", "wed", "thu", "thur", "thurs", "fri", "sat", "sun",
}

FRENCH_WEEKDAYS = {
    "lun",
    "mar",
    "mer",
    "jeu",
    "ven",
    "sam",
    "dim",
}

TIME_RE = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)\b")
STRICT_TIME_RE = re.compile(r"^(?P<hour>[01]?\d|2[0-3]):(?P<minute>[0-5]\d)$")
ENGLISH_TIME_RE = re.compile(
    r"^(?P<hour>1[0-2]|[1-9]):(?P<minute>[0-5]\d)\s*(?P<period>AM|PM)$",
    re.IGNORECASE,
)
PLAYERS_ACTIVITY_RE = re.compile(
    r"^(?P<count>\d+)\s*(?:joueurs?|players?)\s*[\u2022\u00b7•]\s*(?P<activity>.+)$",
    re.IGNORECASE,
)
FRENCH_DATE_RE = re.compile(
    r"^(?:(?P<weekday>[a-zéûêàèâôïçù]+)\.?\s+)?(?P<day>\d{1,2})\s+(?P<month>[a-zàâçéèêëîïôûùüÿœ]+)\s+(?P<year>\d{4})$",
    re.IGNORECASE,
)
ENGLISH_DATE_RE = re.compile(
    r"^(?:(?P<weekday>[A-Za-z]+),?\s+)?(?P<month>[A-Za-z]+)\s+"
    r"(?P<day>\d{1,2}),\s*(?P<year>\d{4})$",
    re.IGNORECASE,
)


def _normalize_text_for_parsing(value: str) -> str:
    """Normalise sauts de ligne, espaces et caractères invisibles."""

    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    normalized = normalized.replace("\u00a0", " ").replace("\u202f", " ").replace("\u2007", " ")
    normalized = "".join(
        " " if unicodedata.category(ch).startswith("Zs") else ch
        for ch in normalized
    )
    normalized = "".join(ch for ch in normalized if unicodedata.category(ch) != "Cf")
    return re.sub(r"\n{3,}", "\n\n", normalized)


def _ascii_lower(value: str) -> str:
    stripped = unicodedata.normalize("NFKD", value)
    stripped = "".join(c for c in stripped if not unicodedata.combining(c))
    return stripped.casefold()


def _normalize_whitespace(value: str) -> str:
    return re.sub(r"[ \t]+", " ", value).strip()


def _parse_day_month_year(raw: str, *, match: re.Match[str] | None) -> date:
    if not match:
        raise ReservationParseError("Date de réservation manquante ou invalide.")

    weekday = _ascii_lower(match.group("weekday") or "")
    if weekday and weekday[:3] not in FRENCH_WEEKDAYS:
        raise ReservationParseError("Jour de la semaine inattendu.")

    day = int(match.group("day"))
    month_name = _ascii_lower(match.group("month"))
    month = FR_MONTHS.get(month_name)
    if month is None:
        raise ReservationParseError("Mois de réservation inconnu.")

    year = int(match.group("year"))
    return date(year=year, month=month, day=day)


def parse_french_date(value: str) -> date:
    """Analyse une date textuelle au format français."""

    normalized = _normalize_whitespace(_ascii_lower(_normalize_text_for_parsing(value)))
    match = FRENCH_DATE_RE.match(normalized)
    return _parse_day_month_year(value, match=match)


def parse_english_date(value: str) -> date:
    """Analyse une date anglaise sans dépendre de la locale système."""

    normalized = _normalize_whitespace(_normalize_text_for_parsing(value))
    match = ENGLISH_DATE_RE.match(normalized)
    if not match:
        raise ReservationParseError("Date de réservation manquante ou invalide.")

    weekday = (match.group("weekday") or "").casefold()
    if weekday and weekday not in ENGLISH_WEEKDAYS:
        raise ReservationParseError("Jour de la semaine inattendu.")
    month = EN_MONTHS.get(match.group("month").casefold())
    if month is None:
        raise ReservationParseError("Mois de réservation inconnu.")
    return date(
        year=int(match.group("year")),
        month=month,
        day=int(match.group("day")),
    )


def parse_hour(value: str) -> time:
    """Analyse une heure courte HH:MM ou une heure anglaise sur 12 heures."""

    normalized = _normalize_whitespace(_normalize_text_for_parsing(value))
    match = STRICT_TIME_RE.match(normalized)
    if match:
        return time(int(match.group("hour")), int(match.group("minute")))

    english_match = ENGLISH_TIME_RE.match(normalized)
    if english_match:
        hour = int(english_match.group("hour")) % 12
        if english_match.group("period").casefold() == "pm":
            hour += 12
        return time(hour, int(english_match.group("minute")))
    raise ReservationParseError("Heure de réservation manquante ou invalide.")


def _is_separator_line(value: str) -> bool:
    """Retourne `True` pour une ligne de séparateur visuel."""

    compact = "".join(ch for ch in value if not ch.isspace())
    if not compact:
        return False
    return all(ch in "_=-" for ch in compact)


def parse_players_and_activity(line: str) -> tuple[int, str]:
    """Analyse la ligne `N joueurs • activité`."""

    normalized = _normalize_whitespace(_normalize_text_for_parsing(line))
    normalized = normalized.replace("\u202f", " ").replace("\u00a0", " ")
    match = PLAYERS_ACTIVITY_RE.match(normalized)
    if not match:
        raise ReservationParseError("Ligne joueurs/activité manquante.")
    number = int(match.group("count"))
    activity = _normalize_whitespace(match.group("activity"))
    if not activity:
        raise ReservationParseError("Activité manquante.")
    return number, activity


def parse_player_name(raw_name: str) -> str:
    """Nettoie un nom dans le format Chronogolf."""

    normalized = _normalize_text_for_parsing(raw_name)
    normalized = re.sub(r"\.\s+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip(" .\t\n")


def parse_players(raw_players: str) -> list[str]:
    """Analyse une liste de joueurs séparés par virgule, `et` ou `and`."""

    normalized = _normalize_text_for_parsing(raw_players)
    normalized = re.sub(r"\set\s+", ", ", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\sand\s+", ", ", normalized, flags=re.IGNORECASE)
    pieces = [_normalize_whitespace(piece) for piece in normalized.split(",")]
    players = [parse_player_name(piece) for piece in pieces if piece.strip()]
    if not players:
        raise ReservationParseError("Noms des joueurs manquants.")
    return players


def parse_reservation_id_line(line: str) -> str | None:
    """Extrait l’ID réservation lorsqu’il existe."""

    normalized = _normalize_whitespace(_normalize_text_for_parsing(line))
    match = re.match(
        r"(?:ID\s+de\s+r[ée]servation|Booking\s+ID)\s*:\s*(.+)",
        normalized,
        re.IGNORECASE,
    )
    if not match:
        return None
    reservation_id = _normalize_whitespace(match.group(1))
    return reservation_id or None


def _find_current_english_block(lines: Sequence[str]) -> tuple[int, date, time] | None:
    """Trouve le bloc anglais actuel grâce à ses quatre lignes structurantes."""

    for index in range(len(lines) - 3):
        if lines[index].casefold() != "reservation confirmed":
            continue
        try:
            reservation_date = parse_english_date(lines[index + 1])
            reservation_hour = parse_hour(lines[index + 2])
            parse_players_and_activity(lines[index + 3])
        except ReservationParseError:
            continue
        return index, reservation_date, reservation_hour
    return None


def _find_historical_english_block(
    lines: Sequence[str],
) -> tuple[int, date, time, str] | None:
    """Trouve l'ancien bloc `Reservation ID / heure / date`."""

    id_pattern = re.compile(
        r"^Reservation\s+(?P<id>[A-Z0-9]+(?:-[A-Z0-9]+)+)$",
        re.IGNORECASE,
    )
    for index in range(len(lines) - 2):
        match = id_pattern.match(lines[index])
        if not match:
            continue
        try:
            reservation_hour = parse_hour(lines[index + 1])
            reservation_date = parse_english_date(lines[index + 2])
        except ReservationParseError:
            continue
        return index, reservation_date, reservation_hour, match.group("id")
    return None


def parse_confirmation_reservation(
    message_body: str,
    *,
    received_at: datetime | None = None,
) -> GolfReservation:
    """Convertit le texte d’une confirmation en `GolfReservation`."""

    content = _normalize_text_for_parsing(message_body)
    raw_lines = [_normalize_whitespace(line) for line in content.split("\n")]
    lines = [line for line in raw_lines if line]

    reservation_date: date | None = None
    reservation_date_index = -1
    reservation_hour: time | None = None
    players: list[str] | None = None
    reservation_id: str | None = None

    current_english = _find_current_english_block(lines)
    historical_english = _find_historical_english_block(lines)
    if current_english is not None:
        reservation_date_index, reservation_date, reservation_hour = current_english
    elif historical_english is not None:
        (
            reservation_date_index,
            reservation_date,
            reservation_hour,
            reservation_id,
        ) = historical_english
    else:
        for index, line in enumerate(lines):
            if FRENCH_DATE_RE.match(_ascii_lower(line)):
                reservation_date = parse_french_date(line)
                reservation_date_index = index
                break

    for index, line in enumerate(
        lines[reservation_date_index + 1 :],
        start=reservation_date_index + 1,
    ):
        lower = _ascii_lower(line)
        if _is_separator_line(line) or lower.startswith("notifications"):
            continue

        if reservation_hour is None:
            try:
                reservation_hour = parse_hour(line)
                continue
            except ReservationParseError:
                pass

        if lower.startswith(("nom", "name")):
            match = re.match(r"(?:nom|name)\s*:\s*(.+)", line, re.IGNORECASE)
            if match:
                players = parse_players(match.group(1))
                continue

        if historical_english is not None and re.match(r"^[●•]", line):
            raw_players = re.sub(r"^[●•\s]+", "", line)
            players = parse_players(raw_players)
            continue

        reservation_id_value = parse_reservation_id_line(line)
        if reservation_id_value is not None:
            reservation_id = reservation_id_value
            continue

    missing_fields: list[str] = []
    if reservation_date is None:
        missing_fields.append("date")
    if reservation_hour is None:
        missing_fields.append("heure")
    if players is None:
        missing_fields.append("joueurs")
    if not reservation_id:
        missing_fields.append("reservation_id")

    if missing_fields:
        raise ReservationParseError(
            "Informations essentielles incomplètes : "
            + ", ".join(missing_fields)
        )

    return GolfReservation(
        date=reservation_date,
        heure=reservation_hour,
        joueurs=players,
        reservation_id=reservation_id,
        received_at=received_at,
    )


def _decode_message_text_part(part: Message) -> str:
    payload = part.get_payload(decode=True)
    if payload is None:
        return ""
    if isinstance(payload, bytes):
        charset = part.get_content_charset() or "utf-8"
        return payload.decode(charset, errors="replace")
    return str(payload)


class _HtmlTextExtractor(HTMLParser):
    """Extracteur HTML minimal pour transformer en texte lisible."""

    def __init__(self) -> None:
        super().__init__()
        self._ignore = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lower = tag.lower()
        if lower in {"script", "style"}:
            self._ignore += 1
        if lower in {"br", "p", "div", "li", "tr", "td", "h1", "h2", "h3"}:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        lower = tag.lower()
        if lower in {"script", "style"} and self._ignore:
            self._ignore -= 1
        if lower in {"p", "div", "li", "tr"}:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._ignore:
            return
        self._parts.append(data)


def _html_to_text(raw_html: str) -> str:
    parser = _HtmlTextExtractor()
    parser.feed(raw_html)
    parser.close()
    return html.unescape("".join(parser._parts))


def extract_confirmation_body_text(message_bytes: bytes) -> str:
    """Extrait un texte propre depuis un courriel MIME (`text/plain`, `text/html`, multipart)."""

    parsed = BytesParser(policy=default).parsebytes(message_bytes)
    if not parsed.is_multipart():
        return _normalize_text_for_parsing(_decode_message_text_part(parsed))

    plain_text: str | None = None
    html_text: str | None = None

    for part in parsed.walk():
        if part.is_multipart():
            continue
        disposition = (part.get_content_disposition() or "").lower()
        if "attachment" in disposition:
            continue

        ctype = part.get_content_type().lower()
        decoded = _decode_message_text_part(part)
        if ctype == "text/plain" and plain_text is None:
            plain_text = decoded
            continue
        if ctype == "text/html" and html_text is None:
            html_text = decoded

    if plain_text is not None:
        return _normalize_text_for_parsing(plain_text)
    if html_text is not None:
        return _normalize_text_for_parsing(_html_to_text(html_text))
    return ""


def reserve_sort_key(reservation: GolfReservation) -> tuple[date, time]:
    return reservation.date, reservation.heure


def sort_reservations(reservations: Sequence[GolfReservation]) -> list[GolfReservation]:
    """Trie des réservations par date puis heure."""

    return sorted(list(reservations), key=reserve_sort_key)


def deduplicate_reservations(reservations: Sequence[GolfReservation]) -> list[GolfReservation]:
    """Supprime les doublons en priorisant le courriel reçu le plus récemment."""

    by_id: dict[str, GolfReservation] = {}
    without_id: list[GolfReservation] = []

    for reservation in reservations:
        if not reservation.reservation_id:
            without_id.append(reservation)
            continue
        current = by_id.get(reservation.reservation_id)
        if current is None:
            by_id[reservation.reservation_id] = reservation
            continue
        if current.received_at is None:
            by_id[reservation.reservation_id] = reservation
            continue
        if reservation.received_at is not None and reservation.received_at > current.received_at:
            by_id[reservation.reservation_id] = reservation

    return without_id + list(by_id.values())


def filter_upcoming_reservations(
    reservations: Sequence[GolfReservation],
    *,
    today: date | None = None,
) -> list[GolfReservation]:
    """Conserve uniquement les réservations aujourd’hui ou futures."""

    limit = today or date.today()
    return [r for r in reservations if r.date >= limit]
