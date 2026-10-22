"""Registre de consommation et trace datée de la politique de modèle (KAN-127).

Deux fichiers sous ``<HERMES_HOME>/orso_model_policy/`` : ``state.json`` (cumul du mois courant,
reconstruit à chaque changement de mois) et ``events.jsonl`` (traces datées append-only : usages
et événements de politique). Chaque conteneur client a son propre ``HERMES_HOME`` ; ``client_id``
est porté dans chaque ligne pour que la trace reste attribuable.
"""

from __future__ import annotations

import contextlib
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, Optional

try:
    import fcntl
except ImportError:  # Windows : verrou de fil seul, le conteneur Orso est Linux
    fcntl = None  # type: ignore[assignment]

from . import policy as pol

_THREAD_LOCK = threading.RLock()


class Ledger:
    def __init__(self, directory: Path, client_id: str, now_fn: Optional[Callable[[], datetime]] = None):
        self.dir = Path(directory)
        self.client_id = client_id
        self._now = now_fn or (lambda: datetime.now(timezone.utc))

    @property
    def state_path(self) -> Path:
        return self.dir / "state.json"

    @property
    def events_path(self) -> Path:
        return self.dir / "events.jsonl"

    @contextlib.contextmanager
    def _locked(self) -> Iterator[None]:
        self.dir.mkdir(parents=True, exist_ok=True)
        with _THREAD_LOCK, open(self.dir / ".lock", "a", encoding="utf-8") as lock_fh:
            if fcntl is not None:
                fcntl.flock(lock_fh, fcntl.LOCK_EX)
            try:
                yield
            finally:
                if fcntl is not None:
                    fcntl.flock(lock_fh, fcntl.LOCK_UN)

    def _load_state(self) -> Dict[str, Any]:
        month = pol.month_key(self._now())
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            state = {}
        if state.get("month") != month or state.get("client_id") != self.client_id:
            state = {"month": month, "client_id": self.client_id, "spent_eur": 0.0, "flags": []}
        return state

    def _save_state(self, state: Dict[str, Any]) -> None:
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
        os.replace(tmp, self.state_path)

    def _append(self, record: Dict[str, Any]) -> Dict[str, Any]:
        now = self._now()
        line = {"ts": now.isoformat(), "month": pol.month_key(now), "client_id": self.client_id, **record}
        with open(self.events_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(line, ensure_ascii=False, sort_keys=True) + "\n")
        return line

    def spent_eur(self) -> float:
        with self._locked():
            return float(self._load_state()["spent_eur"])

    def record_usage(self, *, provider: str, model: str, cost_usd: float, usd_to_eur: float, tokens: int = 0) -> float:
        """Ajoute un appel au cumul du mois ; renvoie le cumul en euros."""
        cost_eur = max(0.0, cost_usd) * usd_to_eur
        with self._locked():
            state = self._load_state()
            state["spent_eur"] = float(state["spent_eur"]) + cost_eur
            self._save_state(state)
            self._append({
                "type": "usage", "provider": provider, "model": model, "tokens": tokens,
                "cost_usd": round(cost_usd, 8), "cost_eur": round(cost_eur, 8),
                "spent_eur": round(state["spent_eur"], 8),
            })
            return float(state["spent_eur"])

    def record_event(self, code: str, **detail: Any) -> Dict[str, Any]:
        with self._locked():
            return self._append({"type": "event", "code": code, **detail})

    def first_time(self, flag: str) -> bool:
        """Vrai la première fois que ``flag`` est levé dans le mois (alerte notifiée une seule fois)."""
        with self._locked():
            state = self._load_state()
            if flag in state["flags"]:
                return False
            state["flags"].append(flag)
            self._save_state(state)
            return True

    def events(self) -> list:
        try:
            lines = self.events_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        return [json.loads(line) for line in lines if line.strip()]
