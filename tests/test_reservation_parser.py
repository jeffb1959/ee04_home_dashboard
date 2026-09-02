"""Tests unitaires pour `reservation_parser.py`."""

from __future__ import annotations

from datetime import date, datetime, time
from email.message import EmailMessage
from pathlib import Path
import sys

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import reservation_parser


PLAIN_CONFIRMATION_TEXT = """\
Réservation confirmée

Club de golf Exemple

Réservation confirmée
mar. 18 août 2026
08:57
3 joueurs • Parcours de golf (18 trous)
Lac du Chêne

Nom : Alice. Tremblay, Bob Martin et Charles. Gagnon
ID de réservation : ABCD-1234
"""

HTML_CONFIRMATION_TEXT = """\
<html><body>
<p>Réservation confirmée</p>
<p>Club de golf Exemple</p>
<p>Réservation confirmée</p>
<p>mar. 18 août 2026</p>
<p>08:57</p>
<p>3 joueurs • Parcours de golf (18 trous)</p>
<p>Lac du Chêne</p>
<p>Nom : Alice. Tremblay, Bob Martin et Charles. Gagnon</p>
<p>ID de réservation : ABCD-1234</p>
</body></html>
"""


def test_parse_french_date_with_weekday() -> None:
    """Le parseur comprend une date français avec jour de semaine."""

    assert reservation_parser.parse_french_date("mar. 18 août 2026") == date(2026, 8, 18)


@pytest.mark.parametrize(
    "value",
    ("Fri, September 4, 2026", "September 4, 2026"),
)
def test_parse_english_date_with_or_without_weekday(value: str) -> None:
    """Les dates anglaises sont analysées sans dépendre de la locale système."""

    assert reservation_parser.parse_english_date(value) == date(2026, 9, 4)


def test_parse_hour() -> None:
    """Le parseur comprend HH:MM."""

    assert reservation_parser.parse_hour("08:57") == time(8, 57)


@pytest.mark.parametrize(
    ("value", "expected"),
    (
        ("8:30 AM", time(8, 30)),
        ("1:05 PM", time(13, 5)),
        ("12:00 AM", time(0, 0)),
        ("12:00 PM", time(12, 0)),
    ),
)
def test_parse_english_hour(value: str, expected: time) -> None:
    """Les heures anglaises AM/PM sont converties au format 24 heures."""

    assert reservation_parser.parse_hour(value) == expected


def test_parse_hour_rejects_non_full_line_text() -> None:
    """Les valeurs `HH:MM` insérées dans d'autres lignes sont rejetées."""

    with pytest.raises(reservation_parser.ReservationParseError):
        reservation_parser.parse_hour("(UTC-05:00) Eastern Time")

    with pytest.raises(reservation_parser.ReservationParseError):
        reservation_parser.parse_hour("Envoyé : 13 août 2026 08:57")

    with pytest.raises(reservation_parser.ReservationParseError):
        reservation_parser.parse_hour("texte 08:57 autre texte")


def test_parse_players_and_activity() -> None:
    """La ligne joueurs+activité est extraite correctement."""

    count, activity = reservation_parser.parse_players_and_activity(
        "3 joueurs • Parcours de golf (18 trous)"
    )
    assert count == 3
    assert activity == "Parcours de golf (18 trous)"


def test_parse_location_from_confirmation_body() -> None:
    """Les joueurs sont récupérés depuis le corps de confirmation."""

    reservation = reservation_parser.parse_confirmation_reservation(
        """\
Réservation confirmée

Club de golf Exemple

Réservation confirmée
mer. 19 septembre 2026
09:30
3 joueurs • Parcours de golf (18 trous)
Terrain du Parc
Nom : Alice Martin, Bob B.
ID de réservation : TOUR-99
"""
    )
    assert reservation.joueurs == ["Alice Martin", "Bob B"]


def test_parse_three_players_with_commas_and_et() -> None:
    """Les noms séparés par virgule et `et` sont convertis en liste."""

    players = reservation_parser.parse_players("Alice Martin, Bob Durand et Charles Léon")
    assert players == ["Alice Martin", "Bob Durand", "Charles Léon"]


def test_parse_three_players_with_name_and_and() -> None:
    """Le séparateur anglais `and` et les points parasites sont acceptés."""

    players = reservation_parser.parse_players(
        "Alice. Martin, Bob. Martin, and Charles Martin"
    )
    assert players == ["Alice Martin", "Bob Martin", "Charles Martin"]


def test_clean_player_name_with_spurious_dot() -> None:
    """Le point parasite entre prénom et nom est supprimé proprement."""

    assert reservation_parser.parse_player_name("Alice. Tremblay") == "Alice Tremblay"


def test_parse_reservation_id_line() -> None:
    """L’ID de réservation est extrait du label connu."""

    reservation_id = reservation_parser.parse_reservation_id_line(
        "ID de réservation : ABCD-1234"
    )
    assert reservation_id == "ABCD-1234"


def test_parse_booking_id_line() -> None:
    """L’identifiant anglais `Booking ID` est extrait."""

    assert reservation_parser.parse_reservation_id_line(
        "Booking ID: TEST-5678"
    ) == "TEST-5678"


def test_parse_complete_current_english_confirmation() -> None:
    """Le format anglais actuel produit une réservation complète."""

    reservation = reservation_parser.parse_confirmation_reservation(
        """\
Reservation confirmed
Example Golf Club
Reservation confirmed
Fri, September 4, 2026
8:30 AM
3 players • Round of golf (18 holes)
Example Course
Name: Alice. Martin, Bob. Martin, and Charles Martin
Booking ID: TEST-1234
"""
    )

    assert reservation.date == date(2026, 9, 4)
    assert reservation.heure == time(8, 30)
    assert reservation.joueurs == ["Alice Martin", "Bob Martin", "Charles Martin"]
    assert reservation.reservation_id == "TEST-1234"


def test_english_confirmation_ignores_forwarded_header_date() -> None:
    """Une date antérieure au bloc structuré n'est pas choisie comme départ."""

    reservation = reservation_parser.parse_confirmation_reservation(
        """\
Sent: January 2, 2026
January 2, 2026
Reservation confirmed
September 4, 2026
1:05 PM
2 players • Round of golf (18 holes)
Example Course
Name: Alice Martin and Bob Martin
Booking ID: TEST-5678
"""
    )

    assert reservation.date == date(2026, 9, 4)
    assert reservation.heure == time(13, 5)


def test_parse_complete_historical_english_confirmation() -> None:
    """Le format anglais historique choisit la date de son bloc structuré."""

    reservation = reservation_parser.parse_confirmation_reservation(
        """\
October 1, 2025
Tee Time Reservation Confirmation
Reservation 0H8D-6F4Z
11:45 AM
October 18, 2025
Example Course
Round of golf (18 holes)
● ● ● Alice. Martin, Bob. Martin, and Guest
"""
    )

    assert reservation.date == date(2025, 10, 18)
    assert reservation.heure == time(11, 45)
    assert reservation.joueurs == ["Alice Martin", "Bob Martin", "Guest"]
    assert reservation.reservation_id == "0H8D-6F4Z"


def test_parse_complete_confirmation() -> None:
    """Le parseur reconstruit une réservation complète depuis un texte valide."""

    reservation = reservation_parser.parse_confirmation_reservation(
        PLAIN_CONFIRMATION_TEXT,
        received_at=datetime(2026, 8, 10, 12, 0, 0),
    )

    assert reservation.date == date(2026, 8, 18)
    assert reservation.heure == time(8, 57)
    assert reservation.joueurs == ["Alice Tremblay", "Bob Martin", "Charles Gagnon"]
    assert reservation.reservation_id == "ABCD-1234"
    assert reservation.received_at == datetime(2026, 8, 10, 12, 0, 0)


def test_parse_format1_confirmation_with_timezone_and_full_block() -> None:
    """Le vrai format 1 avec ligne UTC ne doit pas influencer l’heure de départ."""

    text = """\
(UTC-05:00) Eastern Time

Club de golf Lorette

Réservation confirmée
mar. 18 août 2026
08:57
3 joueurs • Parcours de golf (18 trous)
Terrain Lorette

Nom : Alice. Tremblay, Bob Martin et Charles. Gagnon
ID de réservation : TEST-1234
"""
    reservation = reservation_parser.parse_confirmation_reservation(text)

    assert reservation.date == date(2026, 8, 18)
    assert reservation.heure == time(8, 57)
    assert reservation.joueurs == ["Alice Tremblay", "Bob Martin", "Charles Gagnon"]
    assert reservation.reservation_id == "TEST-1234"


def test_parse_format2_confirmation_block() -> None:
    """Le format 2 est reconnu avec date, heure, joueurs et activité réels."""

    text = """\
Club de golf Lorette

Réservation confirmée

mer. 19 août 2026
08:12
4 joueurs • Ronde de golf (18 trous)
Terrain Lorette

Nom : Alice Martin, Bob. Dupont, Charles Gagnon et Diane Roy
ID de réservation : TEST-5678
"""
    reservation = reservation_parser.parse_confirmation_reservation(text)

    assert reservation.date == date(2026, 8, 19)
    assert reservation.heure == time(8, 12)
    assert reservation.joueurs == [
        "Alice Martin",
        "Bob Dupont",
        "Charles Gagnon",
        "Diane Roy",
    ]
    assert reservation.reservation_id == "TEST-5678"


def test_parse_with_non_breaking_spaces() -> None:
    """Les espaces insécables sont acceptés."""

    text = (
        "Réservation confirmée\n\n"
        "Club de golf Exemple\n\n"
        "Réservation confirmée\n"
        "mar.\u00a0\u2007 18\u00a0août\u00a02026\n"
        "08:57\n"
        "3\u00a0joueurs\u202f\u00b7\u00a0Parcours\u00a0de\u00a0golf\u00a0(18\u00a0trous)\n"
        "Lac\u00a0du\u00a0Chêne\n\n"
        "Nom\u00a0:\u00a0Alice.\u00a0Tremblay\n"
        "ID\u00a0de\u00a0réservation\u00a0:\u00a0ABCD-1234\n"
    )
    reservation = reservation_parser.parse_confirmation_reservation(text)
    assert reservation.joueurs == ["Alice Tremblay"]


def test_discard_past_reservation() -> None:
    """Un départ antérieur à aujourd’hui est rejeté."""

    reservations = [
        reservation_parser.GolfReservation(
            date=date(2026, 8, 9),
            heure=time(8, 0),
            joueurs=["A", "B"],
            reservation_id="R-1",
        ),
        reservation_parser.GolfReservation(
            date=date(2026, 8, 10),
            heure=time(9, 0),
            joueurs=["C", "D"],
            reservation_id="R-2",
        ),
    ]

    filtered = reservation_parser.filter_upcoming_reservations(
        reservations,
        today=date(2026, 8, 10),
    )

    assert len(filtered) == 1
    assert filtered[0].date == date(2026, 8, 10)


def test_keep_today_reservation() -> None:
    """Une réservation d’aujourd’hui est conservée."""

    reservation = reservation_parser.GolfReservation(
        date=date(2026, 8, 10),
        heure=time(12, 0),
        joueurs=["A"],
        reservation_id="R-3",
    )

    assert reservation_parser.filter_upcoming_reservations(
        [reservation],
        today=date(2026, 8, 10),
    ) == [reservation]


def test_keep_future_reservation() -> None:
    """Une réservation future est conservée."""

    reservation = reservation_parser.GolfReservation(
        date=date(2026, 8, 11),
        heure=time(12, 0),
        joueurs=["A"],
        reservation_id="R-4",
    )

    filtered = reservation_parser.filter_upcoming_reservations(
        [reservation],
        today=date(2026, 8, 10),
    )
    assert filtered == [reservation]


def test_sort_reservations_by_date_then_time() -> None:
    """Le tri est d’abord par date puis par heure croissante."""

    first = reservation_parser.GolfReservation(
        date=date(2026, 8, 12),
        heure=time(9, 0),
        joueurs=["A", "B"],
        reservation_id="R-1",
    )
    second = reservation_parser.GolfReservation(
        date=date(2026, 8, 11),
        heure=time(18, 0),
        joueurs=["C", "D"],
        reservation_id="R-2",
    )
    third = reservation_parser.GolfReservation(
        date=date(2026, 8, 11),
        heure=time(9, 0),
        joueurs=["E", "F"],
        reservation_id="R-3",
    )

    sorted_reservations = reservation_parser.sort_reservations([first, second, third])
    assert sorted_reservations == [third, second, first]


def test_deduplicate_by_reservation_id_keep_latest_received() -> None:
    """Le même ID ne doit apparaître qu’une fois."""

    first = reservation_parser.GolfReservation(
        date=date(2026, 8, 11),
        heure=time(9, 0),
        joueurs=["A", "B"],
        reservation_id="DUP-1",
        received_at=datetime(2026, 8, 1, 12, 0, 0),
    )
    second = reservation_parser.GolfReservation(
        date=date(2026, 8, 11),
        heure=time(9, 0),
        joueurs=["A", "B"],
        reservation_id="DUP-1",
        received_at=datetime(2026, 8, 2, 12, 0, 0),
    )
    different = reservation_parser.GolfReservation(
        date=date(2026, 8, 12),
        heure=time(9, 0),
        joueurs=["C", "D"],
        reservation_id="DUP-2",
        received_at=datetime(2026, 8, 1, 12, 0, 0),
    )

    deduped = reservation_parser.deduplicate_reservations([first, second, different])
    assert len(deduped) == 2
    assert second in deduped
    assert different in deduped


def test_incomplete_confirmation_is_reported() -> None:
    """Un message incomplet expose explicitement les champs manquants."""

    with pytest.raises(reservation_parser.ReservationParseError) as exc:
        reservation_parser.parse_confirmation_reservation(
            """\
Réservation confirmée
mar. 19 août 2026
08:57
Nom : Alice. Tremblay
"""
        )
    assert str(exc.value) == "Informations essentielles incomplètes : reservation_id"
    assert "Alice" not in str(exc.value)


def test_extract_message_plain_body() -> None:
    """Le corps `text/plain` est lu directement lorsqu’il existe."""

    msg = EmailMessage()
    msg["From"] = "noreply@example.test"
    msg["To"] = "user@example.test"
    msg["Subject"] = "Confirmation de réservation"
    msg.set_content(PLAIN_CONFIRMATION_TEXT, subtype="plain", charset="utf-8")

    body = reservation_parser.extract_confirmation_body_text(msg.as_bytes())
    assert "3 joueurs" in body
    assert "ID de réservation" in body


def test_extract_message_html_or_multipart() -> None:
    """Un message sans text/plain peut être extrait depuis du HTML."""

    msg = EmailMessage()
    msg["From"] = "noreply@example.test"
    msg["To"] = "user@example.test"
    msg["Subject"] = "Confirmation de réservation"
    msg.set_content(HTML_CONFIRMATION_TEXT, subtype="html", charset="utf-8")

    body = reservation_parser.extract_confirmation_body_text(msg.as_bytes())
    assert "Lac du Chêne" in body
    assert "ID de réservation" in body
