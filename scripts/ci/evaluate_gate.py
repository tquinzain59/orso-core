#!/usr/bin/env python3
"""Evaluate workflow job results for the final aggregation gate (All required checks pass).

Fails closed:
- Exits 1 if any job was cancelled (prevents empty green / 'vert vide').
- Exits 1 if any job failed.
- Exits 1 if zero checks were executed (empty run).
- Exits 0 only if all executed jobs succeeded and at least one check ran.

Outputs:
- Emits ``needs-json={...}`` to ``$GITHUB_OUTPUT`` for downstream summary/comment tools.
- Writes structured markdown report to ``$GITHUB_STEP_SUMMARY``.
- Prints full accounting of executed, skipped, and cancelled controls to stdout.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, List, Tuple


def evaluate_needs(needs_data: Dict[str, Any]) -> Tuple[int, Dict[str, Any], List[str]]:
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

    log_lines: List[str] = []
    log_lines.append("=== All Required Checks Pass — Evaluation ===")
    for name in sorted(compact.keys()):
        res = compact[name]
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
        log_lines.append(f"{icon} {name}: {res}")

    log_lines.append("==============================================")
    log_lines.append(f"Total controls : {total_count}")
    log_lines.append(
        f"Executed       : {executed_count} ({success_count} success, {failure_count} failure)"
    )
    log_lines.append(f"Skipped        : {skipped_count}")
    log_lines.append(f"Cancelled      : {cancelled_count}")
    if other_jobs:
        log_lines.append(f"Other/Unknown  : {other_count} ({', '.join(other_jobs)})")

    # Gate rules:
    has_cancellation = cancelled_count > 0
    has_failure = failure_count > 0
    is_empty_run = executed_count == 0
    has_unknown = other_count > 0

    metrics = {
        "compact": compact,
        "total": total_count,
        "executed": executed_count,
        "success": success_count,
        "failure": failure_count,
        "cancelled": cancelled_count,
        "skipped": skipped_count,
        "other": other_count,
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
    if has_unknown:
        log_lines.append(
            f"::error::Gate failed: {other_count} job(s) have unknown status: {', '.join(other_jobs)}"
        )

    if not has_cancellation and not has_failure and not is_empty_run and not has_unknown:
        verdict = f"Verdict: PASS — {executed_count} executed ({success_count} success, 0 failure), {skipped_count} skipped, 0 cancelled"
        log_lines.append(verdict)
        return 0, metrics, log_lines

    verdict = (
        f"Verdict: FAIL — {failure_count} failure(s), {cancelled_count} cancelled, "
        f"{executed_count} executed, {skipped_count} skipped"
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
        "",
    ])

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
    raw_input = ""
    if not sys.stdin.isatty():
        raw_input = sys.stdin.read().strip()
    if not raw_input and "NEEDS" in os.environ:
        raw_input = os.environ["NEEDS"].strip()
    if not raw_input and len(sys.argv) > 1:
        raw_input = sys.argv[1].strip()

    if not raw_input:
        print("::error::No needs JSON provided to evaluate_gate.py", file=sys.stderr)
        return 1

    try:
        needs_data = json.loads(raw_input)
    except json.JSONDecodeError as err:
        print(f"::error::Failed to parse needs JSON: {err}", file=sys.stderr)
        return 1

    exit_code, metrics, log_lines = evaluate_needs(needs_data)

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
