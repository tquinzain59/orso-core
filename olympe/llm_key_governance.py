"""Gouvernance des clés d'API LLM par tenant (KAN-53).

Ce module vit côté plan de gestion (Olympe), jamais dans le moteur : il ne touche
aucun fichier du Sanctuaire. Il fournit, sur une base SQLite unique :

* un **inventaire** des clés (fournisseur, tenant, emplacement, dernière rotation,
  responsable) — jamais la valeur, seulement une empreinte salée pour la vérification ;
* un **plafond de dépense** par tenant et par mois civil UTC, avec refus ou alerte seule ;
* des **alertes** de seuil et de dérive, dédupliquées, persistées et horodatées ;
* un **journal d'audit** des appels (tenant, fournisseur, modèle, coût, horodatage) ;
* une **rotation à chaud** avec fenêtre de grâce et journal de rotation, après laquelle
  l'ancienne valeur est refusée par :meth:`LLMGovernance.verify_key`.

Les coûts enregistrés doivent provenir d'une source de vérité (compteur interne du
point de passage des appels ou journal du fournisseur), jamais d'un écran applicatif.
Ce module n'intercepte aucun appel par lui-même : le point d'application (proxy ou
passerelle) appelle :meth:`authorize` avant l'appel et :meth:`record_call` après.
"""

from __future__ import annotations

import csv
import hashlib
import hmac
import io
import json
import logging
import os
import re
import secrets
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

_log = logging.getLogger("orso.olympe.llm_key_governance")

DEFAULT_THRESHOLDS = (0.5, 0.8, 1.0)
DEFAULT_DRIFT_FACTOR = 3.0
DRIFT_BASELINE_DAYS = 7
DRIFT_MIN_TODAY_USD = 1.0
DEFAULT_GRACE_SECONDS = 900
MODE_REFUSE = "refuse"
MODE_ALERT_ONLY = "alert_only"
DEFAULT_POLICY_TENANT = "*"
SHARED_KEY_TENANT = "*"

_ACTOR_RE = re.compile(r"^[a-z0-9][a-z0-9_.:-]{2,63}$")
_SECRET_LIKE_RE = re.compile(
    r"(?:\b(?:sk|pk|rk)-[A-Za-z0-9_\-]{16,}|\bAIza[0-9A-Za-z_\-]{20,}|[A-Za-z0-9_\-]{32,})"
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS llm_keys (
    key_id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    tenant_slug TEXT NOT NULL,
    location TEXT NOT NULL,
    owner TEXT NOT NULL,
    last_rotation TEXT,
    salt TEXT,
    digest TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS llm_retired_keys (
    retired_id INTEGER PRIMARY KEY AUTOINCREMENT,
    key_id TEXT NOT NULL,
    salt TEXT NOT NULL,
    digest TEXT NOT NULL,
    retired_at TEXT NOT NULL,
    grace_until TEXT NOT NULL,
    revoked_at TEXT
);
CREATE TABLE IF NOT EXISTS llm_policies (
    tenant_slug TEXT PRIMARY KEY,
    monthly_cap_usd REAL,
    mode TEXT NOT NULL,
    thresholds TEXT NOT NULL,
    drift_factor REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS llm_calls (
    call_id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    tenant_slug TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    cost_usd REAL NOT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    key_id TEXT,
    session_id TEXT,
    decision TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_llm_calls_tenant_ts ON llm_calls(tenant_slug, ts);
CREATE TABLE IF NOT EXISTS llm_alerts (
    alert_id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    kind TEXT NOT NULL,
    tenant_slug TEXT NOT NULL,
    dedupe_key TEXT NOT NULL UNIQUE,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS llm_rotation_log (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    key_id TEXT NOT NULL,
    event TEXT NOT NULL,
    actor TEXT NOT NULL,
    detail TEXT NOT NULL
);
"""


class GovernanceError(ValueError):
    """Entrée invalide (valeur secrète en clair, acteur humain, clé inconnue...)."""


def default_db_path() -> Path:
    """Base du plan de gestion, à côté de ``olympe_ops.db`` (hors dépôt)."""
    return Path(os.environ.get("ORSO_LLM_GOVERNANCE_DB", "./data/llm_governance.db"))


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def _period_of(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m")


def _looks_like_secret(text: str) -> bool:
    for match in _SECRET_LIKE_RE.finditer(text):
        token = match.group(0)
        if token.startswith(("sk-", "pk-", "rk-", "AIza")):
            return True
        if any(c.isdigit() for c in token) and any(c.isalpha() for c in token):
            return True
    return False


def _digest(salt: str, value: str) -> str:
    return hmac.new(salt.encode("ascii"), value.encode("utf-8"), hashlib.sha256).hexdigest()


class LLMGovernance:
    """Façade unique : inventaire, plafonds, alertes, audit, rotation."""

    def __init__(
        self,
        db_path: Optional[Path] = None,
        clock: Optional[Callable[[], datetime]] = None,
        alert_sink: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> None:
        self.db_path = Path(db_path) if db_path else default_db_path()
        self._clock = clock or _utc_now
        self._alert_sink = alert_sink
        self._lock = threading.RLock()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = self._connect()
        try:
            conn.executescript(_SCHEMA)
            conn.commit()
        finally:
            conn.close()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=15.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _now(self) -> datetime:
        return self._clock().astimezone(timezone.utc)

    def _tx(self):
        """Transaction avec fermeture réelle de la connexion (``with conn`` seul ne ferme pas)."""
        return _Tx(self)

    # ── Inventaire (CA1) ────────────────────────────────────────────────────

    def register_key(
        self,
        key_id: str,
        provider: str,
        tenant_slug: str,
        location: str,
        owner: str,
        key_value: Optional[str] = None,
        last_rotation: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Inscrit une clé à l'inventaire. ``tenant_slug='*'`` désigne une clé mutualisée.

        ``key_value`` n'est jamais stocké : seule une empreinte HMAC salée l'est, pour que
        ``verify_key`` puisse refuser une ancienne valeur après rotation.
        """
        for label, text in (("key_id", key_id), ("location", location), ("owner", owner)):
            if not text or not text.strip():
                raise GovernanceError(f"Champ obligatoire vide : {label}")
            if _looks_like_secret(text):
                raise GovernanceError(f"Le champ {label} ressemble à une valeur secrète : refusé.")
        if not provider.strip() or not tenant_slug.strip():
            raise GovernanceError("provider et tenant_slug sont obligatoires.")
        salt = digest = None
        if key_value:
            salt = secrets.token_hex(16)
            digest = _digest(salt, key_value)
        now = self._now()
        with self._lock, self._tx() as conn:
            if conn.execute("SELECT 1 FROM llm_keys WHERE key_id=?", (key_id,)).fetchone():
                raise GovernanceError(f"Clé déjà inscrite : {key_id}")
            conn.execute(
                "INSERT INTO llm_keys(key_id, provider, tenant_slug, location, owner,"
                " last_rotation, salt, digest, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (key_id, provider.strip().lower(), tenant_slug.strip().lower(), location.strip(),
                 owner.strip(), last_rotation, salt, digest, _iso(now)),
            )
        return self.get_key(key_id)

    def get_key(self, key_id: str) -> Dict[str, Any]:
        rows = [r for r in self.inventory() if r["key_id"] == key_id]
        if not rows:
            raise GovernanceError(f"Clé inconnue : {key_id}")
        return rows[0]

    def inventory(self) -> List[Dict[str, Any]]:
        """Inventaire publiable : aucune valeur, aucune empreinte."""
        with self._tx() as conn:
            rows = conn.execute(
                "SELECT key_id, provider, tenant_slug, location, owner, last_rotation"
                " FROM llm_keys ORDER BY provider, tenant_slug, key_id"
            ).fetchall()
        return [dict(r) for r in rows]

    def inventory_markdown(self) -> str:
        lines = [
            "| Clé | Fournisseur | Tenant | Emplacement | Dernière rotation | Responsable |",
            "|---|---|---|---|---|---|",
        ]
        for r in self.inventory():
            tenant = "mutualisée" if r["tenant_slug"] == SHARED_KEY_TENANT else r["tenant_slug"]
            lines.append(
                f"| {r['key_id']} | {r['provider']} | {tenant} | {r['location']} |"
                f" {r['last_rotation'] or 'jamais'} | {r['owner']} |"
            )
        return "\n".join(lines) + "\n"

    # ── Politique de plafond (CA2, CA3) ─────────────────────────────────────

    def set_policy(
        self,
        tenant_slug: str,
        monthly_cap_usd: Optional[float],
        mode: str = MODE_REFUSE,
        thresholds: Optional[List[float]] = None,
        drift_factor: float = DEFAULT_DRIFT_FACTOR,
    ) -> Dict[str, Any]:
        """Fixe la politique d'un tenant (``'*'`` = défaut). ``None`` = pas de plafond."""
        if mode not in (MODE_REFUSE, MODE_ALERT_ONLY):
            raise GovernanceError(f"Mode inconnu : {mode}")
        if monthly_cap_usd is not None and monthly_cap_usd <= 0:
            raise GovernanceError("monthly_cap_usd doit être > 0 ou None.")
        ths = sorted(set(thresholds if thresholds is not None else DEFAULT_THRESHOLDS))
        if not ths or any(t <= 0 for t in ths):
            raise GovernanceError("Les seuils doivent être des ratios > 0.")
        if drift_factor <= 1:
            raise GovernanceError("drift_factor doit être > 1.")
        slug = tenant_slug.strip().lower()
        with self._lock, self._tx() as conn:
            conn.execute(
                "INSERT INTO llm_policies(tenant_slug, monthly_cap_usd, mode, thresholds,"
                " drift_factor) VALUES (?,?,?,?,?) ON CONFLICT(tenant_slug) DO UPDATE SET"
                " monthly_cap_usd=excluded.monthly_cap_usd, mode=excluded.mode,"
                " thresholds=excluded.thresholds, drift_factor=excluded.drift_factor",
                (slug, monthly_cap_usd, mode, json.dumps(ths), drift_factor),
            )
        return self.get_policy(slug)

    def get_policy(self, tenant_slug: str) -> Dict[str, Any]:
        slug = tenant_slug.strip().lower()
        with self._tx() as conn:
            row = conn.execute("SELECT * FROM llm_policies WHERE tenant_slug=?", (slug,)).fetchone()
            if row is None:
                row = conn.execute(
                    "SELECT * FROM llm_policies WHERE tenant_slug=?", (DEFAULT_POLICY_TENANT,)
                ).fetchone()
        if row is None:
            return {
                "tenant_slug": slug, "monthly_cap_usd": None, "mode": MODE_REFUSE,
                "thresholds": list(DEFAULT_THRESHOLDS), "drift_factor": DEFAULT_DRIFT_FACTOR,
                "source": "builtin_no_cap",
            }
        return {
            "tenant_slug": slug, "monthly_cap_usd": row["monthly_cap_usd"], "mode": row["mode"],
            "thresholds": json.loads(row["thresholds"]), "drift_factor": row["drift_factor"],
            "source": "tenant" if row["tenant_slug"] == slug else "default",
        }

    def period_spend(self, tenant_slug: str, period: Optional[str] = None) -> float:
        period = period or _period_of(self._now())
        with self._tx() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(cost_usd), 0) AS s FROM llm_calls"
                " WHERE tenant_slug=? AND decision='allowed' AND substr(ts, 1, 7)=?",
                (tenant_slug.strip().lower(), period),
            ).fetchone()
        return float(row["s"])

    def authorize(
        self, tenant_slug: str, provider: str, model: str, estimated_cost_usd: float = 0.0
    ) -> Dict[str, Any]:
        """À appeler AVANT l'appel fournisseur. Refuse au-delà du plafond (mode ``refuse``)."""
        slug = tenant_slug.strip().lower()
        now = self._now()
        policy = self.get_policy(slug)
        cap = policy["monthly_cap_usd"]
        period = _period_of(now)
        spent = self.period_spend(slug, period)
        exceeded = cap is not None and (spent >= cap or spent + max(estimated_cost_usd, 0.0) > cap)
        decision = {
            "allowed": True, "tenant_slug": slug, "provider": provider, "model": model,
            "period": period, "spent_usd": round(spent, 6), "cap_usd": cap,
            "mode": policy["mode"], "reason": "ok", "ts": _iso(now),
        }
        if not exceeded:
            return decision
        decision["reason"] = "cap_exceeded"
        if policy["mode"] == MODE_REFUSE:
            decision["allowed"] = False
            self._insert_call(now, slug, provider, model, 0.0, 0, 0, None, None, "refused")
        self._raise_alert(
            "cap_exceeded", slug, f"cap_exceeded:{slug}:{now.strftime('%Y-%m-%dT%H')}",
            {"period": period, "spent_usd": round(spent, 6), "cap_usd": cap, "mode": policy["mode"],
             "estimated_cost_usd": estimated_cost_usd, "refused": not decision["allowed"],
             "provider": provider, "model": model},
        )
        return decision

    # ── Journal d'audit (CA6) et alertes (CA3) ──────────────────────────────

    def record_call(
        self,
        tenant_slug: str,
        provider: str,
        model: str,
        cost_usd: float,
        input_tokens: int = 0,
        output_tokens: int = 0,
        key_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """À appeler APRÈS l'appel, avec le coût lu à la source de vérité."""
        if cost_usd < 0:
            raise GovernanceError("cost_usd ne peut pas être négatif.")
        slug = tenant_slug.strip().lower()
        now = self._now()
        self._insert_call(now, slug, provider, model, cost_usd, input_tokens, output_tokens,
                          key_id, session_id, "allowed")
        policy = self.get_policy(slug)
        spent = self.period_spend(slug, _period_of(now))
        fired = self._check_thresholds(slug, policy, spent, now) + self._check_drift(slug, policy, now)
        return {"tenant_slug": slug, "period_spend_usd": round(spent, 6), "alerts": fired}

    def _insert_call(self, now, slug, provider, model, cost, tin, tout, key_id, session_id, decision):
        with self._lock, self._tx() as conn:
            conn.execute(
                "INSERT INTO llm_calls(ts, tenant_slug, provider, model, cost_usd, input_tokens,"
                " output_tokens, key_id, session_id, decision) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (_iso(now), slug, provider.strip().lower(), model, float(cost), int(tin), int(tout),
                 key_id, session_id, decision),
            )

    def _check_thresholds(self, slug: str, policy: Dict[str, Any], spent: float, now: datetime) -> List[str]:
        cap = policy["monthly_cap_usd"]
        if not cap:
            return []
        period = _period_of(now)
        fired = []
        for threshold in policy["thresholds"]:
            if spent >= cap * threshold:
                payload = {"period": period, "threshold_ratio": threshold, "spent_usd": round(spent, 6),
                           "cap_usd": cap, "threshold_usd": round(cap * threshold, 6)}
                if self._raise_alert("threshold", slug, f"threshold:{slug}:{period}:{threshold}", payload):
                    fired.append(f"threshold:{threshold}")
        return fired

    def _check_drift(self, slug: str, policy: Dict[str, Any], now: datetime) -> List[str]:
        """Dérive : dépense du jour > facteur x moyenne quotidienne des 7 jours précédents."""
        day = now.strftime("%Y-%m-%d")
        start = (now - timedelta(days=DRIFT_BASELINE_DAYS)).strftime("%Y-%m-%d")
        with self._tx() as conn:
            today = conn.execute(
                "SELECT COALESCE(SUM(cost_usd),0) AS s FROM llm_calls WHERE tenant_slug=?"
                " AND decision='allowed' AND substr(ts,1,10)=?", (slug, day)).fetchone()["s"]
            prev = conn.execute(
                "SELECT COALESCE(SUM(cost_usd),0) AS s FROM llm_calls WHERE tenant_slug=?"
                " AND decision='allowed' AND substr(ts,1,10)>=? AND substr(ts,1,10)<?",
                (slug, start, day)).fetchone()["s"]
        baseline = prev / DRIFT_BASELINE_DAYS
        if baseline <= 0 or today < DRIFT_MIN_TODAY_USD or today <= policy["drift_factor"] * baseline:
            return []
        payload = {"day": day, "today_usd": round(today, 6), "baseline_daily_usd": round(baseline, 6),
                   "drift_factor": policy["drift_factor"], "baseline_days": DRIFT_BASELINE_DAYS}
        return ["drift"] if self._raise_alert("drift", slug, f"drift:{slug}:{day}", payload) else []

    def _raise_alert(self, kind: str, slug: str, dedupe_key: str, payload: Dict[str, Any]) -> bool:
        now = self._now()
        with self._lock, self._tx() as conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO llm_alerts(ts, kind, tenant_slug, dedupe_key, payload)"
                " VALUES (?,?,?,?,?)", (_iso(now), kind, slug, dedupe_key, json.dumps(payload)))
            inserted = cur.rowcount == 1
        if not inserted:
            return False
        event = {"ts": _iso(now), "kind": kind, "tenant_slug": slug, **payload}
        _log.warning("[LLM-ALERT] %s", json.dumps(event, sort_keys=True))
        if self._alert_sink is not None:
            try:
                self._alert_sink(event)
            except Exception:  # un canal d'alerte en panne ne doit jamais bloquer l'appel métier
                _log.exception("Échec du canal d'alerte externe (alerte conservée en base).")
        return True

    def alerts(self, tenant_slug: Optional[str] = None, kind: Optional[str] = None) -> List[Dict[str, Any]]:
        query, args = "SELECT ts, kind, tenant_slug, payload FROM llm_alerts WHERE 1=1", []
        if tenant_slug:
            query += " AND tenant_slug=?"
            args.append(tenant_slug.strip().lower())
        if kind:
            query += " AND kind=?"
            args.append(kind)
        with self._tx() as conn:
            rows = conn.execute(query + " ORDER BY alert_id", args).fetchall()
        return [{"ts": r["ts"], "kind": r["kind"], "tenant_slug": r["tenant_slug"],
                 **json.loads(r["payload"])} for r in rows]

    def audit(self, tenant_slug: Optional[str] = None, since: Optional[str] = None,
              until: Optional[str] = None, limit: int = 1000) -> List[Dict[str, Any]]:
        """Journal des appels : tenant, fournisseur, modèle, coût, horodatage, décision."""
        query = ("SELECT ts, tenant_slug, provider, model, cost_usd, input_tokens, output_tokens,"
                 " key_id, session_id, decision FROM llm_calls WHERE 1=1")
        args: List[Any] = []
        if tenant_slug:
            query += " AND tenant_slug=?"
            args.append(tenant_slug.strip().lower())
        if since:
            query += " AND ts>=?"
            args.append(since)
        if until:
            query += " AND ts<?"
            args.append(until)
        with self._tx() as conn:
            rows = conn.execute(query + " ORDER BY call_id LIMIT ?", [*args, int(limit)]).fetchall()
        return [dict(r) for r in rows]

    def audit_csv(self, **filters: Any) -> str:
        buf = io.StringIO()
        cols = ["ts", "tenant_slug", "provider", "model", "cost_usd", "input_tokens",
                "output_tokens", "key_id", "session_id", "decision"]
        writer = csv.DictWriter(buf, fieldnames=cols)
        writer.writeheader()
        writer.writerows(self.audit(**filters))
        return buf.getvalue()

    # ── Rotation à chaud (CA4) ──────────────────────────────────────────────

    @staticmethod
    def _check_actor(actor: str) -> str:
        if not actor or "@" in actor or not _ACTOR_RE.match(actor):
            raise GovernanceError(
                "Acteur invalide : un compte de service est exigé (aucun identifiant humain, S1.3)."
            )
        return actor

    @staticmethod
    def _log_rotation(conn: sqlite3.Connection, key_id: str, event: str, actor: str,
                      detail: Dict[str, Any], now: datetime) -> None:
        conn.execute(
            "INSERT INTO llm_rotation_log(ts, key_id, event, actor, detail) VALUES (?,?,?,?,?)",
            (_iso(now), key_id, event, actor, json.dumps(detail, sort_keys=True)))

    def rotate_key(self, key_id: str, new_key_value: str, actor: str,
                   grace_seconds: int = DEFAULT_GRACE_SECONDS) -> Dict[str, Any]:
        """Active la nouvelle valeur et ouvre une fenêtre de grâce pour l'ancienne.

        Pendant la fenêtre, les sessions déjà ouvertes (clé injectée au démarrage du conteneur)
        continuent avec l'ancienne valeur ; après ``grace_until`` elle est refusée.
        La valeur reçue n'est ni journalisée ni stockée : seule son empreinte salée l'est.
        """
        self._check_actor(actor)
        if not new_key_value or len(new_key_value) < 8:
            raise GovernanceError("Nouvelle valeur de clé absente ou trop courte.")
        if grace_seconds < 0:
            raise GovernanceError("grace_seconds doit être >= 0.")
        now = self._now()
        grace_until = now + timedelta(seconds=grace_seconds)
        with self._lock, self._tx() as conn:
            row = conn.execute("SELECT * FROM llm_keys WHERE key_id=?", (key_id,)).fetchone()
            if row is None:
                raise GovernanceError(f"Clé inconnue : {key_id}")
            if row["digest"] and hmac.compare_digest(row["digest"], _digest(row["salt"], new_key_value)):
                raise GovernanceError("La nouvelle valeur est identique à la valeur active.")
            self._log_rotation(conn, key_id, "rotation_started", actor,
                               {"provider": row["provider"], "tenant_slug": row["tenant_slug"],
                                "grace_seconds": grace_seconds}, now)
            salt = secrets.token_hex(16)
            had_previous = bool(row["digest"])
            if had_previous:
                conn.execute(
                    "INSERT INTO llm_retired_keys(key_id, salt, digest, retired_at, grace_until)"
                    " VALUES (?,?,?,?,?)",
                    (key_id, row["salt"], row["digest"], _iso(now), _iso(grace_until)))
            conn.execute(
                "UPDATE llm_keys SET salt=?, digest=?, last_rotation=? WHERE key_id=?",
                (salt, _digest(salt, new_key_value), _iso(now), key_id))
            self._log_rotation(conn, key_id, "new_key_activated", actor, {}, now)
            if had_previous:
                self._log_rotation(conn, key_id, "old_key_grace_open", actor,
                                   {"grace_until": _iso(grace_until)}, now)
        return {"key_id": key_id, "rotated_at": _iso(now),
                "grace_until": _iso(grace_until) if had_previous else None}

    def finalize_rotations(self) -> List[str]:
        """Révoque les anciennes valeurs dont la fenêtre de grâce est échue."""
        now = self._now()
        revoked: List[str] = []
        with self._lock, self._tx() as conn:
            rows = conn.execute(
                "SELECT retired_id, key_id, grace_until FROM llm_retired_keys"
                " WHERE revoked_at IS NULL AND grace_until<=?", (_iso(now),)).fetchall()
            for r in rows:
                conn.execute("UPDATE llm_retired_keys SET revoked_at=? WHERE retired_id=?",
                             (_iso(now), r["retired_id"]))
                self._log_rotation(conn, r["key_id"], "old_key_revoked", "system:governance",
                                   {"grace_until": r["grace_until"]}, now)
                revoked.append(r["key_id"])
        return revoked

    def verify_key(self, key_id: str, presented_value: str) -> Dict[str, Any]:
        """Statut d'une valeur présentée : ``active``, ``grace``, ``revoked`` ou ``unknown``.

        Seuls ``active`` et ``grace`` sont acceptables ; tout refus est journalisé.
        """
        self.finalize_rotations()
        now = self._now()
        status = "unknown"
        with self._lock, self._tx() as conn:
            row = conn.execute("SELECT salt, digest FROM llm_keys WHERE key_id=?", (key_id,)).fetchone()
            if row is None:
                raise GovernanceError(f"Clé inconnue : {key_id}")
            if row["digest"] and hmac.compare_digest(row["digest"], _digest(row["salt"], presented_value)):
                status = "active"
            else:
                for r in conn.execute(
                    "SELECT salt, digest, revoked_at FROM llm_retired_keys WHERE key_id=?"
                    " ORDER BY retired_id DESC", (key_id,)).fetchall():
                    if hmac.compare_digest(r["digest"], _digest(r["salt"], presented_value)):
                        status = "revoked" if r["revoked_at"] else "grace"
                        break
            if status in ("revoked", "unknown"):
                self._log_rotation(conn, key_id, "verification_refused", "system:governance",
                                   {"status": status}, now)
        return {"key_id": key_id, "status": status, "accepted": status in ("active", "grace"),
                "ts": _iso(now)}

    def rotation_log(self, key_id: Optional[str] = None) -> List[Dict[str, Any]]:
        query, args = "SELECT ts, key_id, event, actor, detail FROM llm_rotation_log", []
        if key_id:
            query += " WHERE key_id=?"
            args.append(key_id)
        with self._tx() as conn:
            rows = conn.execute(query + " ORDER BY event_id", args).fetchall()
        return [{"ts": r["ts"], "key_id": r["key_id"], "event": r["event"], "actor": r["actor"],
                 "detail": json.loads(r["detail"])} for r in rows]


class _Tx:
    """Gestionnaire de contexte : commit si succès, rollback sinon, fermeture dans tous les cas."""

    def __init__(self, gov: LLMGovernance) -> None:
        self._conn = gov._connect()

    def __enter__(self) -> sqlite3.Connection:
        return self._conn

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            if exc_type is None:
                self._conn.commit()
            else:
                self._conn.rollback()
        finally:
            self._conn.close()
