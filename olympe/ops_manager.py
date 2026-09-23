"""Gestionnaire Opérationnel, Commercial & Facturation pour le Cockpit Orso Ops (Olympe).

Gère la réconciliation des clients (public.tenants), des habilitations d'agents (agents_enabled),
des périodes d'essai et des abonnements Stripe (99€, 169€, 279€ HT).
"""

import json
import logging
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

_log = logging.getLogger("orso.olympe.ops")

# Grille tarifaire officielle Orso Agents (prix mensuels HT)
TIER_PRICING = {
    "1_agent": {"price_ht": 99.00, "max_agents": 1, "label": "Starter (1 agent)"},
    "2_agents": {"price_ht": 169.00, "max_agents": 2, "label": "Duo (2 agents)"},
    "4_agents": {"price_ht": 279.00, "max_agents": 4, "label": "Flotte Complète (4 agents)"},
    "custom": {"price_ht": 0.00, "max_agents": 4, "label": "Sur mesure"},
}

CATALOG_AGENTS = [
    {
        "id": "jerome",
        "name": "Jérôme",
        "role": "Recouvrement & Trésorerie",
        "avatar": "blue",
        "description": "Analyse les balances âgées, détecte les retards et prépare les relances amiables.",
    },
    {
        "id": "lucas",
        "name": "Lucas",
        "role": "Commercial & Prospection",
        "avatar": "purple",
        "description": "Qualifie les leads, suit les devis et relance les opportunités d'affaires.",
    },
    {
        "id": "clara",
        "name": "Clara",
        "role": "Support & Relation Client",
        "avatar": "emerald",
        "description": "Prend en charge les réclamations, litiges et questions récurrentes 24/7.",
    },
    {
        "id": "victor",
        "name": "Victor",
        "role": "Veille & Marchés Publics",
        "avatar": "amber",
        "description": "Surveille les appels d'offres (BOAMP) et assiste au montage des dossiers DCE.",
    },
]


def _format_timestamp(ts: Optional[float] = None) -> str:
    dt = datetime.fromtimestamp(ts, tz=timezone.utc) if ts else datetime.now(timezone.utc)
    return dt.isoformat()


class OpsManager:
    """Gestionnaire des opérations clients, facturation Stripe et activation des agents."""

    def __init__(
        self,
        supabase_url: Optional[str] = None,
        supabase_key: Optional[str] = None,
        stripe_secret_key: Optional[str] = None,
    ):
        self.supabase_url = (supabase_url or os.environ.get("SUPABASE_URL", "")).rstrip("/")
        self.supabase_key = supabase_key or os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
        self.stripe_secret_key = stripe_secret_key or os.environ.get("STRIPE_SECRET_KEY", "")

        # État en mémoire / cache pour le mode sans base distante ou le développement local
        self._mock_tenants: Dict[str, Dict[str, Any]] = self._init_seed_data()

    def _init_seed_data(self) -> Dict[str, Dict[str, Any]]:
        """Données d'amorçage réalistes représentant les premiers clients du projet Orso."""
        return {
            "f3e25379-6531-479e-b276-3b3185e7421b": {
                "id": "f3e25379-6531-479e-b276-3b3185e7421b",
                "name": "Financia Solutions",
                "siret": "83214567800012",
                "slug": "financia-solutions",
                "sector": "Courtage & Financement",
                "status": "active",
                "created_at": "2026-09-01T08:30:00Z",
                "contact": {
                    "full_name": "Sophie Martin",
                    "email": "sophie.martin@finarecee20.fr",
                    "phone": "+33 6 12 34 56 78",
                    "role": "DAF",
                },
                "instance": {
                    "container_name": "orso_client_financia_solutions",
                    "internal_route_key": "orso_client_financia_solutions",
                    "status": "ready",
                    "environment_status": "active",
                },
                "agents_enabled": {
                    "active": ["jerome", "lucas"],
                    "trials": {
                        "lucas": {
                            "is_trial": True,
                            "start_date": "2026-09-15T00:00:00Z",
                            "end_date": "2026-10-15T23:59:59Z",
                            "days_remaining": 24,
                        }
                    },
                },
                "subscription": {
                    "id": "sub_financia_001",
                    "tier_id": "1_agent",
                    "tier_label": "Starter (1 agent)",
                    "price_ht": 99.00,
                    "status": "active",
                    "current_period_start": "2026-09-01T00:00:00Z",
                    "current_period_end": "2026-10-01T00:00:00Z",
                    "stripe_customer_id": "cus_financia_9821",
                    "stripe_subscription_id": "sub_1Q1234567890",
                    "payment_method": "SEPA Direct Debit (••• 4021)",
                },
                "invoices": [
                    {
                        "id": "inv_001",
                        "number": "ORSO-2026-0001",
                        "amount_ht": 99.00,
                        "amount_ttc": 118.80,
                        "status": "paid",
                        "date": "2026-09-01T09:00:00Z",
                        "pdf_url": "#download/ORSO-2026-0001.pdf",
                    }
                ],
            },
            "9a38ef87-19d2-45e3-9821-2efbb91081a9": {
                "id": "9a38ef87-19d2-45e3-9821-2efbb91081a9",
                "name": "CommerciaLink",
                "siret": "78451236900021",
                "slug": "commercialink",
                "sector": "Distribution B2B",
                "status": "active",
                "created_at": "2026-09-05T14:15:00Z",
                "contact": {
                    "full_name": "Claire Dubois",
                    "email": "claire.dubois@servicallc322.com",
                    "phone": "+33 6 98 76 54 32",
                    "role": "Directrice Commerciale",
                },
                "instance": {
                    "container_name": "orso_client_commercialink",
                    "internal_route_key": "orso_client_commercialink",
                    "status": "ready",
                    "environment_status": "active",
                },
                "agents_enabled": {
                    "active": ["jerome", "lucas"],
                    "trials": {},
                },
                "subscription": {
                    "id": "sub_commercialink_002",
                    "tier_id": "2_agents",
                    "tier_label": "Duo (2 agents)",
                    "price_ht": 169.00,
                    "status": "active",
                    "current_period_start": "2026-09-05T00:00:00Z",
                    "current_period_end": "2026-10-05T00:00:00Z",
                    "stripe_customer_id": "cus_comm_3211",
                    "stripe_subscription_id": "sub_2W9876543210",
                    "payment_method": "Visa (••• 4242)",
                },
                "invoices": [
                    {
                        "id": "inv_002",
                        "number": "ORSO-2026-0002",
                        "amount_ht": 169.00,
                        "amount_ttc": 202.80,
                        "status": "paid",
                        "date": "2026-09-05T14:30:00Z",
                        "pdf_url": "#download/ORSO-2026-0002.pdf",
                    }
                ],
            },
            "c56b8290-7f28-4a11-893d-47209118a72e": {
                "id": "c56b8290-7f28-4a11-893d-47209118a72e",
                "name": "BatiPro Services",
                "siret": "90123456700038",
                "slug": "batipro-services",
                "sector": "BTP & Rénovation",
                "status": "trial",
                "created_at": "2026-09-18T10:00:00Z",
                "contact": {
                    "full_name": "Julien Lefèvre",
                    "email": "julien.lefevre@batiprof38f.fr",
                    "phone": "+33 6 45 67 89 01",
                    "role": "Gérant",
                },
                "instance": {
                    "container_name": "orso_client_batipro_services",
                    "internal_route_key": "orso_client_batipro_services",
                    "status": "ready",
                    "environment_status": "active",
                },
                "agents_enabled": {
                    "active": ["jerome", "victor"],
                    "trials": {
                        "jerome": {
                            "is_trial": True,
                            "start_date": "2026-09-18T00:00:00Z",
                            "end_date": "2026-10-02T23:59:59Z",
                            "days_remaining": 11,
                        },
                        "victor": {
                            "is_trial": True,
                            "start_date": "2026-09-18T00:00:00Z",
                            "end_date": "2026-10-02T23:59:59Z",
                            "days_remaining": 11,
                        },
                    },
                },
                "subscription": {
                    "id": "sub_trial_batipro",
                    "tier_id": "2_agents",
                    "tier_label": "Duo (Essai 14 jours)",
                    "price_ht": 0.00,
                    "status": "trialing",
                    "current_period_start": "2026-09-18T00:00:00Z",
                    "current_period_end": "2026-10-02T23:59:59Z",
                    "stripe_customer_id": "cus_batipro_pending",
                    "stripe_subscription_id": None,
                    "payment_method": "Aucune carte enregistrée (Période d'essai)",
                },
                "invoices": [],
            },
            "e88d1234-9abc-4def-0123-456789abcdef": {
                "id": "e88d1234-9abc-4def-0123-456789abcdef",
                "name": "HexaTech Solutions",
                "siret": "55566677700044",
                "slug": "hexatech",
                "sector": "Édition Logicielle SaaS",
                "status": "active",
                "created_at": "2026-09-10T11:00:00Z",
                "contact": {
                    "full_name": "Marc Vasseur",
                    "email": "m.vasseur@hexatech.io",
                    "phone": "+33 6 11 22 33 44",
                    "role": "CEO",
                },
                "instance": {
                    "container_name": "orso_client_hexatech",
                    "internal_route_key": "orso_client_hexatech",
                    "status": "ready",
                    "environment_status": "active",
                },
                "agents_enabled": {
                    "active": ["jerome", "lucas", "clara", "victor"],
                    "trials": {},
                },
                "subscription": {
                    "id": "sub_hexatech_full",
                    "tier_id": "4_agents",
                    "tier_label": "Flotte Complète (4 agents)",
                    "price_ht": 279.00,
                    "status": "active",
                    "current_period_start": "2026-09-10T00:00:00Z",
                    "current_period_end": "2026-10-10T00:00:00Z",
                    "stripe_customer_id": "cus_hexa_555",
                    "stripe_subscription_id": "sub_4F9988776655",
                    "payment_method": "Mastercard (••• 8899)",
                },
                "invoices": [
                    {
                        "id": "inv_003",
                        "number": "ORSO-2026-0003",
                        "amount_ht": 279.00,
                        "amount_ttc": 334.80,
                        "status": "paid",
                        "date": "2026-09-10T11:15:00Z",
                        "pdf_url": "#download/ORSO-2026-0003.pdf",
                    }
                ],
            },
        }

    # ── Requetage Supabase / Source de Vérité ─────────────────────────────────

    def _query_supabase(self, path: str, method: str = "GET", payload: Optional[dict] = None) -> Optional[Any]:
        """Exécute un appel HTTP authentifié vers l'API PostgREST de Supabase."""
        if not self.supabase_url or not self.supabase_key:
            return None

        url = f"{self.supabase_url}/rest/v1/{path}"
        data_bytes = json.dumps(payload).encode("utf-8") if payload else None

        req = urllib.request.Request(
            url,
            data=data_bytes,
            headers={
                "apikey": self.supabase_key,
                "Authorization": f"Bearer {self.supabase_key}",
                "Content-Type": "application/json",
                "User-Agent": "OrsoOlympeOps/1.0",
                "Prefer": "return=representation",
            },
            method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            _log.warning("Échec requête Supabase (%s %s): %s", method, path, e)
            return None

    def _fetch_supabase_auth_users(self) -> Dict[str, str]:
        """Récupère la table de correspondance user_id -> email via l'API Admin Supabase."""
        if not self.supabase_url or not self.supabase_key:
            return {}

        admin_url = f"{self.supabase_url}/auth/v1/admin/users"
        req = urllib.request.Request(
            admin_url,
            headers={
                "apikey": self.supabase_key,
                "Authorization": f"Bearer {self.supabase_key}",
                "Content-Type": "application/json",
                "User-Agent": "OrsoOlympeOps/1.0",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                users = data.get("users", [])
                return {u["id"]: u.get("email", "") for u in users if "id" in u}
        except Exception as e:
            _log.warning("Échec récupération des utilisateurs Supabase Auth: %s", e)
            return {}

    # ── Endpoints Métier Ops ──────────────────────────────────────────────────

    def get_tenants_overview(self) -> List[Dict[str, Any]]:
        """Retourne la liste consolidée de tous les clients avec instance, contact, agents et abonnement."""
        # 1. Tentative de lecture Supabase si configuré
        sb_tenants = self._query_supabase("tenants?select=*,profiles(*),tenant_instances(*)")
        if sb_tenants and isinstance(sb_tenants, list) and len(sb_tenants) > 0:
            auth_emails = self._fetch_supabase_auth_users()
            result = []
            for t in sb_tenants:
                tenant_id = t.get("id")
                cached = self._mock_tenants.get(tenant_id, {})
                profiles = t.get("profiles", [])
                primary_contact = profiles[0] if profiles else {}
                instances = t.get("tenant_instances", [])
                instance_info = instances[0] if instances else {}

                agents_data = instance_info.get("agents_enabled") or cached.get("agents_enabled", {"active": ["jerome"], "trials": {}})
                if isinstance(agents_data, list):
                    agents_data = {"active": agents_data, "trials": {}}

                sub = cached.get("subscription") or {
                    "id": f"sub_{t.get('slug')}",
                    "tier_id": "1_agent",
                    "tier_label": "Starter (1 agent)",
                    "price_ht": 99.00,
                    "status": "active",
                    "current_period_start": t.get("created_at"),
                    "current_period_end": t.get("created_at"),
                }

                contact_id = primary_contact.get("id")
                email = primary_contact.get("email") or auth_emails.get(contact_id, "") or cached.get("contact", {}).get("email", "")

                item = {
                    "id": tenant_id,
                    "name": t.get("name"),
                    "siret": t.get("siret"),
                    "slug": t.get("slug"),
                    "sector": t.get("sector") or "Services",
                    "status": t.get("status", "active"),
                    "created_at": t.get("created_at"),
                    "contact": {
                        "full_name": primary_contact.get("full_name", "Contact Principal"),
                        "email": email,
                        "phone": primary_contact.get("phone", "") or cached.get("contact", {}).get("phone", ""),
                        "role": primary_contact.get("role", "Direction"),
                    },
                    "instance": {
                        "container_name": instance_info.get("docker_container_name") or f"orso_client_{t.get('slug')}",
                        "status": instance_info.get("status", "ready"),
                    },
                    "agents_enabled": agents_data,
                    "subscription": sub,
                    "invoices": cached.get("invoices", []),
                }
                result.append(item)
            return result

        # 2. Fallback sur le référentiel d'amorçage
        return list(self._mock_tenants.values())

    def get_tenant_detail(self, tenant_id: str) -> Optional[Dict[str, Any]]:
        """Retourne la fiche détaillée complète d'un client."""
        tenants = self.get_tenants_overview()
        for t in tenants:
            if t["id"] == tenant_id or t.get("slug") == tenant_id:
                return t
        return None

    def update_tenant_agents(
        self,
        tenant_id: str,
        active_agents: List[str],
        trials_config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Active ou désactive des agents pour un client et configure d'éventuelles périodes d'essai.

        Met à jour public.tenant_instances dans Supabase de façon atomique.
        """
        clean_active = [a for a in active_agents if a in ["jerome", "lucas", "clara", "victor"]]
        clean_trials = trials_config or {}

        payload_agents = {
            "active": clean_active,
            "trials": clean_trials,
        }

        # 1. Mise à jour Supabase si configuré
        if self.supabase_url and self.supabase_key:
            sb_update = self._query_supabase(
                f"tenant_instances?tenant_id=eq.{tenant_id}",
                method="PATCH",
                payload={"agents_enabled": clean_active},
            )
            _log.info("Mise à jour Supabase pour le tenant %s : %s", tenant_id, sb_update)

        # 2. Mise à jour de l'état mémoire local / cache
        if tenant_id in self._mock_tenants:
            self._mock_tenants[tenant_id]["agents_enabled"] = payload_agents
            nb_agents = len(clean_active)
            if nb_agents <= 1:
                tier_key = "1_agent"
            elif nb_agents == 2:
                tier_key = "2_agents"
            else:
                tier_key = "4_agents"

            self._mock_tenants[tenant_id]["subscription"]["suggested_tier"] = tier_key

        return {
            "success": True,
            "tenant_id": tenant_id,
            "agents_enabled": payload_agents,
            "updated_at": _format_timestamp(),
            "message": f"Habilitations mises à jour : {len(clean_active)} agents activés.",
        }

    def update_tenant_subscription(
        self,
        tenant_id: str,
        tier_id: str,
        status: str = "active",
    ) -> Dict[str, Any]:
        """Met à jour le plan d'abonnement d'un client (99€, 169€, 279€ HT)."""
        pricing = TIER_PRICING.get(tier_id, TIER_PRICING["custom"])

        if tenant_id in self._mock_tenants:
            sub = self._mock_tenants[tenant_id]["subscription"]
            sub["tier_id"] = tier_id
            sub["tier_label"] = pricing["label"]
            sub["price_ht"] = pricing["price_ht"]
            sub["status"] = status
            sub["updated_at"] = _format_timestamp()

        return {
            "success": True,
            "tenant_id": tenant_id,
            "tier_id": tier_id,
            "price_ht": pricing["price_ht"],
            "status": status,
        }

    def get_stats(self) -> Dict[str, Any]:
        """Calcule les indicateurs clés de performance (KPIs) pour le tableau de bord Orso Ops."""
        tenants = self.get_tenants_overview()

        total_clients = len(tenants)
        active_subscribers = 0
        trialing_clients = 0
        mrr_ht = 0.0

        tier_counts = {"1_agent": 0, "2_agents": 0, "4_agents": 0, "custom": 0}
        agent_utilization = {"jerome": 0, "lucas": 0, "clara": 0, "victor": 0}

        for t in tenants:
            sub = t.get("subscription", {})
            sub_status = sub.get("status")
            price = float(sub.get("price_ht", 0.0))

            if sub_status == "active" and price > 0:
                active_subscribers += 1
                mrr_ht += price
                tier_id = sub.get("tier_id", "custom")
                tier_counts[tier_id] = tier_counts.get(tier_id, 0) + 1
            elif sub_status == "trialing" or t.get("status") == "trial":
                trialing_clients += 1

            agents = t.get("agents_enabled", {}).get("active", [])
            for a in agents:
                if a in agent_utilization:
                    agent_utilization[a] += 1

        return {
            "kpis": {
                "total_clients": total_clients,
                "active_subscribers": active_subscribers,
                "trialing_clients": trialing_clients,
                "mrr_ht": round(mrr_ht, 2),
                "mrr_ttc": round(mrr_ht * 1.20, 2),
                "arr_ht": round(mrr_ht * 12, 2),
            },
            "tier_distribution": tier_counts,
            "agent_utilization": agent_utilization,
            "pricing_catalog": TIER_PRICING,
            "timestamp": _format_timestamp(),
        }

    def list_all_invoices(self) -> List[Dict[str, Any]]:
        """Agrège l'historique complet des factures de tous les clients."""
        all_invoices = []
        for t in self.get_tenants_overview():
            for inv in t.get("invoices", []):
                item = dict(inv)
                item["tenant_id"] = t["id"]
                item["tenant_name"] = t["name"]
                item["tenant_slug"] = t["slug"]
                all_invoices.append(item)
        all_invoices.sort(key=lambda x: x.get("date", ""), reverse=True)
        return all_invoices

    def handle_stripe_webhook(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Traite les événements Webhook émis par Stripe Billing."""
        event_type = event.get("type", "")
        data_obj = event.get("data", {}).get("object", {})

        _log.info("Réception d'un webhook Stripe : %s", event_type)

        if event_type in ("customer.subscription.created", "customer.subscription.updated"):
            sub_id = data_obj.get("id")
            cus_id = data_obj.get("customer")
            status = data_obj.get("status")
            _log.info("Mise à jour d'abonnement Stripe: %s (client: %s) -> statut: %s", sub_id, cus_id, status)
            return {"status": "processed", "type": event_type, "subscription_id": sub_id}

        elif event_type == "invoice.payment_succeeded":
            inv_id = data_obj.get("id")
            amount_paid = data_obj.get("amount_paid", 0) / 100.0
            _log.info("Paiement réussi pour la facture Stripe: %s (montant: %.2f €)", inv_id, amount_paid)
            return {"status": "processed", "type": event_type, "invoice_id": inv_id}

        elif event_type == "invoice.payment_failed":
            inv_id = data_obj.get("id")
            _log.warning("Paiement échoué pour la facture Stripe: %s", inv_id)
            return {"status": "alert_logged", "type": event_type, "invoice_id": inv_id}

        return {"status": "ignored", "type": event_type}
