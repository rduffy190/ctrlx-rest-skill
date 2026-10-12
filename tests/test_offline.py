"""Offline regression test for dl.py and motion_axes.py against mock_ctrlx.py (no controller needed).

Starts the mock over HTTPS with a throwaway self-signed cert, points CTRLX_HOST at it, and runs the
scripts as a user would. Run by tests/run.sh.
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import ssl

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(HERE, "..", "scripts")
SPEC = os.path.join(HERE, "..", "references", "examples", "press_axes.json")
fails = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  [{detail}]"))
    if not cond:
        fails.append(name)


tmp = tempfile.mkdtemp()
cert, key = os.path.join(tmp, "c.pem"), os.path.join(tmp, "k.pem")
subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", key, "-out", cert,
                "-days", "1", "-subj", "/CN=127.0.0.1"], check=True, capture_output=True)
with socket.socket() as s:
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
mock = subprocess.Popen([sys.executable, "-I", os.path.join(HERE, "mock_ctrlx.py"), str(port), cert, key],
                        stdout=subprocess.PIPE, text=True)
assert mock.stdout.readline().strip() == "ready"
env = dict(os.environ, CTRLX_HOST=f"127.0.0.1:{port}", CTRLX_USER="boschrexroth", CTRLX_PASS="boschrexroth")


def run(script, *args, ok=True):
    r = subprocess.run([sys.executable, "-I", os.path.join(SCRIPTS, script), *args], env=env,
                       capture_output=True, text=True, timeout=60)
    if ok and r.returncode != 0:
        print(r.stdout, r.stderr)
    return r


def dl(*args, ok=True):
    return run("dl.py", *args, ok=ok)


def log():
    ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
    return json.load(urllib.request.urlopen(f"https://127.0.0.1:{port}/__log", context=ctx))


try:
    # dl.py basics
    r = dl("token")
    check("token: bearer token from identity-manager", r.stdout.strip() == "mock-token", r.stdout)
    r = dl("browse", "/")
    check("browse root", json.loads(r.stdout)["value"] == ["motion", "system"], r.stdout)
    r = dl("read", "system/info/name")
    check("read", json.loads(r.stdout)["value"] == "MockCore", r.stdout)
    r = dl("meta", "motion/axs")
    check("metadata: createType string", "types/datalayer/string" in r.stdout)
    r = dl("write", "system/info/name", "string", '"Renamed"')
    check("write (PUT)", json.loads(r.stdout)["value"] == "Renamed")
    r = dl("bulk", "system/info/name", "no/such/node")
    res = json.loads(r.stdout)
    check("bulk: per-entry results", res[0]["result"] == "DL_OK" and res[1]["result"] == "DL_INVALID_ADDRESS", res)
    r = dl("read", "no/such/node", ok=False)
    check("error: exits non-zero with the Problem JSON", r.returncode != 0 and "DL_INVALID_ADDRESS" in r.stderr
          and "HTTP 404 on GET no/such/node" in r.stderr, r.stderr)
    r = dl("rtmap", "motion/realtime/cyclicStatusData")
    lines = r.stdout.splitlines()
    check("rtmap: sorted by offset, revision and size", "revision 7" in lines[0] and "sizeBytes 9" in lines[0]
          and "Ax/pos" in lines[2] and "Ax/flag" in lines[3], r.stdout)
    r = dl("rtdata", "motion/realtime/cyclicStatusData")
    check("rtdata: decodes LREAL and bool8", "12.5" in r.stdout and "True" in r.stdout, r.stdout)

    # create / delete
    r = dl("create", "motion/axs", "string", '"Tmp1"')
    check("create (POST) an axis", json.loads(r.stdout)["responseType"] == "create")
    r = dl("delete", "motion/axs/Tmp1")
    check("delete", r.returncode == 0 and "Tmp1" not in json.loads(dl("browse", "motion/axs").stdout)["value"])

    # motion_axes.py: plan writes nothing
    before = len(log())
    r = run("motion_axes.py", "plan", SPEC)
    writes = [e for e in log()[before:] if e["method"] != "GET" and "auth/token" not in e["path"]]
    check("plan: lists CREATE for all 4 axes", r.stdout.count("CREATE  ") == 4, r.stdout)
    check("plan: no writes reach the controller", writes == [], writes)

    # apply --save
    r = run("motion_axes.py", "apply", SPEC, "--save")
    check("apply: succeeded", r.returncode == 0, r.stderr)
    axes = json.loads(dl("browse", "motion/axs").stdout)["value"]
    check("apply: 4 axes created", axes == ["BeamLift", "BeamTransfer", "PressA", "PressB"], axes)
    cfg = json.loads(dl("read", "motion/axs/BeamTransfer/cfg").stdout)["value"]
    lim = cfg["limits"]
    check("apply: limits written with their units", lim["posMax"] == 1050 and lim["velPos"] == 1000
          and lim["velPosUnit"] == "mm/s" and lim["accUnit"] == "mm/s^2", lim)
    units = {u["valueType"]: u["abbreviation"] for u in cfg["units"]["default"]}
    check("apply: default units set", units == {"position+length": "mm", "velocity": "mm/s",
                                                "acceleration": "mm/s^2", "jerk": "mm/s^3"}, units)
    order = [e["path"].rsplit("/", 1)[-1] for e in log() if e["method"] == "PUT" and "/BeamLift/cfg/" in e["path"]]
    check("apply: properties written before units and limits", order[:3] == ["properties", "units", "lim"], order)
    check("apply --save: saved through the Solutions task, nothing unsaved",
          json.loads(dl("read", "motion/cfg/unsaved").stdout)["value"] is False
          and any(e["path"] == "/solutions/api/v1/tasks" for e in log()))
    check("show: table lists the axes as virtual", "BeamLift" in r.stdout and "(virtual)" in r.stdout, r.stdout)

    # re-plan: everything is an UPDATE now
    r = run("motion_axes.py", "plan", SPEC)
    check("plan after apply: UPDATE only", r.stdout.count("UPDATE  ") == 4 and "CREATE" not in r.stdout)

    # axis profile: written to cfg/axisprofile (not cfg/axisProfileName), and only when it changes
    prof = os.path.join(tmp, "prof.json")
    lim1 = {"posMin": 0, "posMax": 1, "vel": 1, "acc": 1}
    json.dump({"axes": {"BeamLift": {"axisProfileName": "", "limits": lim1}}}, open(prof, "w"))
    before = len(log())
    r = run("motion_axes.py", "apply", prof)
    puts = [e["path"] for e in log()[before:] if e["method"] == "PUT"]
    check("profile: unchanged value is not written", r.returncode == 0 and not any("axisprofile" in p.lower()
          for p in puts) and "not written" in r.stdout, (r.stderr, puts))
    json.dump({"axes": {"BeamLift": {"axisProfileName": "MockDrive", "limits": lim1}}}, open(prof, "w"))
    before = len(log())
    r = run("motion_axes.py", "apply", prof)
    puts = [e["path"] for e in log()[before:] if e["method"] == "PUT"]
    check("profile: changed value written to cfg/axisprofile", r.returncode == 0
          and "/automation/api/v2/nodes/motion/axs/BeamLift/cfg/axisprofile" in puts
          and json.loads(dl("read", "motion/axs/BeamLift/cfg").stdout)["value"]["axisProfileName"] == "MockDrive",
          (r.stderr, puts))

    # name validation
    bad = os.path.join(tmp, "bad.json")
    json.dump({"axes": {"Bad-Name": {"limits": {"posMin": 0, "posMax": 1, "vel": 1, "acc": 1}}}}, open(bad, "w"))
    r = run("motion_axes.py", "plan", bad, ok=False)
    check("spec: invalid axis name rejected", r.returncode != 0 and "bad axis name" in r.stderr, r.stderr)

    # the per-axis save node really does reject an empty parameter (why dl.py save exists)
    r = dl("create", "motion/axs/BeamLift/cfg/save", "object", "{}", ok=False)
    check("per-axis cfg/save rejects empty param (500 Invalid parameter)", r.returncode != 0 and "Invalid parameter" in r.stderr)

    # dl.py save
    dl("write", "system/info/name", "string", '"x"')
    r = dl("save", "regression test")
    check("save: Solutions task with the active solution/configuration",
          json.loads(r.stdout)["configuration"] == "appdata")
    task = [e for e in log() if e["path"] == "/solutions/api/v1/tasks"][-1]["body"]
    check("save: comment passed through", task["properties"]["comment"] == "regression test", task)
finally:
    mock.terminate()

sys.exit(1 if fails else 0)
