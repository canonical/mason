#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml"]
# ///
"""hygiene: the mean of the SDF style and format checks, as one score.

they rarely fail and say little about whether a slice is right, so they get one
vote in a pair's mean instead of one each. each check is still its own
scorer_<name>.py, run here; the ones that missed are listed after the score."""
import subprocess
import sys
from pathlib import Path

CHECKS = (
    "paths-sorted",
    "copyright-path-present",
    "arch-format",
    "no-man-pages",
    "no-doc-clutter",
    "no-shell-completions",
    "mutable-has-text",
    "slice-names-canonical",
    "v3-essential-format-compat",
    "essential-map-format-compat",
    "hint-format-compat",
    "prefer-format-compat",
    "essential-list-on-v1",
)


def main() -> None:
    here = Path(__file__).resolve().parent
    scores, missed = [], []
    for name in CHECKS:
        r = subprocess.run([sys.executable, str(here / f"scorer_{name}.py")], capture_output=True, text=True, check=False)
        first = r.stdout.split("\n", 1)[0].strip()
        if r.returncode != 0 or not first:
            sys.exit(f"hygiene: {name} failed: {r.stderr.strip()}")
        if first == "na":
            continue
        v = float(first)
        scores.append(v)
        if v < 1.0:
            missed.append(f"{name} {v:.2f}")
    print(f"{sum(scores) / len(scores):.4f}" if scores else "na")
    for m in missed:
        print(m)


main()
