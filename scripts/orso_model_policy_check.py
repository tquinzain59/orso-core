#!/usr/bin/env python3
"""Contrôle et preuves de la politique de modèle Orso (KAN-127).

Sous-commandes (code retour 0 = conforme / preuve produite, 1 = non conforme, 2 = non exécutable) :

  validate            politique + config/hermes*.yaml conformes (CA1)
  simulate-cap        plafond posé à la valeur de la politique, dépassement simulé (CA2)
  simulate-fallback   coupure du primaire simulée, secours actif, trace + information client (CA3)
  evaluate            protocole d'évaluation comparative DeepSeek/Mistral via OpenRouter (CA4) ;
                      nécessite OPENROUTER_API_KEY dans l'environnement (jamais affichée)

Les simulations rejouent la séquence de hooks du plugin sur un HERMES_HOME temporaire : elles
prouvent la logique du plugin, pas une coupure réelle du fournisseur (voir le handoff).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

REPO = Path(__file__).resolve().parent.parent
PLUGIN_DIR = REPO / "plugins" / "orso-model-policy"
POLICY_PATH = REPO / "config" / "orso_model_policy.yaml"
HERMES_CONFIGS = (REPO / "config" / "hermes.yaml", REPO / "config" / "hermes.default.yaml")


def load_plugin_package():
    """Charge le paquet du plugin (nom de dossier avec tiret : import par chemin)."""
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    name = "orso_model_policy_plugin"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, PLUGIN_DIR / "__init__.py", submodule_search_locations=[str(PLUGIN_DIR)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _emit(label: str, payload: Any) -> None:
    print(f"{label}: {json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)}")


def cmd_validate(_: argparse.Namespace) -> int:
    plugin = load_plugin_package()
    pol = sys.modules[f"{plugin.__name__}.policy"]
    policy = pol.load_policy(POLICY_PATH)
    problems: List[str] = []
    for cfg_path in HERMES_CONFIGS:
        cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        found = pol.validate_hermes_config(policy, cfg)
        enabled = ((cfg.get("plugins") or {}).get("enabled")) or []
        if "orso-model-policy" not in enabled:
            found.append("plugins.enabled ne contient pas orso-model-policy")
        if cfg.get("fallback_model", {}).get("model") != policy.fallback_model:
            found.append("fallback_model différent de routing.fallback de la politique")
        if (cfg.get("model") or {}).get("default") != policy.primary_model:
            found.append("model.default différent de routing.primary de la politique")
        _emit("config", {"file": str(cfg_path.relative_to(REPO)), "problems": found})
        problems += [f"{cfg_path.name}: {p}" for p in found]
    _emit("policy", {
        "file": str(POLICY_PATH.relative_to(REPO)), "decided_on": policy.decided_on,
        "required_provider": policy.required_provider, "forbid_local": policy.forbid_local,
        "allowed_prefixes": policy.allowed_prefixes, "default_monthly_eur": policy.default_monthly_eur,
        "primary": policy.primary_model, "fallback": policy.fallback_model,
    })
    print("RESULT:", "CONFORME" if not problems else "NON CONFORME")
    return 0 if not problems else 1


def _runtime(tmp: str, now: List[datetime]):
    plugin = load_plugin_package()
    pol = sys.modules[f"{plugin.__name__}.policy"]
    ledger_mod = sys.modules[f"{plugin.__name__}.ledger"]
    policy = pol.load_policy(POLICY_PATH)
    ledger = ledger_mod.Ledger(Path(tmp) / "orso_model_policy", "client-demo", now_fn=lambda: now[0])
    return plugin, pol, policy, ledger, plugin.PolicyRuntime(policy, ledger)


def cmd_simulate_cap(_: argparse.Namespace) -> int:
    now = [datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)]
    with tempfile.TemporaryDirectory() as tmp:
        plugin, pol, policy, ledger, rt = _runtime(tmp, now)
        _emit("seuil", {"client": ledger.client_id, "monthly_cap_eur": policy.monthly_cap_eur(ledger.client_id)})
        sent: List[str] = []

        def provider_call(_request):  # remplace le fournisseur : compte les requêtes réellement émises
            sent.append("request")
            return "REPONSE_FOURNISSEUR"

        steps = (("sous le seuil", 5.0), ("alerte (80 %)", 11.5), ("plafond dépassé", 4.0))
        outcome = {}
        for label, extra_eur in steps:
            now[0] += timedelta(minutes=5)
            plugin._call_cost_usd = lambda *_a, _c=extra_eur, **_k: _c  # coût d'un appel simulé, chemin réel ensuite
            rt.post_api_request(model=policy.primary_model, provider="openrouter", usage={"total_tokens": 1})
            verdict = rt.verdict()
            notice = rt.transform_llm_output(response_text="réponse", session_id="s1", model=policy.primary_model)
            reply = rt.llm_execution(request={}, next_call=provider_call, api_mode="chat_completions",
                                     model=policy.primary_model, session_id="s1")
            blocked = getattr(reply, "id", "") == "orso-model-policy-block"
            outcome[label] = {"spent_eur": round(verdict.spent_eur, 2), "status": verdict.status, "code": verdict.code,
                              "client_notice": notice, "request_blocked": blocked}
            _emit(f"etape[{label}]", outcome[label])
        _emit("requetes_fournisseur_emises", len(sent))
        _emit("trace", [e for e in ledger.events() if e["type"] == "event"])
        ok = (
            outcome["sous le seuil"]["status"] == "ok"
            and outcome["alerte (80 %)"]["code"] == pol.CODE_CAP_ALERT
            and outcome["plafond dépassé"]["code"] == pol.CODE_CAP_BLOCKED
            and outcome["plafond dépassé"]["request_blocked"]
            and len(sent) == 2
        )
    print("RESULT:", "ALERTE PUIS BLOCAGE OBSERVES" if ok else "ECHEC")
    return 0 if ok else 1


def cmd_simulate_fallback(_: argparse.Namespace) -> int:
    now = [datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)]
    with tempfile.TemporaryDirectory() as tmp:
        _, pol, policy, ledger, rt = _runtime(tmp, now)
        sid = "s-fallback"
        rt.pre_api_request(model=policy.primary_model, provider="openrouter", session_id=sid)
        now[0] += timedelta(seconds=2)
        rt.api_request_error(model=policy.primary_model, status_code=503, reason="service_unavailable", session_id=sid)
        now[0] += timedelta(seconds=1)
        rt.pre_api_request(model=policy.fallback_model, provider="openrouter", session_id=sid)
        notice = rt.transform_llm_output(response_text="Voici la relance.", session_id=sid, model=policy.fallback_model)
        _emit("modele_actif", policy.fallback_model)
        _emit("information_client", notice)
        events = [e for e in ledger.events() if e["type"] == "event"]
        _emit("trace", events)
        ok = (
            any(e["code"] == pol.CODE_FALLBACK and e["fallback"] == policy.fallback_model for e in events)
            and any(e["code"] == pol.CODE_PRIMARY_ERROR for e in events)
            and any(e["code"] == pol.CODE_CLIENT_INFORMED and e["about"] == pol.CODE_FALLBACK for e in events)
            and bool(notice) and pol.CODE_FALLBACK in notice
        )
    print("RESULT:", "BASCULE TRACEE ET CLIENT INFORME" if ok else "ECHEC")
    return 0 if ok else 1


# --- Évaluation comparative (CA4) ------------------------------------------------------------

EVAL_CASES: Tuple[Dict[str, Any], ...] = (
    {"id": "indemnite_recouvrement", "max_words": 60,
     "prompt": "En droit commercial français, quel est le montant de l'indemnité forfaitaire pour frais de "
               "recouvrement due à un créancier professionnel en cas de retard de paiement ? Une phrase.",
     "checks": [r"\b40\b"]},
    {"id": "somme_factures", "max_words": 80,
     "prompt": "Additionne ces trois factures en euros : 1250,40 ; 480,10 ; 99,50. Donne uniquement le total.",
     "checks": [r"1\s?830(?:[.,]00)?"]},
    {"id": "extraction_json", "max_words": 120,
     "prompt": "Extrais en JSON strict (clés client, montant, echeance) : « La société Durand SARL doit 2300,00 € "
               "pour la facture échue le 15/09/2026. » Réponds uniquement avec le JSON.",
     "checks": [r"Durand", r"2300", r"15/09/2026|2026-09-15"], "json": True},
    {"id": "relance_courtoise", "max_words": 150,
     "prompt": "Rédige en français une relance courtoise (moins de 100 mots) pour la facture n°F-2026-114 de "
               "1200 € échue depuis 30 jours. Cite l'article L.441-10 du Code de commerce.",
     "checks": [r"F-2026-114", r"L\.?\s?441-10", r"1\s?200"]},
    {"id": "langue_francaise", "max_words": 60,
     "prompt": "Explique en deux phrases, en français uniquement, ce qu'est un échéancier de paiement.",
     "checks": [r"échéanc|paiement"], "forbid": [r"\bthe\b", r"\bpayment schedule\b"]},
)


def _score(case: Dict[str, Any], text: str) -> Dict[str, Any]:
    results = {c: bool(re.search(c, text, re.IGNORECASE)) for c in case["checks"]}
    if case.get("json"):
        m = re.search(r"\{.*\}", text, re.DOTALL)
        try:
            json.loads(m.group(0) if m else text)
            results["json_valide"] = True
        except ValueError:
            results["json_valide"] = False
    for bad in case.get("forbid", []):
        results[f"absent:{bad}"] = not re.search(bad, text, re.IGNORECASE)
    results["longueur_ok"] = len(text.split()) <= case["max_words"]
    passed = sum(results.values())
    return {"checks": results, "passed": passed, "total": len(results), "all_ok": passed == len(results)}


def _chat(api_key: str, model: str, prompt: str) -> Dict[str, Any]:
    body = json.dumps({
        "model": model, "temperature": 0, "max_tokens": 400, "usage": {"include": True},
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions", data=body, method="POST",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    started = time.monotonic()
    with urllib.request.urlopen(req, timeout=90) as resp:  # noqa: S310 - URL https constante
        data = json.loads(resp.read().decode("utf-8"))
    return {"latency_s": round(time.monotonic() - started, 2), "data": data}


def cmd_evaluate(args: argparse.Namespace) -> int:
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        print("NON EXECUTE: OPENROUTER_API_KEY absente de l'environnement (emplacement: .env hôte).")
        return 2
    plugin = load_plugin_package()
    policy = sys.modules[f"{plugin.__name__}.policy"].load_policy(POLICY_PATH)
    report: Dict[str, Any] = {
        "executed_at": datetime.now(timezone.utc).isoformat(), "protocol": "docs/3_Technique/evaluation_modeles_KAN-127.md",
        "temperature": 0, "runs_per_case": 1, "models": {},
    }
    for model in policy.evaluation_candidates:
        rows = []
        for case in EVAL_CASES:
            try:
                out = _chat(api_key, model, case["prompt"])
                msg = (out["data"].get("choices") or [{}])[0].get("message", {}).get("content") or ""
                usage = out["data"].get("usage") or {}
                rows.append({"case": case["id"], "latency_s": out["latency_s"], "cost_usd": usage.get("cost"),
                             "tokens": usage.get("total_tokens"), "score": _score(case, msg)})
            except (urllib.error.URLError, ValueError, TimeoutError) as exc:
                rows.append({"case": case["id"], "error": type(exc).__name__})
        ok = sum(1 for r in rows if r.get("score", {}).get("all_ok"))
        report["models"][model] = {"cases_passed": ok, "cases_total": len(rows), "rows": rows}
        print(f"{model}: {ok}/{len(rows)} cas réussis")
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"RESULT: rapport écrit dans {args.output}")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("validate").set_defaults(fn=cmd_validate)
    sub.add_parser("simulate-cap").set_defaults(fn=cmd_simulate_cap)
    sub.add_parser("simulate-fallback").set_defaults(fn=cmd_simulate_fallback)
    ev = sub.add_parser("evaluate")
    ev.add_argument("--output", default=str(REPO / "docs" / "3_Technique" / "evaluation_modeles_KAN-127_resultats.json"))
    ev.set_defaults(fn=cmd_evaluate)
    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
