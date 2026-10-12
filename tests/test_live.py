"""Live, READ-ONLY smoke test against a real controller (CTRLX_HOST, required).

Nothing is written: only GETs, a bulk read, and 'motion_axes.py show/plan' (plan never writes).
Run with: tests/run.sh --live
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(HERE, "..", "scripts")
fails = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  [{detail}]"))
    if not cond:
        fails.append(name)


def run(script, *args):
    return subprocess.run([sys.executable, "-I", os.path.join(SCRIPTS, script), *args],
                          capture_output=True, text=True, timeout=60)


r = run("dl.py", "browse", "/")
check("browse root reaches the controller", r.returncode == 0 and "motion" in r.stdout, r.stderr[:300])
if fails:
    sys.exit(1)
state = json.loads(run("dl.py", "read", "motion/state/opstate").stdout)["value"]
check("motion state readable", state in ("Configuration", "Running", "Error", "Booting"), state)
axes = json.loads(run("dl.py", "browse", "motion/axs").stdout)["value"]
print(f"     controller has {len(axes)} axes: {axes}, motion {state}")
r = run("dl.py", "bulk", "motion/state/opstate", "motion/cfg/unsaved")
check("bulk read", r.returncode == 0 and all(e["result"] == "DL_OK" for e in json.loads(r.stdout)), r.stdout[:300])
r = run("motion_axes.py", "show")
check("motion_axes show", r.returncode == 0 and all(a in r.stdout for a in axes), r.stderr[:300])
r = run("motion_axes.py", "plan", os.path.join(HERE, "..", "references", "examples", "press_axes.json"))
check("motion_axes plan (no writes)", r.returncode == 0 and ("CREATE" in r.stdout or "UPDATE" in r.stdout), r.stderr[:300])
r = run("dl.py", "read", "motion/axs/__no_such_axis__/cfg")
check("errors come back as Problem JSON", r.returncode != 0 and "DL_INVALID_ADDRESS" in r.stderr, r.stderr[:300])
sys.exit(1 if fails else 0)
