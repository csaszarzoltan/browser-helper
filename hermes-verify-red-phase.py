#!/usr/bin/env python3
"""Ad-hoc verification: P2 Condensed Snapshot pre-dev RED tests.

Created with tempfile-safe path pattern.
"""
import subprocess
import sys
import re


def run(kw):
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_core.py", "-k", kw, "--tb=no", "-q", "--no-header"],
        capture_output=True, text=True,
        cwd="/home/zoltan/browser-helper",
    )
    last = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ""
    p = int(re.search(r"(\d+)\s+passed", last).group(1)) if re.search(r"(\d+)\s+passed", last) else 0
    f = int(re.search(r"(\d+)\s+failed", last).group(1)) if re.search(r"(\d+)\s+failed", last) else 0
    s = int(re.search(r"(\d+)\s+skipped", last).group(1)) if re.search(r"(\d+)\s+skipped", last) else 0
    return p, f, s


print("--- Ad-hoc verification: P2 Condensed pre-dev RED phase ---")

p, f, s = run("not Condensed")
ok1 = p == 29 and f == 0
print(f"Existing (k=not Condensed): {p}p {f}f {s}s -> {'OK' if ok1 else 'FAIL'}")

p, f, s = run("Condensed")
ok2 = f == 18 and p == 0
print(f"Condensed (k=Condensed):     {p}p {f}f -> {'OK' if ok2 else 'FAIL'}")

r = subprocess.run(
    [sys.executable, "-m", "pytest", "tests/test_core.py", "-k", "Condensed", "--tb=line", "-q", "--no-header"],
    capture_output=True, text=True,
    cwd="/home/zoltan/browser-helper",
)
ae = r.stdout.count("AttributeError:")
ase = r.stdout.count("AssertionError:")
ok3 = ae > 0 and ase > 0
print(f"Failure types: AttrErr={ae}, AssertErr={ase} -> {'OK' if ok3 else 'FAIL'}")

print(f"--- Verdict: RED phase {'verified' if (ok1 and ok2 and ok3) else 'FAILED'} ---")
