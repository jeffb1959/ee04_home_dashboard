"""Gestion du cache local des réservations Chronogolf."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from typing import Any, Iterable, Mapping
import json
import os
import tempfile

import reservation_parser


PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_CACHE_PATH = PROJECT_ROOT / "data" / "reservation_cache.json"
CURRENT_CACHE_VERSION = 1


class ReservationCacheError(ValueError):
    """Erreur de lecture/écriture du cache de réservations."""


@dataclass(frozen=True)
class ReservationCache:
    """Structure de cache chargée depuis le disque."""

    version: int
    updated_at: datetime
    reservations: list[reservation_parser.GolfReservation]


def reservation_to_record(reservation: reservation_parser.GolfReservation) -> dict[str, Any]:
    """Convertit une réservation en structure JSON sérialisable."""

    return {
        "date": reservation.date.isoformat(),
        "heure": reservation.heure.isoformat(timespec="minutes"),
        "joueurs": list(reservation.joueurs),
        "reservation_id": reservation.reservation_id,
    }


def reservation_from_record(raw: Mapping[str, object]) -> reservation_parser.GolfReservation:
    """Recrée une réservation depuis une structure JSON."""

    date_value = raw.get("date")
    if not isinstance(date_value, str) or not date_value:
        raise ReservationCacheError("Champ `date` manquant ou invalide.")

    heure_value = raw.get("heure")
    if not isinstance(heure_value, str) or not heure_value:
        raise ReservationCacheError("Champ `heure` manquant ou invalide.")

    joueurs_value = raw.get("joueurs")
    if not isinstance(joueurs_value, list):
        raise ReservationCacheError("Champ `joueurs` manquant ou invalide.")
    joueurs = [player for player in joueurs_value if isinstance(player, str)]
    if len(joueurs) != len(joueurs_value) or not joueurs:
        raise ReservationCacheError("Champ `joueurs` manquant ou invalide.")

    reservation_id = raw.get("reservation_id")
    if not isinstance(reservation_id, str) or not reservation_id:
        raise ReservationCacheError("Champ `reservation_id` manquant ou invalide.")

    try:
        reservation_date = date.fromisoformat(date_value)
    except ValueError as exc:
        raise ReservationCacheError("Champ `date` invalide.") from exc

    try:
        reservation_time = time.fromisoformat(heure_value)
    except ValueError as exc:
        raise ReservationCacheError("Champ `heure` invalide.") from exc

    return reservation_parser.GolfReservation(
        date=reservation_date,
        heure=reservation_time,
        joueurs=joueurs,
        reservation_id=reservation_id,
    )


def _validate_cache_payload(payload: Any) -> tuple[datetime, list[reservation_parser.GolfReservation]]:
    if not isinstance(payload, dict):
        raise ReservationCacheError("Le cache n’a pas le bon format.")

    version = payload.get("version")
    if version != CURRENT_CACHE_VERSION:
        raise ReservationCacheError(f"Version de cache non supportée: {version!r}.")

    updated_at_raw = payload.get("updated_at")
    if not isinstance(updated_at_raw, str):
        raise ReservationCacheError("Champ `updated_at` manquant ou invalide.")
    try:
        updated_at = datetime.fromisoformat(updated_at_raw)
    except ValueError as exc:
        raise ReservationCacheError("Champ `updated_at` invalide.") from exc

    reservations_raw = payload.get("reservations")
    if not isinstance(reservations_raw, list):
        raise ReservationCacheError("Champ `reservations` manquant ou invalide.")

    reservations = [
        reservation_from_record(item)
        for item in reservations_raw
        if isinstance(item, Mapping)
    ]
    if len(reservations) != len(reservations_raw):
        raise ReservationCacheError("Entrée de réservation invalide.")

    return updated_at, reservations


def load_reservations_cache(
    *,
    cache_path: Path | str = DEFAULT_CACHE_PATH,
) -> ReservationCache | None:
    """Charge le cache local de réservations."""

    path = Path(cache_path)
    if not path.exists():
        return None

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ReservationCacheError("Le cache local contient un JSON invalide.") from exc
    except OSError as exc:
        raise ReservationCacheError("Impossible de lire le cache local.") from exc

    updated_at, reservations = _validate_cache_payload(payload)

    return ReservationCache(
        version=CURRENT_CACHE_VERSION,
        updated_at=updated_at,
        reservations=reservations,
    )


def _write_cache_atomic(path: Path, content: dict[str, Any]) -> None:
    """Écrit le cache de manière atomique."""

    tmp_file = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=str(path.parent),
            suffix=".tmp",
            delete=False,
        ) as handle:
            tmp_file = Path(handle.name)
            json.dump(content, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())

        os.replace(tmp_file, path)
    except Exception:
        if tmp_file is not None and tmp_file.exists():
            try:
                tmp_file.unlink()
            except OSError:
                pass
        raise


def save_reservations_cache(
    reservations: Iterable[reservation_parser.GolfReservation],
    *,
    updated_at: datetime | None = None,
    cache_path: Path | str = DEFAULT_CACHE_PATH,
) -> ReservationCache:
    """Sauvegarde les réservations dans le cache local."""

    now = updated_at or datetime.now()
    path = Path(cache_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "version": CURRENT_CACHE_VERSION,
        "updated_at": now.isoformat(timespec="seconds"),
        "reservations": [reservation_to_record(reservation) for reservation in reservations],
    }
    _write_cache_atomic(path, payload)

    try:
        path.chmod(0o600)
    except OSError:
        pass

    return load_reservations_cache(cache_path=path)  # type: ignore[return-value]
