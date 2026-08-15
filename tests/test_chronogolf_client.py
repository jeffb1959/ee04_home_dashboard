"""Tests unitaires pour `chronogolf_client.py`."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
import sys

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import chronogolf_client


def _make_header_bytes(subject: str, date_header: str) -> bytes:
    """Construit des entêtes IMAP minimalistes."""

    return (
        f"Subject: {subject}\r\nDate: {date_header}\r\n\r\n"
    ).encode("utf-8")


def _make_confirmation_body(
    *,
    date_line: str,
    heure: str,
    joueurs: str,
    reservation_id: str,
) -> bytes:
    """Construit un corps de confirmation valide."""

    text = "\n".join(
        (
            "Réservation confirmée",
            "",
            "Club de golf Exemple",
            "",
            "Réservation confirmée",
            date_line,
            heure,
            joueurs,
            "Terrain Exemple",
            "",
            "Nom : Alice Martin, Bob Martin et Charles Martin",
            f"ID de réservation : {reservation_id}",
        )
    )
    return text.encode("utf-8")


class FakeImap:
    """IMAP simulé pour les tests."""

    def __init__(
        self,
        search_data: str,
        headers: dict[str, bytes],
        bodies: dict[str, bytes],
        close_status: str = "OK",
        header_status: str = "OK",
        select_status: str = "OK",
        search_status: str = "OK",
        body_status: str = "OK",
        logout_status: str = "OK",
    ) -> None:
        self.search_data = search_data
        self.headers = headers
        self.bodies = bodies
        self.select_status = select_status
        self.search_status = search_status
        self.header_status = header_status
        self.body_status = body_status
        self.close_status = close_status
        self.logout_status = logout_status
        self.calls: list[tuple] = []

    def login(self, user: str, password: str) -> None:
        self.calls.append(("login", user, password))

    def select(self, mailbox: str, readonly: bool = False) -> tuple[str, list[bytes]]:
        self.calls.append(("select", mailbox, readonly))
        return self.select_status, [b""]

    def search(self, *_: object, **__: object) -> tuple[str, list[bytes]]:
        self.calls.append(("search", tuple(_), frozenset(__.items())))
        return self.search_status, [self.search_data.encode("utf-8")]

    def fetch(self, message_id: str, query: str) -> tuple[str, list[tuple]]:
        self.calls.append(("fetch", message_id, query))
        if "BODY.PEEK[HEADER.FIELDS" in query:
            payload = self.headers.get(message_id)
            if payload is None:
                return "NO", []
            return self.header_status, [(b"HEADER", payload)]
        if "BODY.PEEK[]" in query:
            payload = self.bodies.get(message_id)
            if payload is None:
                return "NO", []
            return self.body_status, [(b"BODY", payload)]
        return "NO", []

    def close(self) -> tuple[str, list[bytes]]:
        self.calls.append(("close",))
        return self.close_status, []

    def logout(self) -> tuple[str, list[bytes]]:
        self.calls.append(("logout",))
        return self.logout_status, []


def _make_client(
    fake: FakeImap,
) -> tuple[chronogolf_client.ChronogolfClient, dict[str, object]]:
    """Crée un client Chronogolf avec IMAP simulé."""

    config = chronogolf_client.ImapConfig(
        host="imap.test",
        port=993,
        user="user@example.com",
        password="secret-password",
    )

    def factory(_: str, __: int) -> FakeImap:
        return fake

    return chronogolf_client.ChronogolfClient(config, imap_factory=factory), {"config": config}


def test_load_imap_config_prefers_environment_variables(tmp_path: Path) -> None:
    """Les variables d’environnement doivent prendre la priorité sur `.env`."""

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

    config = chronogolf_client.load_imap_config(
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


def test_select_inbox_is_readonly_and_search_window_is_last_7_days() -> None:
    """Le client doit sélectionner INBOX en lecture seule et chercher depuis J-7."""

    fake = FakeImap(
        search_data="",
        headers={},
        bodies={},
    )
    client, _ = _make_client(fake)
    reference = datetime(2026, 8, 14, 10, 0, 0)

    client.get_upcoming_reservations_with_report(reference=reference)

    assert ("select", "INBOX", True) in fake.calls
    assert (
        "search",
        (None, "SINCE", "07-Aug-2026"),
        frozenset(),
    ) in fake.calls


def test_fetch_uses_body_peek() -> None:
    """Le contenu doit être lu via `BODY.PEEK[]`."""

    fake = FakeImap(
        search_data="1",
        headers={
            "1": _make_header_bytes(
                "Confirmation de réservation",
                "Tue, 11 Aug 2026 11:00:00 +0000",
            ),
        },
        bodies={
            "1": _make_confirmation_body(
                date_line="mar. 18 août 2026",
                heure="08:57",
                joueurs="3 joueurs • Parcours de golf (18 trous)",
                reservation_id="A-1",
            ),
        },
    )
    client, _ = _make_client(fake)
    client.get_upcoming_reservations_with_report(reference=datetime(2026, 8, 14))

    assert ("fetch", "1", "(BODY.PEEK[])") in fake.calls


def test_only_confirmation_subjects_are_parsed() -> None:
    """Un sujet différent doit être ignoré sans lecture du corps."""

    fake = FakeImap(
        search_data="1 2",
        headers={
            "1": _make_header_bytes(
                "Quelque chose d’autre",
                "Mon, 01 Aug 2026 10:00:00 +0000",
            ),
            "2": _make_header_bytes(
                "Confirmation de réservation",
                "Tue, 11 Aug 2026 11:00:00 +0000",
            ),
        },
        bodies={
            "2": _make_confirmation_body(
                date_line="mar. 18 août 2026",
                heure="08:57",
                joueurs="3 joueurs • Parcours de golf (18 trous)",
                reservation_id="CONF-2",
            ),
        },
    )
    client, _ = _make_client(fake)

    result = client.get_upcoming_reservations_with_report(reference=datetime(2026, 8, 14))

    assert result.confirmations_found == 1
    assert len(result.reservations) == 1
    assert result.reservations[0].reservation_id == "CONF-2"
    assert ("fetch", "2", "(BODY.PEEK[])") in fake.calls
    assert ("fetch", "1", "(BODY.PEEK[])") not in fake.calls


def test_confirmation_parse_error_is_ignored_without_stopping_others() -> None:
    """Une confirmation invalide ne bloque pas les autres messages."""

    fake = FakeImap(
        search_data="1 2",
        headers={
            "1": _make_header_bytes("Confirmation de réservation", "Tue, 10 Aug 2026 10:00:00 +0000"),
            "2": _make_header_bytes("Confirmation de réservation", "Tue, 11 Aug 2026 11:00:00 +0000"),
        },
        bodies={
            "1": b"mauvais contenu",
            "2": _make_confirmation_body(
                date_line="mar. 18 août 2026",
                heure="08:57",
                joueurs="3 joueurs • Parcours de golf (18 trous)",
                reservation_id="VALID-2",
            ),
        },
    )
    client, _ = _make_client(fake)

    result = client.get_upcoming_reservations_with_report(reference=datetime(2026, 8, 14))

    assert result.confirmations_found == 2
    assert result.confirmations_ignored == 1
    assert len(result.reservations) == 1
    assert result.reservations[0].reservation_id == "VALID-2"


def test_past_reservations_are_rejected_and_today_kept() -> None:
    """La logique de tri temporel doit conserver aujourd’hui et futures uniquement."""

    fake = FakeImap(
        search_data="1 2 3",
        headers={
            "1": _make_header_bytes("Confirmation de réservation", "Mon, 01 Aug 2026 08:00:00 +0000"),
            "2": _make_header_bytes("Confirmation de réservation", "Mon, 01 Aug 2026 09:00:00 +0000"),
            "3": _make_header_bytes("Confirmation de réservation", "Mon, 01 Aug 2026 10:00:00 +0000"),
        },
        bodies={
            "1": _make_confirmation_body(
                date_line="mar. 10 août 2026",
                heure="08:57",
                joueurs="3 joueurs • Parcours de golf (18 trous)",
                reservation_id="PAST",
            ),
            "2": _make_confirmation_body(
                date_line="mar. 14 août 2026",
                heure="08:57",
                joueurs="3 joueurs • Parcours de golf (18 trous)",
                reservation_id="TODAY",
            ),
            "3": _make_confirmation_body(
                date_line="mer. 15 août 2026",
                heure="08:57",
                joueurs="3 joueurs • Parcours de golf (18 trous)",
                reservation_id="FUTURE",
            ),
        },
    )
    client, _ = _make_client(fake)

    result = client.get_upcoming_reservations_with_report(
        reference=datetime(2026, 8, 14),
        today=date(2026, 8, 14),
    )

    assert [r.reservation_id for r in result.reservations] == ["TODAY", "FUTURE"]


def test_deduplicate_by_reservation_id_keep_latest_received_at() -> None:
    """Les doublons doivent être supprimés par `reservation_id`."""

    fake = FakeImap(
        search_data="1 2",
        headers={
            "1": _make_header_bytes("Confirmation de réservation", "Mon, 01 Aug 2026 08:00:00 +0000"),
            "2": _make_header_bytes("Confirmation de réservation", "Tue, 02 Aug 2026 08:00:00 +0000"),
        },
        bodies={
            "1": _make_confirmation_body(
                date_line="mer. 19 août 2026",
                heure="08:57",
                joueurs="3 joueurs • Parcours de golf (18 trous)",
                reservation_id="DUP-1",
            ),
            "2": _make_confirmation_body(
                date_line="mer. 20 août 2026",
                heure="08:57",
                joueurs="3 joueurs • Parcours de golf (18 trous)",
                reservation_id="DUP-1",
            ),
        },
    )
    client, _ = _make_client(fake)
    result = client.get_upcoming_reservations_with_report(reference=datetime(2026, 8, 14))

    assert len(result.reservations) == 1
    assert result.reservations[0].reservation_id == "DUP-1"
    assert result.reservations[0].date.isoformat() == "2026-08-20"


def test_sort_reservations_by_date_then_time() -> None:
    """Le résultat doit être trié par date puis heure."""

    fake = FakeImap(
        search_data="1 2 3",
        headers={
            "1": _make_header_bytes("Confirmation de réservation", "Mon, 01 Aug 2026 08:00:00 +0000"),
            "2": _make_header_bytes("Confirmation de réservation", "Mon, 01 Aug 2026 09:00:00 +0000"),
            "3": _make_header_bytes("Confirmation de réservation", "Mon, 01 Aug 2026 10:00:00 +0000"),
        },
        bodies={
            "1": _make_confirmation_body(
                date_line="mar. 19 août 2026",
                heure="09:00",
                joueurs="3 joueurs • Parcours de golf (18 trous)",
                reservation_id="A",
            ),
            "2": _make_confirmation_body(
                date_line="mer. 20 août 2026",
                heure="08:00",
                joueurs="3 joueurs • Parcours de golf (18 trous)",
                reservation_id="B",
            ),
            "3": _make_confirmation_body(
                date_line="mer. 20 août 2026",
                heure="07:00",
                joueurs="3 joueurs • Parcours de golf (18 trous)",
                reservation_id="C",
            ),
        },
    )
    client, _ = _make_client(fake)
    result = client.get_upcoming_reservations_with_report(reference=datetime(2026, 8, 18))

    assert [r.reservation_id for r in result.reservations] == ["A", "C", "B"]


def test_no_reservations_returns_empty_list() -> None:
    """Aucune confirmation valide ne doit produire une liste vide."""

    fake = FakeImap(search_data="", headers={}, bodies={})
    client, _ = _make_client(fake)

    assert client.get_upcoming_reservations_with_report(reference=datetime(2026, 8, 14)).reservations == []


def test_imap_error_is_propagated_without_password() -> None:
    """Une erreur IMAP doit être remontée proprement sans révéler le mot de passe."""

    fake = FakeImap(
        search_data="",
        headers={},
        bodies={},
        select_status="NO",
    )
    client, _ = _make_client(fake)

    with pytest.raises(chronogolf_client.ChronogolfIMAPError) as exc_info:
        client.get_upcoming_reservations_with_report(reference=datetime(2026, 8, 14))

    assert "secret-password" not in str(exc_info.value)


def test_player_count_from_joueurs_list() -> None:
    """Le nombre de joueurs est dérivé de la liste de joueurs parsée."""

    fake = FakeImap(
        search_data="1",
        headers={
            "1": _make_header_bytes(
                "Confirmation de réservation",
                "Mon, 01 Aug 2026 10:00:00 +0000",
            ),
        },
        bodies={
            "1": _make_confirmation_body(
                date_line="mar. 19 août 2026",
                heure="08:57",
                joueurs="3 joueurs • Ronde de golf (18 trous)",
                reservation_id="TEAM",
            ),
        },
    )
    client, _ = _make_client(fake)
    result = client.get_upcoming_reservations_with_report(reference=datetime(2026, 8, 14))

    assert len(result.reservations) == 1
    assert len(result.reservations[0].joueurs) == 3
