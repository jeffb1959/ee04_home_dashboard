"""Mise à jour manuelle du cache de réservations Chronogolf."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

from chronogolf_client import ChronogolfClient, ChronogolfIMAPError, ImapConfigError, ImapConfig, load_imap_config, ENV_FILE
from reservation_cache import save_reservations_cache, DEFAULT_CACHE_PATH


def _human_count_label(count: int) -> str:
    if count == 1:
        return "1 réservation future trouvée."
    return f"{count} réservations futures trouvées."


def refresh_reservations(
    *,
    now: datetime | None = None,
    cache_path=DEFAULT_CACHE_PATH,
    client_factory=ChronogolfClient,
    config: ImapConfig | None = None,
) -> int:
    """Rafraîchit le cache local des réservations Chronogolf."""

    now = now or datetime.now()
    try:
        if config is None:
            load_dotenv(ENV_FILE)
            config = load_imap_config()

        print("Connexion Chronogolf réussie.")
        client = client_factory(config)
        reservations = client.get_upcoming_reservations(reference=now, today=now.date())

        save_reservations_cache(
            reservations,
            updated_at=now,
            cache_path=cache_path,
        )

        print(_human_count_label(len(reservations)))
        print(f"Cache mis à jour : {cache_path}")
        return 0
    except (ChronogolfIMAPError, ImapConfigError):
        print("Échec de mise à jour Chronogolf.")
        print("Dernier cache conservé.")
        return 1


def main() -> int:
    """Point d’entrée script."""

    return refresh_reservations()


if __name__ == "__main__":
    raise SystemExit(main())
