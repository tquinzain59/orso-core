"""Citation obligatoire et bloquante : une réponse appuyée sur des passages doit citer sa source.

Une réponse non conforme n'est pas livrée : :func:`block_answer` renvoie le texte de remplacement
(un refus qui ne reprend pas le contenu non sourcé), que le hook ``transform_llm_output`` substitue
à la réponse du modèle.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable

_CITATION_RE = re.compile(r"\[Source:[^\]]*\]")
_MAX_ECHO = 200  # une source inventée est recopiée dans le refus : tronquée, c'est du texte du modèle

REFUSAL = (
    "⛔ Réponse refusée : elle s'appuie sur des documents du client mais ne cite aucune source "
    "valide. Elle n'est pas transmise. Format de citation attendu : {example}"
)
UNKNOWN_REFUSAL = (
    "⛔ Réponse refusée : elle cite une source absente des passages retrouvés ({sources}). "
    "Elle n'est pas transmise."
)


@dataclass(frozen=True)
class Verdict:
    ok: bool
    cited: list[str] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)


def verify_answer(
    answer: str, retrieved_citations: Iterable[str], known_citations: Iterable[str] = ()
) -> Verdict:
    """Conforme si, lorsque des passages ont été retrouvés ce tour, au moins l'un d'eux est cité, et
    si aucune citation ``[Source: ...]`` n'est inventée (absente de ``retrieved_citations`` comme de
    ``known_citations``, les passages retrouvés plus tôt dans la session)."""
    retrieved = list(dict.fromkeys(retrieved_citations))
    valid = set(retrieved) | set(known_citations)
    cited = [c for c in retrieved if c in answer]
    unknown = [c for c in _CITATION_RE.findall(answer) if c not in valid]
    return Verdict(ok=(bool(cited) or not retrieved) and not unknown, cited=cited, unknown=unknown)


def block_answer(
    answer: str, retrieved_citations: Iterable[str], known_citations: Iterable[str] = ()
) -> str | None:
    """``None`` si la réponse est conforme, sinon le refus qui la remplace (jamais la réponse suivie
    d'un avertissement : le contenu non sourcé n'est pas transmis)."""
    retrieved = list(dict.fromkeys(retrieved_citations))
    verdict = verify_answer(answer, retrieved, known_citations)
    if verdict.ok:
        return None
    if verdict.unknown:
        sources = ", ".join(s[:_MAX_ECHO] for s in verdict.unknown)
        return UNKNOWN_REFUSAL.format(sources=sources)
    return REFUSAL.format(example=retrieved[0])
