"""Politique de reprise après échec d'une exécution côté client (KAN-128, CA2).

Comportement produit : un échec en cours d'exécution déclenche un rejeu automatique
(``MAX_REPLAYS`` rejeux au plus) ; si l'échec persiste, l'appelant en est informé pour
signaler l'échec au client. Ce module est volontairement indépendant du moteur : il
enveloppe un callable fourni par l'appelant et ne touche ni à la boucle d'exécution
ni à la persistance.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional

_log = logging.getLogger("hermes_cli.client_run_replay")

# Nombre de rejeux automatiques après la première tentative. Valeur de produit, non secrète.
MAX_REPLAYS = 2
# Pause (secondes) avant le rejeu n°1, n°2... ; la dernière valeur est réutilisée au-delà.
REPLAY_BACKOFF_SECONDS = (1.0, 3.0)


class RunFailure(Exception):
    """Échec d'une tentative d'exécution sans exception native (réponse vide, modèle injoignable)."""


@dataclass
class ReplayOutcome:
    """Résultat d'une exécution enveloppée par :func:`run_with_replay`."""

    result: Any = None
    attempts: int = 0
    failed: bool = False
    # Erreurs de chaque tentative en échec : détail INTERNE, jamais exposé au client.
    errors: List[BaseException] = field(default_factory=list)

    @property
    def replays(self) -> int:
        return max(0, self.attempts - 1)


def run_with_replay(
    attempt_fn: Callable[[int], Any],
    *,
    max_replays: Optional[int] = None,
    on_replay: Optional[Callable[[int, BaseException], None]] = None,
    sleep: Callable[[float], None] = time.sleep,
) -> ReplayOutcome:
    """Exécute ``attempt_fn(numero_tentative)`` puis la rejoue automatiquement en cas d'échec.

    Une tentative échoue quand ``attempt_fn`` lève une exception. ``on_replay(n, erreur)`` est
    appelé juste avant chaque rejeu (n = numéro du rejeu, à partir de 1). Quand toutes les
    tentatives ont échoué, ``ReplayOutcome.failed`` vaut True : c'est à l'appelant de signaler
    l'échec au client.
    """
    replays_allowed = MAX_REPLAYS if max_replays is None else max_replays
    outcome = ReplayOutcome()
    for attempt in range(1, replays_allowed + 2):
        outcome.attempts = attempt
        try:
            outcome.result = attempt_fn(attempt)
            outcome.failed = False
            return outcome
        except Exception as exc:
            outcome.errors.append(exc)
            _log.warning("Exécution en échec (tentative %d/%d): %s", attempt, replays_allowed + 1, exc)
            if attempt > replays_allowed:
                break
            if on_replay is not None:
                on_replay(attempt, exc)
            if REPLAY_BACKOFF_SECONDS:
                idx = min(attempt - 1, len(REPLAY_BACKOFF_SECONDS) - 1)
                sleep(REPLAY_BACKOFF_SECONDS[idx])
    outcome.failed = True
    outcome.result = None
    return outcome
