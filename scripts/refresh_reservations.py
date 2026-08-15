"""Mise à jour manuelle du cache de réservations Chronogolf."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from reservation_cache import DEFAULT_CACHE_PATH
from reservation_refresh import ReservationRefreshResult, refresh_reservation_cache
from chronogolf_client import ChronogolfClient, ChronogolfIMAPError, ImapConfigError, ImapConfig


def _human_count_label(count: int) -> str:
    if count == 1:
        return "1 réservation future trouvée."
    return f"{count} réservations futures trouvées."


def refresh_reservations(
    *,
    now: datetime | None = None,
    cache_path: Path | str = DEFAULT_CACHE_PATH,
    client_factory=ChronogolfClient,
    config: ImapConfig | None = None,
) -> int:
    """Rafraîchit le cache local des réservations Chronogolf."""

    try:
        result: ReservationRefreshResult = refresh_reservation_cache(
            now=now,
            cache_path=cache_path,
            client_factory=client_factory,
            config=config,
        )

        print("Connexion Chronogolf réussie.")
        print(_human_count_label(result.reservations_count))
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
