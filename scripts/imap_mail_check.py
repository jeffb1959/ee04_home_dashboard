"""Validation IMAP en lecture seule pour la boîte Vidéotron."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from chronogolf_client import (
    ChronogolfIMAPError,
    ImapConfigError,
    ImapConfig,
    decode_mime_subject,
    format_imap_since_date,
    get_upcoming_reservations_with_report,
    is_confirmation_subject,
    load_imap_config,
    ENV_FILE,
)


def _print_report(
    search_date: str,
    examined: int,
    confirmations: int,
    reservations: list,
) -> None:
    """Affiche un rapport humain lisible."""

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


def fetch_confirmation_reservations(config, reference=None, today=None):
    """Compatibilité avec l’ancienne API de script."""

    result = get_upcoming_reservations_with_report(
        config,
        reference=reference,
        today=today,
    )
    return (
        format_imap_since_date(reference),
        result.messages_examined,
        result.confirmations_found,
        result.reservations,
    )


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
        print(f"Connexion IMAP réussie : {config.host}")
        result = get_upcoming_reservations_with_report(
            config,
            reference=now,
            today=now.date(),
        )
    except ChronogolfIMAPError as exc:
        print(f"Erreur IMAP: {exc}")
        return 1

    _print_report(
        result.search_since.isoformat(),
        result.messages_examined,
        result.confirmations_found,
        result.reservations,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
