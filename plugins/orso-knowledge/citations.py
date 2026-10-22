"""Citation obligatoire : vérifie qu'une réponse appuyée sur des passages cite ses sources."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable

_CITATION_RE = re.compile(r"\[Source:[^\]]*\]")

NOTICE = (
    "⚠️ Réponse signalée : elle s'appuie sur des documents du client mais ne cite pas de source "
    "valide. Format attendu : {example}"
)
UNKNOWN_NOTICE = "⚠️ Source citée non reconnue (absente des passages retrouvés) : {sources}"


@dataclass(frozen=True)
class Verdict:
    ok: bool
    cited: list[str] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)


def verify_answer(answer: str, retrieved_citations: Iterable[str]) -> Verdict:
    """Valide si au moins une citation retrouvée figure dans ``answer`` et si aucune citation
    ``[Source: ...]`` citée n'est inventée."""
    retrieved = list(dict.fromkeys(retrieved_citations))
    cited = [c for c in retrieved if c in answer]
    unknown = [c for c in _CITATION_RE.findall(answer) if c not in retrieved]
    return Verdict(ok=bool(cited) and not unknown, cited=cited, unknown=unknown)


def flag_answer(answer: str, retrieved_citations: Iterable[str]) -> str | None:
    """``None`` si la réponse est conforme, sinon la réponse suivie d'un signalement explicite."""
    retrieved = list(dict.fromkeys(retrieved_citations))
    verdict = verify_answer(answer, retrieved)
    if verdict.ok:
        return None
    notices = []
    if not verdict.cited:
        notices.append(NOTICE.format(example=retrieved[0] if retrieved else "[Source: <document>, vN, §k]"))
    if verdict.unknown:
        notices.append(UNKNOWN_NOTICE.format(sources=", ".join(verdict.unknown)))
    return answer.rstrip() + "\n\n" + "\n".join(notices)
