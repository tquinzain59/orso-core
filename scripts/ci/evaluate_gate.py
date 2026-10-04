#!/usr/bin/env python3
"""Evaluate workflow job results for the final aggregation gate (All required checks pass).

Fails closed:
- Exits 1 if any job was cancelled (prevents empty green / 'vert vide').
- Exits 1 if any job failed.
- Exits 1 if zero checks were executed (empty run).
- Exits 1 if any required check was skipped or is missing (closes empty green class, KAN-80 Condition 5).
- Exits 0 only if all executed jobs succeeded, at least one check ran, and all required checks passed.

Outputs:
- Emits ``needs-json={...}`` to ``$GITHUB_OUTPUT`` for downstream summary/comment tools.
- Writes structured markdown report to ``$GITHUB_STEP_SUMMARY``.
- Prints full accounting of executed, skipped, and cancelled controls to stdout.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional, Set, Tuple


LANE_REQUIRED_MAPPINGS: Dict[str, List[str]] = {
    "python": ["tests", "lint", "profile-artifact-check"],
    "frontend": ["js-tests"],
    "rust": ["rust-tests"],
    "site": ["docs-site"],
    "installer": ["installer-tests"],
    "docker_meta": ["docker-lint"],
    "uv_lock": ["uv-lockfile"],
    "npm_lock": ["lockfile-diff"],
}


def derive_required_checks(needs_data: Dict[str, Any], explicit_required: Optional[List[str]] = None) -> List[str]:
    """Derive list of required checks from explicit args, env vars, or detect outputs."""
    reqs: Set[str] = set()

    # 1. Explicit list takes precedence if given
    if explicit_required:
        for r in explicit_required:
            parts = [p.strip() for p in r.split(",") if p.strip()]
            reqs.update(parts)

    # 2. Check environment variable REQUIRED_CHECKS
    env_reqs = os.environ.get("REQUIRED_CHECKS", "").strip()
    if env_reqs:
        for p in env_reqs.split(","):
            if p.strip():
                reqs.add(p.strip())

    # 3. Dynamic deduction based on 'detect' job outputs
    detect_job = needs_data.get("detect")
    if isinstance(detect_job, dict):
        # 'detect' itself is always a required foundation job
        reqs.add("detect")
        outputs = detect_job.get("outputs", {})
        if isinstance(outputs, dict):
            for lane, mapped_jobs in LANE_REQUIRED_MAPPINGS.items():
                if str(outputs.get(lane, "")).lower() == "true":
                    reqs.update(mapped_jobs)

    return sorted(reqs)


def evaluate_needs(
    needs_data: Dict[str, Any],
    required_checks: Optional[List[str]] = None,
) -> Tuple[int, Dict[str, Any], List[str]]:
    """Evaluate job results from the needs dictionary.

    Returns:
        (exit_code, metrics_dict, log_lines)
    """
    compact: Dict[str, str] = {}
    for name, info in needs_data.items():
        if isinstance(info, dict):
            compact[name] = str(info.get("result", "unknown"))
        else:
            compact[name] = str(info)

    success_jobs = [name for name, res in compact.items() if res == "success"]
    failure_jobs = [name for name, res in compact.items() if res == "failure"]
    cancelled_jobs = [name for name, res in compact.items() if res == "cancelled"]
    skipped_jobs = [name for name, res in compact.items() if res == "skipped"]
    other_jobs = [
        name
        for name, res in compact.items()
        if res not in ("success", "failure", "cancelled", "skipped")
    ]

    total_count = len(compact)
    executed_count = len(success_jobs) + len(failure_jobs)
    success_count = len(success_jobs)
    failure_count = len(failure_jobs)
    cancelled_count = len(cancelled_jobs)
    skipped_count = len(skipped_jobs)
    other_count = len(other_jobs)

    # Resolve required checks
    effective_required = derive_required_checks(needs_data, required_checks)
    required_skipped_jobs = [job for job in effective_required if job in skipped_jobs]
    missing_required_jobs = [job for job in effective_required if job not in compact]

    log_lines: List[str] = []
    log_lines.append("=== All Required Checks Pass — Evaluation ===")
    for name in sorted(compact.keys()):
        res = compact[name]
        is_req = name in effective_required
        flag_req = " (REQUIRED)" if is_req else ""
        if res == "success":
            icon = "✅"
        elif res == "failure":
            icon = "❌"
        elif res == "cancelled":
            icon = "🚫"
        elif res == "skipped":
            icon = "⏭️"
        else:
            icon = "⚠️"
        log_lines.append(f"{icon} {name}{flag_req}: {res}")

    log_lines.append("==============================================")
    log_lines.append(f"Total controls : {total_count}")
    log_lines.append(
        f"Executed       : {executed_count} ({success_count} success, {failure_count} failure)"
    )
    log_lines.append(f"Skipped        : {skipped_count}")
    log_lines.append(f"Cancelled      : {cancelled_count}")
    if effective_required:
        log_lines.append(f"Required checks: {len(effective_required)} ({', '.join(effective_required)})")
    if required_skipped_jobs:
        log_lines.append(f"Required SKIPPED: {len(required_skipped_jobs)} ({', '.join(required_skipped_jobs)})")
    if missing_required_jobs:
        log_lines.append(f"Required MISSING: {len(missing_required_jobs)} ({', '.join(missing_required_jobs)})")
    if other_jobs:
        log_lines.append(f"Other/Unknown  : {other_count} ({', '.join(other_jobs)})")

    # Gate rules:
    has_cancellation = cancelled_count > 0
    has_failure = failure_count > 0
    is_empty_run = executed_count == 0
    has_unknown = other_count > 0
    has_required_skipped = len(required_skipped_jobs) > 0
    has_missing_required = len(missing_required_jobs) > 0

    metrics = {
        "compact": compact,
        "total": total_count,
        "executed": executed_count,
        "success": success_count,
        "failure": failure_count,
        "cancelled": cancelled_count,
        "skipped": skipped_count,
        "other": other_count,
        "required": effective_required,
        "required_skipped_jobs": required_skipped_jobs,
        "missing_required_jobs": missing_required_jobs,
        "success_jobs": success_jobs,
        "failure_jobs": failure_jobs,
        "cancelled_jobs": cancelled_jobs,
        "skipped_jobs": skipped_jobs,
        "other_jobs": other_jobs,
    }

    if has_cancellation:
        log_lines.append(
            f"::error::Gate failed: {cancelled_count} job(s) were cancelled: {', '.join(cancelled_jobs)}"
        )
    if has_failure:
        log_lines.append(
            f"::error::Gate failed: {failure_count} job(s) failed: {', '.join(failure_jobs)}"
        )
    if is_empty_run and not has_cancellation and not has_failure:
        log_lines.append("::error::Gate failed: empty run, 0 checks were executed")
    if has_required_skipped:
        log_lines.append(
            f"::error::Gate failed: required check(s) were skipped: {', '.join(required_skipped_jobs)}"
        )
    if has_missing_required:
        log_lines.append(
            f"::error::Gate failed: required check(s) missing from payload: {', '.join(missing_required_jobs)}"
        )
    if has_unknown:
        log_lines.append(
            f"::error::Gate failed: {other_count} job(s) have unknown status: {', '.join(other_jobs)}"
        )

    if (
        not has_cancellation
        and not has_failure
        and not is_empty_run
        and not has_unknown
        and not has_required_skipped
        and not has_missing_required
    ):
        verdict = f"Verdict: PASS — {executed_count} executed ({success_count} success, 0 failure), {skipped_count} skipped, 0 cancelled"
        log_lines.append(verdict)
        return 0, metrics, log_lines

    verdict_reasons = []
    if has_failure:
        verdict_reasons.append(f"{failure_count} failure(s)")
    if has_cancellation:
        verdict_reasons.append(f"{cancelled_count} cancelled")
    if has_required_skipped:
        verdict_reasons.append(f"{len(required_skipped_jobs)} required check(s) skipped")
    if has_missing_required:
        verdict_reasons.append(f"{len(missing_required_jobs)} required check(s) missing")
    if is_empty_run and not has_failure and not has_cancellation:
        verdict_reasons.append("empty run")
    if has_unknown:
        verdict_reasons.append(f"{other_count} unknown")

    reason_str = ", ".join(verdict_reasons)
    verdict = (
        f"Verdict: FAIL ({reason_str}) — {executed_count} executed, {skipped_count} skipped"
    )
    log_lines.append(verdict)
    return 1, metrics, log_lines


def write_step_summary(metrics: Dict[str, Any], exit_code: int, summary_path: str) -> None:
    """Write markdown summary to GITHUB_STEP_SUMMARY."""
    lines: List[str] = [
        "## Aggregated Gate Verdict: All Required Checks Pass",
        "",
    ]
    if exit_code == 0:
        lines.append(
            f"✅ **PASS** — Tous les contrôles requis ont été validés "
            f"({metrics['executed']} exécutés, {metrics['skipped']} sautés)."
        )
    elif metrics["cancelled"] > 0:
        lines.append(
            f"🚫 **ÉCHEC (ANNULÉ)** — Exécution incomplète : {metrics['cancelled']} contrôle(s) "
            f"annulé(s). La porte refuse formellement de valider un vert vide."
        )
    elif metrics.get("required_skipped_jobs"):
        lines.append(
            f"⚠️ **ÉCHEC (CONTRÔLE REQUIS SAUTÉ)** — La porte refuse formellement le verdict : "
            f"{len(metrics['required_skipped_jobs'])} contrôle(s) requis ont été sautés : "
            f"`{', '.join(sorted(metrics['required_skipped_jobs']))}`."
        )
    elif metrics.get("missing_required_jobs"):
        lines.append(
            f"⚠️ **ÉCHEC (CONTRÔLE REQUIS MANQUANT)** — Contrôle(s) requis introuvable(s) : "
            f"`{', '.join(sorted(metrics['missing_required_jobs']))}`."
        )
    elif metrics["failure"] > 0:
        lines.append(
            f"❌ **ÉCHEC** — {metrics['failure']} contrôle(s) en échec."
        )
    elif metrics["executed"] == 0:
        lines.append(
            "❌ **ÉCHEC (RUN VIDE)** — 0 contrôle exécuté. Aucune validation effective."
        )
    else:
        lines.append("❌ **ÉCHEC** — Statut indéterminé.")

    lines.extend([
        "",
        "| Métrique | Valeur |",
        "| :--- | :--- |",
        f"| **Total contrôles évalués** | {metrics['total']} |",
        f"| **Contrôles exécutés** | {metrics['executed']} ({metrics['success']} ✅ / {metrics['failure']} ❌) |",
        f"| **Contrôles sautés (gated)** | {metrics['skipped']} ⏭️ |",
        f"| **Contrôles annulés** | {metrics['cancelled']} 🚫 |",
        f"| **Contrôles requis** | {len(metrics['required'])} ({', '.join(sorted(metrics['required'])) or 'aucun'}) |",
        "",
    ])

    if metrics.get("required_skipped_jobs"):
        lines.append(f"**Contrôles requis sautés :** `{', '.join(sorted(metrics['required_skipped_jobs']))}`\n")
    if metrics.get("missing_required_jobs"):
        lines.append(f"**Contrôles requis manquants :** `{', '.join(sorted(metrics['missing_required_jobs']))}`\n")
    if metrics["cancelled_jobs"]:
        lines.append(f"**Contrôles annulés :** `{', '.join(sorted(metrics['cancelled_jobs']))}`\n")
    if metrics["failure_jobs"]:
        lines.append(f"**Contrôles en échec :** `{', '.join(sorted(metrics['failure_jobs']))}`\n")

    try:
        with open(summary_path, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except OSError as err:
        print(f"::warning::Unable to write to GITHUB_STEP_SUMMARY: {err}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate GitHub Actions needs object for gate job.")
    parser.add_argument(
        "--required",
        "-r",
        help="Comma-separated list of required checks (e.g. 'detect,tests,lint')",
        default=None,
    )
    args, unknown = parser.parse_known_args()

    raw_input = ""
    if not sys.stdin.isatty():
        raw_input = sys.stdin.read().strip()
    if not raw_input and "NEEDS" in os.environ:
        raw_input = os.environ["NEEDS"].strip()
    if not raw_input and unknown:
        raw_input = unknown[0].strip()

    if not raw_input:
        print("::error::No needs JSON provided to evaluate_gate.py", file=sys.stderr)
        return 1

    try:
        needs_data = json.loads(raw_input)
    except json.JSONDecodeError as err:
        print(f"::error::Failed to parse needs JSON: {err}", file=sys.stderr)
        return 1

    required_list = [c.strip() for c in args.required.split(",") if c.strip()] if args.required else None
    exit_code, metrics, log_lines = evaluate_needs(needs_data, required_checks=required_list)

    for line in log_lines:
        print(line)

    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        compact_json = json.dumps(metrics["compact"])
        try:
            with open(github_output, "a", encoding="utf-8") as f:
                f.write(f"needs-json={compact_json}\n")
        except OSError as err:
            print(f"::warning::Unable to write to GITHUB_OUTPUT: {err}", file=sys.stderr)

    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        write_step_summary(metrics, exit_code, step_summary)

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
