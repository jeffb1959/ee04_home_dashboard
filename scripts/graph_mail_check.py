"""Validation Microsoft Graph en lecture seule (Exchange professionnel)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence
import os

import msal
import requests
from dotenv import dotenv_values, load_dotenv

GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
GRAPH_SCOPES = ("Mail.Read", "User.Read")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = PROJECT_ROOT / ".env"
MSAL_CACHE_FILE = PROJECT_ROOT / "data" / "msal_token_cache.json"
CHRONOGOLF_SENDER = "notifications@chronogolf.ca"


@dataclass(frozen=True)
class GraphConfig:
    """Paramètres Microsoft Graph."""

    client_id: str
    tenant_id: str
    account: str | None = None


class GraphConfigError(ValueError):
    """Erreur de configuration Microsoft Graph."""


def build_authority(tenant_id: str) -> str:
    """Construit l’autorité tenant Microsoft."""

    return f"https://login.microsoftonline.com/{tenant_id}"


def load_graph_config(
    env_file: Path = ENV_FILE,
    environ: Mapping[str, str] | None = None,
) -> GraphConfig:
    """Charge la config Graph depuis `.env` et l’environnement courant."""

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

    client_id = get_value("MS_GRAPH_CLIENT_ID")
    tenant_id = get_value("MS_GRAPH_TENANT_ID")

    missing = [name for name in ("MS_GRAPH_CLIENT_ID", "MS_GRAPH_TENANT_ID") if not get_value(name)]
    if missing:
        raise GraphConfigError(
            "Variables de configuration Microsoft Graph manquantes: "
            + ", ".join(missing)
        )

    account = get_value("MS_GRAPH_ACCOUNT") or None
    return GraphConfig(
        client_id=client_id,
        tenant_id=tenant_id,
        account=account,
    )


def load_token_cache(cache_file: Path) -> msal.SerializableTokenCache:
    """Charge le cache MSAL depuis le disque."""

    cache = msal.SerializableTokenCache()
    if cache_file.is_file():
        cache_data = cache_file.read_text(encoding="utf-8").strip()
        if cache_data:
            cache.deserialize(cache_data)
    return cache


def save_token_cache(cache: msal.SerializableTokenCache, cache_file: Path) -> None:
    """Sauvegarde le cache MSAL local."""

    if not cache.has_state_changed:
        return
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(cache.serialize(), encoding="utf-8")


def find_account(
    accounts: list[dict[str, Any]],
    preferred_account: str | None,
) -> dict[str, Any] | None:
    """Retourne le premier compte qui matche `MS_GRAPH_ACCOUNT`, sinon le premier."""

    if not accounts:
        return None
    if preferred_account:
        preferred = preferred_account.lower().strip()
        for account in accounts:
            username = str(account.get("username", "")).lower()
            if preferred in username:
                return account
    return accounts[0]


def request_graph_access_token(config: GraphConfig) -> str:
    """Retourne un token d’accès en lecture seule, via cache puis code d’appareil."""

    cache = load_token_cache(MSAL_CACHE_FILE)
    authority = build_authority(config.tenant_id)
    public_client = msal.PublicClientApplication(
        client_id=config.client_id,
        authority=authority,
        token_cache=cache,
    )

    accounts = public_client.get_accounts()
    account = find_account(accounts, config.account)
    if account:
        token_result = public_client.acquire_token_silent(
            list(GRAPH_SCOPES),
            account=account,
        )
        if token_result and token_result.get("access_token"):
            save_token_cache(cache, MSAL_CACHE_FILE)
            return token_result["access_token"]

    flow = public_client.initiate_device_flow(scopes=list(GRAPH_SCOPES))
    if "user_code" not in flow or "message" not in flow:
        raise RuntimeError(
            "Le flux de code d’appareil n’a pas pu être démarré: "
            f"{flow.get('error_description', flow.get('error'))}"
        )

    print(flow["message"])
    print(f"Adresse de connexion: {flow.get('verification_uri', '')}")
    print(f"Code: {flow.get('user_code', '')}")
    print("En attente de la validation du code d’appareil...")

    token_result = public_client.acquire_token_by_device_flow(flow)
    if "access_token" not in token_result:
        raise_auth_error(token_result)
    save_token_cache(cache, MSAL_CACHE_FILE)
    return token_result["access_token"]


def raise_auth_error(token_result: Mapping[str, Any]) -> None:
    """Produit des messages d’erreur ciblés pour le consentement."""

    error = str(token_result.get("error", "")).lower()
    description = str(token_result.get("error_description", "")).lower()
    error_codes = token_result.get("error_codes", [])
    admin_block_codes = {65001, 65005}
    if isinstance(error_codes, Sequence) and any(
        isinstance(code, int) and code in admin_block_codes for code in error_codes
    ):
        raise RuntimeError(
            "Le consentement semble bloqué par un administrateur du locataire."
        )
    if error == "authorization_declined":
        raise RuntimeError("Le consentement a été refusé par l’utilisateur.")
    if error in {"access_denied", "unauthorized_client"} and "admin" in description:
        raise RuntimeError(
            "Le consentement est bloqué par un administrateur du locataire."
        )
    if error == "authorization_pending":
        raise RuntimeError("L’attente de validation est trop longue ou interrompue.")
    raise RuntimeError(
        "Erreur Microsoft Graph durant l’authentification: "
        f"{token_result.get('error', 'erreur inconnue')}"
    )


def request_graph_json(
    endpoint: str,
    token: str,
    *,
    params: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Appelle Microsoft Graph avec les entêtes de sécurité minimales."""

    response = requests.get(
        endpoint,
        headers={"Authorization": f"Bearer {token}"},
        params=params,
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def get_graph_profile(token: str) -> Mapping[str, Any]:
    """Récupère uniquement les champs demandés du profil."""

    return request_graph_json(f"{GRAPH_BASE_URL}/me", token)


def get_inbox_messages(token: str, *, top: int = 10) -> list[dict[str, Any]]:
    """Lit les messages les plus récents de la boîte de réception, en lecture seule."""

    payload = request_graph_json(
        f"{GRAPH_BASE_URL}/me/mailFolders/inbox/messages",
        token,
        params={
            "$top": top,
            "$orderby": "receivedDateTime desc",
            "$select": "subject,from,receivedDateTime,isRead",
        },
    )
    messages = payload.get("value", [])
    if isinstance(messages, list):
        return messages[:top]
    return []


def _parse_received_datetime(value: Any) -> str:
    if not value or not isinstance(value, str):
        return "Date inconnue"
    timestamp = value.strip()
    if timestamp.endswith("Z"):
        timestamp = timestamp[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(timestamp).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return timestamp


def _extract_sender(message: Mapping[str, Any]) -> str:
    from_value = message.get("from")
    if isinstance(from_value, Mapping):
        email_address = from_value.get("emailAddress")
        if isinstance(email_address, Mapping):
            name = str(email_address.get("name", "")).strip()
            address = str(email_address.get("address", "")).strip()
            if name and address:
                return f"{name} <{address}>"
            if address:
                return address
            if name:
                return name
    if isinstance(from_value, str):
        return from_value.strip()
    return "<expéditeur inconnu>"


def _is_chronogolf_notification_sender(sender: str) -> bool:
    return CHRONOGOLF_SENDER in sender.lower()


def format_message_line(message: Mapping[str, Any]) -> str:
    """Formate une ligne d’affichage pour un message Microsoft Graph."""

    received = _parse_received_datetime(message.get("receivedDateTime"))
    sender = _extract_sender(message)
    subject = str(message.get("subject", "(sans sujet)")).strip() or "(sans sujet)"
    is_read = "Lu" if message.get("isRead") is True else "Non lu"
    content = f"{received} | {sender} | {subject} | {is_read}"
    if _is_chronogolf_notification_sender(sender.lower()):
        return f"[CHRONOGOLF] {content}"
    return content


def format_messages(messages: Sequence[Mapping[str, Any]]) -> list[str]:
    """Formate une liste de messages au format affichage humain."""

    return [format_message_line(message) for message in messages]


def main() -> int:
    """Point d’entrée du script de test Microsoft Graph."""

    load_dotenv(ENV_FILE)

    try:
        config = load_graph_config()
    except GraphConfigError as exc:
        print(f"Configuration invalide: {exc}")
        return 1

    try:
        token = request_graph_access_token(config)
    except (RuntimeError, ValueError, OSError) as exc:
        print(f"Erreur d’authentification: {exc}")
        return 1

    try:
        profile = get_graph_profile(token)
        messages = get_inbox_messages(token)
    except requests.HTTPError as exc:
        print(f"Erreur d’appel Graph: {exc}")
        return 1

    print("Utilisateur Microsoft Graph :")
    print(f"  displayName: {profile.get('displayName')}")
    print(f"  userPrincipalName: {profile.get('userPrincipalName')}")
    print(f"  mail: {profile.get('mail')}")
    print()
    print("10 derniers messages (inbox):")
    print_messages = format_messages(messages)
    if not print_messages:
        print("  Aucun message trouvé.")
        return 0
    for index, line in enumerate(print_messages, start=1):
        print(f"{index:>2}. {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
