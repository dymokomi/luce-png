#!/usr/bin/env python3
"""Build and run luce-png's test blocks in native and C modes."""
import os, subprocess
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT.parent / "luce-base/build/luce-base"
MODES = [["--native"], ["--backend=c"]]
env = dict(os.environ, LUCE_BASE=str(BASE.resolve()), LUCE_STD=str((ROOT.parent / "luce-base/src/std").resolve()))
for source in ["src/luce_png/png.lucb"]:
    for flags in MODES:
        subprocess.run([str(BASE.resolve()), "test", str(ROOT / source), *flags], env=env, check=True, timeout=300, cwd=ROOT)
print("PASS luce-png")
