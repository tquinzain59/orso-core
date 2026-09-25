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
    "none": {"price_ht": 0.00, "max_agents": 0, "label": "Aucun abonnement"},
    "1_agent": {"price_ht": 0.00, "max_agents": 1, "label": "Starter (1 agent)"},
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

        # Cache mémoire TTL pour la table de correspondance auth.users (évite les requêtes Supabase répétitives)
        self._cached_auth_emails: Optional[tuple[float, Dict[str, str]]] = None
        self._auth_emails_ttl: float = 60.0  # 60 secondes

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
                "users": [
                    {
                        "id": "usr_financia_001",
                        "email": "sophie.martin@finarecee20.fr",
                        "full_name": "Sophie Martin",
                        "role": "DAF",
                        "is_admin": True,
                        "is_primary_contact": True,
                        "created_at": "2026-09-01T08:30:00Z",
                    },
                    {
                        "id": "usr_financia_002",
                        "email": "lucas.compta@finarecee20.fr",
                        "full_name": "Lucas Bernard",
                        "role": "Comptable",
                        "is_admin": False,
                        "is_primary_contact": False,
                        "created_at": "2026-09-10T09:15:00Z",
                    },
                ],
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
                "status": "none",
                "created_at": "2026-09-05T14:15:00Z",
                "contact": {
                    "full_name": "Claire Dubois",
                    "email": "claire.dubois@servicallc322.com",
                    "phone": "+33 6 98 76 54 32",
                    "role": "Directrice Commerciale",
                },
                "users": [
                    {
                        "id": "usr_comm_001",
                        "email": "claire.dubois@servicallc322.com",
                        "full_name": "Claire Dubois",
                        "role": "Directrice Commerciale",
                        "is_admin": True,
                        "is_primary_contact": True,
                        "created_at": "2026-09-05T14:15:00Z",
                    },
                    {
                        "id": "usr_comm_002",
                        "email": "thomas.vente@servicallc322.com",
                        "full_name": "Thomas Petit",
                        "role": "Commercial B2B",
                        "is_admin": False,
                        "is_primary_contact": False,
                        "created_at": "2026-09-12T11:00:00Z",
                    },
                ],
                "instance": {
                    "container_name": None,
                    "internal_route_key": None,
                    "status": "not_provisioned",
                    "environment_status": "inactive",
                },
                "agents_enabled": {
                    "active": [],
                    "trials": {},
                },
                "subscription": {
                    "id": "sub_commercialink_002",
                    "tier_id": "none",
                    "tier_label": "Aucun abonnement",
                    "price_ht": 0.00,
                    "status": "none",
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
                "users": [
                    {
                        "id": "usr_bati_001",
                        "email": "julien.lefevre@batiprof38f.fr",
                        "full_name": "Julien Lefèvre",
                        "role": "Gérant",
                        "is_admin": True,
                        "is_primary_contact": True,
                        "created_at": "2026-09-18T10:00:00Z",
                    },
                    {
                        "id": "usr_bati_002",
                        "email": "chantal.admin@batiprof38f.fr",
                        "full_name": "Chantal Durand",
                        "role": "Assistante de Direction",
                        "is_admin": False,
                        "is_primary_contact": False,
                        "created_at": "2026-09-20T14:30:00Z",
                    },
                ],
                "instance": {
                    "container_name": None,
                    "internal_route_key": None,
                    "status": "not_provisioned",
                    "environment_status": "inactive",
                },
                "agents_enabled": {
                    "active": [],
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
                    "tier_id": "none",
                    "tier_label": "Aucun abonnement",
                    "price_ht": 0.00,
                    "status": "none",
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
                "status": "none",
                "created_at": "2026-09-10T11:00:00Z",
                "contact": {
                    "full_name": "Marc Vasseur",
                    "email": "m.vasseur@hexatech.io",
                    "phone": "+33 6 11 22 33 44",
                    "role": "CEO",
                },
                "users": [
                    {
                        "id": "usr_hexa_001",
                        "email": "m.vasseur@hexatech.io",
                        "full_name": "Marc Vasseur",
                        "role": "CEO",
                        "is_admin": True,
                        "is_primary_contact": True,
                        "created_at": "2026-09-10T11:00:00Z",
                    },
                    {
                        "id": "usr_hexa_002",
                        "email": "sarah.cto@hexatech.io",
                        "full_name": "Sarah Bensaid",
                        "role": "CTO",
                        "is_admin": True,
                        "is_primary_contact": False,
                        "created_at": "2026-09-11T10:00:00Z",
                    },
                    {
                        "id": "usr_hexa_003",
                        "email": "hugo.support@hexatech.io",
                        "full_name": "Hugo Moreau",
                        "role": "Support Client",
                        "is_admin": False,
                        "is_primary_contact": False,
                        "created_at": "2026-09-15T16:20:00Z",
                    },
                ],
                "instance": {
                    "container_name": None,
                    "internal_route_key": None,
                    "status": "not_provisioned",
                    "environment_status": "inactive",
                },
                "agents_enabled": {
                    "active": [],
                    "trials": {},
                },
                "subscription": {
                    "id": "sub_hexatech_full",
                    "tier_id": "none",
                    "tier_label": "Aucun abonnement",
                    "price_ht": 0.00,
                    "status": "none",
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
        """Récupère la table de correspondance user_id -> email via l'API Admin Supabase (avec cache TTL 60s)."""
        now = time.time()
        if self._cached_auth_emails and (now - self._cached_auth_emails[0] < self._auth_emails_ttl):
            return self._cached_auth_emails[1]

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
                mapping = {u["id"]: u.get("email", "") for u in users if "id" in u}
                self._cached_auth_emails = (now, mapping)
                return mapping
        except Exception as e:
            _log.warning("Échec récupération des utilisateurs Supabase Auth: %s", e)
            if self._cached_auth_emails:
                return self._cached_auth_emails[1]
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
                user_list = []
                for p in profiles:
                    p_id = p.get("id")
                    p_email = p.get("email") or auth_emails.get(p_id, "")
                    user_list.append({
                        "id": p_id,
                        "email": p_email,
                        "full_name": p.get("full_name") or "Utilisateur",
                        "phone": p.get("phone", ""),
                        "role": p.get("role") or "Membre",
                        "is_admin": bool(p.get("is_admin", False) or p.get("role") == "admin"),
                        "is_primary_contact": bool(p.get("is_primary_contact", False)),
                        "created_at": p.get("created_at") or t.get("created_at"),
                    })
                if not user_list and cached.get("users"):
                    user_list = list(cached.get("users", []))

                primary_contact = next((u for u in user_list if u.get("is_primary_contact")), user_list[0] if user_list else {})
                instances = t.get("tenant_instances", [])
                instance_info = instances[0] if instances else {}

                agents_data = instance_info.get("agents_enabled") or cached.get("agents_enabled", {"active": [], "trials": {}})
                if isinstance(agents_data, list):
                    agents_data = {"active": agents_data, "trials": {}}

                sub = cached.get("subscription") or {
                    "id": f"sub_{t.get('slug')}",
                    "tier_id": "none",
                    "tier_label": "Aucun abonnement",
                    "price_ht": 0.00,
                    "status": "none",
                    "current_period_start": t.get("created_at"),
                    "current_period_end": t.get("created_at"),
                }

                contact_email = primary_contact.get("email") or cached.get("contact", {}).get("email", "")

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
                        "email": contact_email,
                        "phone": primary_contact.get("phone", "") or cached.get("contact", {}).get("phone", ""),
                        "role": primary_contact.get("role", "Direction"),
                    },
                    "users": user_list,
                    "instance": {
                        "container_name": instance_info.get("docker_container_name") or f"orso_client_{t.get('slug')}",
                        "status": instance_info.get("status", "not_provisioned"),
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

    def get_tenant_users(self, tenant_id: str) -> List[Dict[str, Any]]:
        """Retourne la liste complète des utilisateurs rattachés à un client."""
        detail = self.get_tenant_detail(tenant_id)
        if detail and "users" in detail:
            return detail["users"]
        return []

    def create_tenant_user(
        self,
        tenant_id: str,
        email: str,
        password: Optional[str] = None,
        full_name: str = "",
        role: str = "Membre",
        is_admin: bool = False,
    ) -> Dict[str, Any]:
        """Crée un nouvel utilisateur pour une organisation cliente.

        Enregistre dans Supabase Auth (auth.users) et public.profiles si configuré,
        ou dans le référentiel mémoire mock.
        """
        tenant_detail = self.get_tenant_detail(tenant_id)
        if not tenant_detail:
            raise ValueError(f"Organisation cliente {tenant_id} introuvable.")

        actual_tenant_id = tenant_detail["id"]
        tenant_slug = tenant_detail.get("slug", "")

        user_password = password or f"Orso{int(time.time())}!"

        # 1. Mode Supabase si configuré
        if self.supabase_url and self.supabase_key:
            admin_url = f"{self.supabase_url}/auth/v1/admin/users"
            payload = {
                "email": email,
                "password": user_password,
                "email_confirm": True,
                "user_metadata": {
                    "full_name": full_name,
                    "role": role,
                },
                "app_metadata": {
                    "tenant_id": actual_tenant_id,
                    "tenant_slug": tenant_slug,
                    "role": role,
                    "is_admin": is_admin,
                },
            }
            res_user = None
            try:
                req = urllib.request.Request(
                    admin_url,
                    data=json.dumps(payload).encode("utf-8"),
                    headers={
                        "apikey": self.supabase_key,
                        "Authorization": f"Bearer {self.supabase_key}",
                        "Content-Type": "application/json",
                        "User-Agent": "OrsoOlympeOps/1.0",
                    },
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=5.0) as resp:
                    res_user = json.loads(resp.read().decode("utf-8"))
            except Exception as e:
                _log.error("Échec création utilisateur Supabase Auth: %s", e)
                raise ValueError(f"Impossible de créer l'utilisateur Supabase Auth : {e}")

            user_id = res_user.get("id") if res_user else None
            if not user_id:
                raise ValueError("Identifiant utilisateur Supabase non renvoyé.")

            # Insertion dans public.profiles
            profile_payload = {
                "id": user_id,
                "tenant_id": actual_tenant_id,
                "full_name": full_name,
                "role": role,
                "is_admin": is_admin,
                "is_primary_contact": False,
            }
            self._query_supabase("profiles", method="POST", payload=profile_payload)
            self._cached_auth_emails = None

            created_user = {
                "id": user_id,
                "email": email,
                "full_name": full_name,
                "role": role,
                "is_admin": is_admin,
                "is_primary_contact": False,
                "created_at": _format_timestamp(),
            }
            if actual_tenant_id in self._mock_tenants:
                self._mock_tenants[actual_tenant_id].setdefault("users", []).append(created_user)
            return created_user

        # 2. Mode Mock Local
        user_id = f"usr_{int(time.time())}_{len(self._mock_tenants)}"
        created_user = {
            "id": user_id,
            "email": email,
            "full_name": full_name,
            "role": role,
            "is_admin": is_admin,
            "is_primary_contact": False,
            "created_at": _format_timestamp(),
        }
        if actual_tenant_id in self._mock_tenants:
            self._mock_tenants[actual_tenant_id].setdefault("users", []).append(created_user)

        return created_user

    def delete_tenant_user(self, tenant_id: str, user_id: str) -> bool:
        """Supprime un utilisateur pour une organisation cliente."""
        tenant_detail = self.get_tenant_detail(tenant_id)
        if not tenant_detail:
            return False
        actual_tenant_id = tenant_detail["id"]

        if self.supabase_url and self.supabase_key:
            try:
                self._query_supabase(f"profiles?id=eq.{user_id}", method="DELETE")
                del_url = f"{self.supabase_url}/auth/v1/admin/users/{user_id}"
                req = urllib.request.Request(
                    del_url,
                    headers={
                        "apikey": self.supabase_key,
                        "Authorization": f"Bearer {self.supabase_key}",
                        "User-Agent": "OrsoOlympeOps/1.0",
                    },
                    method="DELETE",
                )
                with urllib.request.urlopen(req, timeout=5.0):
                    pass
                self._cached_auth_emails = None
            except Exception as e:
                _log.warning("Erreur suppression utilisateur Supabase: %s", e)

        if actual_tenant_id in self._mock_tenants:
            users = self._mock_tenants[actual_tenant_id].get("users", [])
            self._mock_tenants[actual_tenant_id]["users"] = [u for u in users if u["id"] != user_id]
            return True

        return True

    def update_tenant_agents(
        self,
        tenant_id: str,
        active_agents: List[str],
        trials_config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Active ou désactive des agents pour un client et configure d'éventuelles périodes d'essai.

        Met à jour public.tenant_instances dans Supabase de façon atomique.
        """
        # VERROU 1 & 2 : Validation d'abonnement et de quota
        tenant = self.get_tenant_detail(tenant_id)
        if not tenant:
            raise ValueError("Client introuvable.")
        
        sub = tenant.get("subscription", {})
        sub_status = sub.get("status", "none")
        tier_id = sub.get("tier_id", "none")
        
        if sub_status not in ["active", "trialing"] and len(active_agents) > 0:
            raise ValueError("Impossible d'activer des agents sans abonnement actif.")
            
        pricing = TIER_PRICING.get(tier_id, TIER_PRICING["custom"])
        max_agents = pricing.get("max_agents", 0)
        
        if len(active_agents) > max_agents and tier_id != "custom":
            raise ValueError(f"Quota dépassé : le forfait {pricing.get('label')} n'autorise que {max_agents} agent(s).")
            
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
            
            # VERROU 3 : Purge des agents et instance en cas de résiliation / downgrade
            max_agents = pricing.get("max_agents", 0)
            current_agents = self._mock_tenants[tenant_id].get("agents_enabled", {}).get("active", [])
            
            if status in ["none", "inactive", "canceled"] or tier_id == "none":
                self._mock_tenants[tenant_id]["agents_enabled"]["active"] = []
                self._mock_tenants[tenant_id]["instance"]["status"] = "not_provisioned"
                self._mock_tenants[tenant_id]["instance"]["environment_status"] = "inactive"
                if self.supabase_url and self.supabase_key:
                    self._query_supabase(f"tenant_instances?tenant_id=eq.{tenant_id}", method="PATCH", payload={"agents_enabled": [], "status": "not_provisioned", "environment_status": "inactive"})
            elif len(current_agents) > max_agents and tier_id != "custom":
                # Downgrade: troncature automatique
                new_agents = current_agents[:max_agents]
                self._mock_tenants[tenant_id]["agents_enabled"]["active"] = new_agents
                if self.supabase_url and self.supabase_key:
                    self._query_supabase(f"tenant_instances?tenant_id=eq.{tenant_id}", method="PATCH", payload={"agents_enabled": new_agents})


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
