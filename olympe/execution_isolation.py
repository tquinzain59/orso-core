"""Isolation entre exécutions simultanées d'un même client (KAN-129 / CA2).

Module de marge (outillage de recette, aucune modification du moteur). Il ne crée pas d'isolation : il la
*mesure*. Deux exécutions parallèles d'un même client sont lancées via la couche d'exécution d'outils du
moteur ; le verdict dit si l'une voit les fichiers de l'autre ou partage son environnement d'exécution.

Verdicts (jamais de « vert vide » : une recette qui n'a pas pu s'exécuter n'est pas un succès) :
    ISOLATED       aucune interférence constatée ;
    INTERFERENCE   au moins une interférence constatée (liste dans ``findings``) ;
    NOT_VERIFIED   la recette n'a pas pu s'exécuter (backend indisponible, exécution en échec).
"""

from __future__ import annotations

import re
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional

ISOLATED = "ISOLATED"
INTERFERENCE = "INTERFERENCE"
NOT_VERIFIED = "NOT_VERIFIED"

EXIT_CODES: Dict[str, int] = {ISOLATED: 0, INTERFERENCE: 1, NOT_VERIFIED: 2}

# Réglage moteur qui donne un environnement d'exécution par session : backend docker, sans conteneur
# partagé entre sessions. Avec ``container_persistent: true`` (défaut moteur), toutes les sessions d'un même
# profil/client sont ramenées sur UN SEUL conteneur (tools/terminal_tool.py, _resolve_container_task_id).
REQUIRED_TERMINAL_SETTINGS: Dict[str, Any] = {"backend": "docker", "container_persistent": False}

_PROBE_GLOB = "/tmp/orso_ca2_{run}_*.txt"
_PROBE_FILE = "/tmp/orso_ca2_{run}_{idx}.txt"
_DIGEST_PINNED = re.compile(r"@sha256:[0-9a-f]{64}$")

# Fabrique d'environnement d'exécution : (index) -> objet avec execute(cmd) -> {"output", "returncode"} et cleanup().
EnvFactory = Callable[[int], Any]


@dataclass
class IsolationReport:
    verdict: str
    findings: List[str] = field(default_factory=list)
    executions: List[Dict[str, Any]] = field(default_factory=list)
    detail: str = ""

    @property
    def exit_code(self) -> int:
        return EXIT_CODES[self.verdict]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "verdict": self.verdict,
            "findings": self.findings,
            "executions": self.executions,
            "detail": self.detail,
        }


def execution_isolation_gaps(terminal_cfg: Optional[Mapping[str, Any]]) -> List[str]:
    """Écarts entre la section ``terminal`` d'une config client et l'isolation par exécution requise.

    Une section absente vaut défauts moteur : backend ``local`` (aucune isolation) et conteneur persistant.
    """
    cfg = dict(terminal_cfg or {})
    backend = str(cfg.get("backend", cfg.get("env_type", "local"))).strip().lower() or "local"
    gaps: List[str] = []
    if backend != REQUIRED_TERMINAL_SETTINGS["backend"]:
        gaps.append(
            f"terminal.backend={backend!r} : les exécutions partagent le même système de fichiers "
            f"(attendu {REQUIRED_TERMINAL_SETTINGS['backend']!r})"
        )
    if cfg.get("container_persistent", True) is not False:
        gaps.append(
            "terminal.container_persistent n'est pas false : les sessions d'un même client sont "
            "ramenées sur un seul conteneur"
        )
    return gaps


def is_digest_pinned(image: str) -> bool:
    """Vrai si l'image est référencée par empreinte (``repo@sha256:<64 hex>``) — reproductibilité (CA4)."""
    return bool(_DIGEST_PINNED.search(image or ""))


def _out(result: Any) -> str:
    return str((result or {}).get("output", "")).strip()


def run_isolation_probe(make_env: EnvFactory, *, parallel: int = 2, step_timeout: float = 120.0) -> IsolationReport:
    """Lance ``parallel`` exécutions simultanées et constate d'éventuelles interférences.

    Chaque exécution : (1) écrit un fichier-témoin et pose une variable d'état, (2) attend que toutes les
    autres aient écrit (barrière : le recouvrement est garanti), (3) liste les fichiers-témoins visibles,
    relit son état et son identité d'hôte. Interférence = témoin d'une autre exécution visible, état
    d'une autre exécution lu, ou identité d'hôte partagée.
    """
    if parallel < 2:
        return IsolationReport(NOT_VERIFIED, detail="au moins deux exécutions parallèles sont requises")

    run = uuid.uuid4().hex[:8]
    barrier = threading.Barrier(parallel, timeout=step_timeout)
    results: List[Dict[str, Any]] = [{} for _ in range(parallel)]
    envs: List[Any] = [None] * parallel

    def _worker(idx: int) -> None:
        res: Dict[str, Any] = {"index": idx}
        results[idx] = res
        try:
            env = make_env(idx)
            envs[idx] = env
            own = _PROBE_FILE.format(run=run, idx=idx)
            write = env.execute(f"echo marker-{idx} > {own} && export ORSO_CA2_STATE=state-{idx}")
            res["write_rc"] = (write or {}).get("returncode")
            barrier.wait()
            seen = env.execute(
                f"ls {_PROBE_GLOB.format(run=run)} 2>/dev/null; echo STATE=${{ORSO_CA2_STATE}}; echo HOST=$(hostname)"
            )
            lines = _out(seen).splitlines()
            res["files"] = sorted(ln.strip() for ln in lines if ln.startswith("/tmp/orso_ca2_"))
            res["state"] = next((ln[6:] for ln in lines if ln.startswith("STATE=")), None)
            res["host"] = next((ln[5:] for ln in lines if ln.startswith("HOST=")), None)
            res["own_file"] = own
        except Exception as exc:  # noqa: BLE001 — toute défaillance rend la recette NOT_VERIFIED, jamais vert
            res["error"] = f"{type(exc).__name__}: {exc}"
            barrier.abort()

    threads = [threading.Thread(target=_worker, args=(i,), name=f"ca2-exec-{i}") for i in range(parallel)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(step_timeout * 3)

    for env in envs:
        if env is not None:
            try:
                env.execute(f"rm -f {_PROBE_GLOB.format(run=run)}")
            except Exception:  # noqa: BLE001 — nettoyage au mieux ; le verdict ne dépend pas de lui
                pass
            try:
                env.cleanup()
            except Exception:  # noqa: BLE001
                pass

    errors = [f"exécution {r.get('index')}: {r['error']}" for r in results if r.get("error")]
    incomplete = [r.get("index") for r in results if not r.get("error") and "own_file" not in r]
    if errors or incomplete:
        detail = "; ".join(errors) or f"exécutions incomplètes : {incomplete}"
        return IsolationReport(NOT_VERIFIED, executions=results, detail=detail)

    findings: List[str] = []
    for r in results:
        if r.get("write_rc") not in (0, None):
            return IsolationReport(NOT_VERIFIED, executions=results, detail=f"écriture du témoin en échec (exécution {r['index']})")
        foreign = [f for f in r["files"] if f != r["own_file"]]
        if foreign:
            findings.append(f"exécution {r['index']} voit des fichiers d'une autre exécution : {foreign}")
        if r["state"] != f"state-{r['index']}" and r["state"] not in (None, ""):
            findings.append(f"exécution {r['index']} lit l'état d'une autre exécution : {r['state']!r}")
        if r["own_file"] not in r["files"]:
            return IsolationReport(NOT_VERIFIED, executions=results, detail=f"témoin propre illisible (exécution {r['index']})")
    hosts = [r["host"] for r in results]
    if len(set(hosts)) < len(hosts):
        findings.append(f"identité d'hôte partagée entre exécutions : {hosts}")

    return IsolationReport(INTERFERENCE if findings else ISOLATED, findings=findings, executions=results)
