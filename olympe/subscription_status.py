"""Choix déterministe de la ligne d'abonnement qui représente un client (KAN-96).

Avant KAN-96, le cockpit OPS retenait ``subscriptions[0]`` d'une jointure PostgREST
non triée : le statut commercial affiché dépendait de l'ordre de retour de la base.

Règle écrite (CA1) : la ligne retenue est la plus récente par ``created_at`` ;
à égalité (ou date absente / illisible, classée la plus ancienne), on départage par
``updated_at`` puis par ``id`` (ordre lexicographique). Le résultat ne dépend donc
jamais de l'ordre d'entrée.

Ce module ne crée aucun statut commercial : il rend la *cause* du statut affiché
lisible (ligne retenue, date de création, contrepartie Stripe enregistrée) et signale
les contradictions entre statut du client, statut d'abonnement et état du conteneur.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# Statuts d'abonnement pour lesquels le récepteur d'événements Stripe suspend le
# conteneur (cf. OpsManager.process_stripe_event).
SUSPENDING_STATUSES = ("canceled", "unpaid", "past_due")
# Statuts d'abonnement qui traduisent un client réellement abonné.
LIVE_STATUSES = ("active", "trialing")
# Statuts du client (table tenants) qui annoncent un client vivant.
LIVE_TENANT_STATUSES = ("active", "trial")

_EPOCH = datetime.min.replace(tzinfo=timezone.utc)


def _parse_ts(value: Any) -> datetime:
    """Parse un horodatage ISO-8601 en UTC ; absent ou illisible → le plus ancien."""
    if not value or not isinstance(value, str):
        return _EPOCH
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return _EPOCH
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _sort_key(row: Dict[str, Any]) -> tuple:
    return (
        _parse_ts(row.get("created_at")),
        _parse_ts(row.get("updated_at")),
        str(row.get("id") or ""),
    )


def pick_representative_subscription(rows: Optional[List[Dict[str, Any]]]) -> Optional[Dict[str, Any]]:
    """Retourne la ligne d'abonnement la plus récente (règle ci-dessus), ou None."""
    candidates = [r for r in (rows or []) if isinstance(r, dict)]
    if not candidates:
        return None
    return max(candidates, key=_sort_key)


def build_subscription_origin(
    chosen: Dict[str, Any], rows: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """Décrit sur quelle ligne repose le statut affiché (CA3).

    ``stripe_counterpart`` indique seulement ce qui est *enregistré* en base :
    ``recorded`` = identifiants Stripe présents (existence côté Stripe non vérifiée
    ici), ``absent`` = aucun identifiant Stripe sur la ligne.
    """
    has_stripe = bool(chosen.get("stripe_customer_id") or chosen.get("stripe_subscription_id"))
    by_status: Dict[str, int] = {}
    for r in rows:
        key = str(r.get("status") or "").lower() or "inconnu"
        by_status[key] = by_status.get(key, 0) + 1
    return {
        "subscription_id": chosen.get("id"),
        "created_at": chosen.get("created_at"),
        "updated_at": chosen.get("updated_at"),
        "stripe_counterpart": "recorded" if has_stripe else "absent",
        "stripe_customer_id": chosen.get("stripe_customer_id"),
        "stripe_subscription_id": chosen.get("stripe_subscription_id"),
        "rows_total": len(rows),
        "rows_by_status": by_status,
        "selection_rule": "ligne la plus récente par created_at (puis updated_at, puis id)",
    }


def compute_divergences(
    tenant_status: Optional[str],
    sub_status: Optional[str],
    container_status: Optional[str],
    origin: Optional[Dict[str, Any]],
) -> List[Dict[str, str]]:
    """Liste les contradictions à afficher à côté du statut commercial (CA2 / CA5).

    Chaque entrée : ``{"code", "scope" ("status" | "container"), "message"}``.
    """
    t_status = (tenant_status or "").lower()
    s_status = (sub_status or "").lower()
    c_status = (container_status or "").lower()
    out: List[Dict[str, str]] = []

    sub_ref = ""
    no_stripe = False
    if origin:
        sub_ref = f" (ligne {origin.get('subscription_id')}, créée le {origin.get('created_at')})"
        no_stripe = origin.get("stripe_counterpart") == "absent"

    if s_status == "canceled" and t_status in LIVE_TENANT_STATUSES:
        out.append({
            "code": "tenant_vs_subscription",
            "scope": "status",
            "message": (
                f"Écart : le client est « {t_status} » en base mais l'abonnement retenu est annulé{sub_ref}."
                + (" Aucun identifiant Stripe sur cette ligne." if no_stripe else "")
            ),
        })
    elif s_status in LIVE_STATUSES and t_status == "churn":
        out.append({
            "code": "tenant_vs_subscription",
            "scope": "status",
            "message": f"Écart : le client est « churn » en base mais l'abonnement retenu est « {s_status} »{sub_ref}.",
        })

    container_running = c_status == "ready"
    container_sleeping = bool(c_status) and c_status not in ("ready", "not_provisioned")

    if container_running and (s_status == "canceled" or t_status == "churn"):
        out.append({
            "code": "container_running_while_canceled",
            "scope": "container",
            "message": "Écart : conteneur en ligne alors que le client est annoncé résilié.",
        })
    if container_sleeping and s_status in SUSPENDING_STATUSES and t_status in LIVE_TENANT_STATUSES:
        out.append({
            "code": "container_sleeping_after_cancellation",
            "scope": "container",
            "message": (
                f"Écart : client « {t_status} » dont le conteneur est en veille ; le statut d'abonnement "
                f"« {s_status} » déclenche la suspension du conteneur."
                + (" Cette annulation n'a aucun identifiant Stripe sur sa ligne." if no_stripe else "")
            ),
        })
    return out
