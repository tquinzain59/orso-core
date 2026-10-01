#!/usr/bin/env python3
"""Runner infrastructure guard for orso-core (KAN-67).

Ensures all jobs in GitHub Actions run on available, supported runners
(ubuntu-latest, macos-latest, windows-latest) and explicitly fails if
any job requests unavailable larger runners (e.g. *-core) or unsupported
runner tiers.

Usage:
  # Scan all workflows in .github/workflows
  python3 scripts/ci/check_runner_guard.py --scan-workflows

  # Probe a specific runner label
  python3 scripts/ci/check_runner_guard.py --check-runner ubuntu-latest-96-core
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

# Supported standard runners available on the repository's account tier
ALLOWED_RUNNERS = {
    "ubuntu-latest",
    "macos-latest",
    "windows-latest",
    "ubuntu-24.04-arm",
}

# Explicitly banned larger / paid-tier runner patterns that cause indefinite queues
BANNED_PATTERNS = [
    r".*-core$",  # ubuntu-latest-96-core, ubuntu-latest-32-core, windows-latest-32-core, etc.
    r".*-arm-core$",
]


def check_runner_label(runner: str) -> bool:
    """Return True if runner label is permitted, False if unavailable."""
    runner = runner.strip().strip("'\"")
    for pattern in BANNED_PATTERNS:
        if re.match(pattern, runner):
            return False
    if runner.startswith("${{") and runner.endswith("}}"):
        # Matrix/dynamic variable expression, evaluated at runtime
        return True
    return runner in ALLOWED_RUNNERS


def scan_workflows(workflows_dir: Path) -> list[tuple[str, int, str]]:
    """Scan all YAML workflows for runs-on or runner matrix declarations.
    
    Returns list of (file_path, line_number, runner_label) for violations.
    """
    violations = []
    runs_on_regex = re.compile(r"^\s*(?:runs-on|runner):\s*(.*)$")
    
    for yml_file in sorted(workflows_dir.glob("*.y*ml")):
        try:
            content = yml_file.read_text(encoding="utf-8")
        except Exception as exc:
            print(f"Warning: could not read {yml_file}: {exc}", file=sys.stderr)
            continue
            
        for line_no, line in enumerate(content.splitlines(), 1):
            match = runs_on_regex.search(line)
            if match:
                raw_val = match.group(1).split("#")[0].strip().strip("'\"")
                if raw_val and not check_runner_label(raw_val):
                    violations.append((str(yml_file), line_no, raw_val))
                    
    return violations


def main() -> int:
    parser = argparse.ArgumentParser(description="Guard against unavailable CI runners.")
    parser.add_argument("--scan-workflows", action="store_true", help="Scan .github/workflows for unauthorized runners")
    parser.add_argument("--check-runner", type=str, help="Validate a specific runner label")
    parser.add_argument("--workflows-dir", type=str, default=".github/workflows", help="Workflows directory")
    args = parser.parse_args()

    if args.check_runner:
        runner = args.check_runner.strip()
        if not check_runner_label(runner):
            print(
                f"[ERROR] Runner '{runner}' is unavailable on this repository infrastructure.\n"
                f"Permitted runners: {', '.join(sorted(ALLOWED_RUNNERS))}.\n"
                f"Aborting execution to prevent indefinite queue hang.",
                file=sys.stderr,
            )
            return 1
        print(f"[OK] Runner '{runner}' is verified and available.")
        return 0

    # Default to scanning workflows
    workflows_path = Path(args.workflows_dir)
    if not workflows_path.exists():
        print(f"[ERROR] Workflows directory not found: {workflows_path}", file=sys.stderr)
        return 1

    violations = scan_workflows(workflows_path)
    if violations:
        print("[ERROR] Found unavailable runner declarations in CI workflows:", file=sys.stderr)
        for path, line_no, label in violations:
            print(f"  - {path}:{line_no} requests unavailable runner '{label}'", file=sys.stderr)
        print(
            f"\nPermitted runners: {', '.join(sorted(ALLOWED_RUNNERS))}.\n"
            f"Jobs with unavailable runners remain queued indefinitely and block all runs.",
            file=sys.stderr,
        )
        return 1

    print(f"[OK] All workflow runner declarations verified ({workflows_path}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
