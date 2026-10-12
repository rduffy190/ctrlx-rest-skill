#!/usr/bin/env python3
"""Create and configure ctrlX MOTION axes from a JSON spec (stdlib only, uses dl.py).

Usage:
  motion_axes.py show                       table of all axes: type, profile, limits, units
  motion_axes.py plan  <spec.json>          print what apply would change (no writes)
  motion_axes.py apply <spec.json> [--save] create missing axes, write properties/units/limits
                                            (and the axis profile if given); --save then saves
                                            the active configuration so it survives reboot

Spec (see references/examples/press_axes.json):
  {"units": {"position+length": "mm", "velocity": "mm/s", "acceleration": "mm/s^2", "jerk": "mm/s^3"},
   "axes": {"Ax1": {"type": "LINEAR", "modulo": false, "moduloValue": 0,
                    "axisProfileName": "",            # optional; "" = virtual axis
                    "units": {...},                     # optional per-axis override
                    "limits": {"posMin": -5, "posMax": 150, "vel": 200, "acc": 2000,
                               "dec": 2000, "jerk": 0}}}}
  Limits are in the axis' units. vel sets velPos and velNeg (or give velPos/velNeg);
  jerk sets jrkAcc and jrkDec. Torque limits are left untouched.

Rules from the Motion manual (4.1.5/4.1.6/4.1.9):
  - creating/deleting axes needs motion state CONFIGURATION (ctrlX OS in SETUP);
  - names: max 16 chars, [A-Za-z0-9_], unique across axes and kinematics.
    PLC AXIS_REF.AxisName is STRING(15), so keep names <= 15 for PLC use;
  - changing LINEAR <-> ROTATIONAL resets the axis units and limits, so properties are written first;
  - the axis profile reference can only change in SETUP.

Axis profile: the spec key is "axisProfileName" (the field name in the cfg struct), but the writable node
differs by Motion version: cfg/axisprofile (e.g. RM26) or cfg/axisProfileName (older). apply browses the
axis' cfg to find it, and skips the write when the value is already right (it is SETUP-only).
"""
import importlib.util
import json
import os
import re
import sys

_spec = importlib.util.spec_from_file_location("dl", os.path.join(os.path.dirname(os.path.abspath(__file__)), "dl.py"))
dl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dl)
call = dl.call

NAME_RE = re.compile(r"^[A-Za-z0-9_]{1,16}$")
UNIT_FIELDS = {"posMinUnit": "position+length", "posMaxUnit": "position+length",
               "velPosUnit": "velocity", "velNegUnit": "velocity",
               "accUnit": "acceleration", "decUnit": "acceleration",
               "jrkAccUnit": "jerk", "jrkDecUnit": "jerk"}


def axes():
    return call("GET", "motion/axs", {"type": "browse"})["value"]


def show():
    print(f"motion state: {call('GET', 'motion/state/opstate')['value']}   "
          f"unsaved: {call('GET', 'motion/cfg/unsaved')['value']}")
    for n in axes():
        c = call("GET", f"motion/axs/{n}/cfg")["value"]
        l, p = c["limits"], c["properties"]
        prof = c.get("axisProfileName") or "(virtual)"
        print(f"{n:16s} {p['axsType']:<10} mod={str(p['modulo'])[0]} {prof:<12} "
              f"pos {l['posMin']}..{l['posMax']} {l['posMinUnit']}  "
              f"vel +{l['velPos']}/-{l['velNeg']} {l['velPosUnit']}  "
              f"acc {l['acc']} dec {l['dec']} {l['accUnit']}  jrk {l['jrkAcc']}/{l['jrkDec']} {l['jrkAccUnit']}")


PROFILE_NODES = ("axisprofile", "axisProfileName")   # newer Motion versions first


def profile_node(name):
    """Path of the writable axis-profile node of an axis; its name depends on the Motion version."""
    children = call("GET", f"motion/axs/{name}/cfg", {"type": "browse"})["value"]
    for n in PROFILE_NODES:
        if n in children:
            return f"motion/axs/{name}/cfg/{n}"
    sys.exit(f"{name}: no axis profile node under cfg (looked for {', '.join(PROFILE_NODES)}; found {children})")


def write_profile(name, body):
    current = call("GET", f"motion/axs/{name}/cfg")["value"].get("axisProfileName", "")
    if current == body["value"]:
        print(f"   axis profile already {body['value']!r}, not written")
        return
    call("PUT", profile_node(name), body=body)


def build(spec):
    """Return [(name, list of (method, path, body))] for every axis in the spec."""
    out = []
    default_units = spec.get("units", {})
    for name, a in spec["axes"].items():
        if not NAME_RE.match(name):
            sys.exit(f"bad axis name {name!r}: max 16 chars of [A-Za-z0-9_]")
        if len(name) > 15:
            print(f"WARNING: {name} is 16 chars; PLC AXIS_REF.AxisName is STRING(15)")
        units = {**default_units, **a.get("units", {})}
        lim = a["limits"]
        ops = []
        props = {"axsType": a.get("type", "LINEAR"), "modulo": a.get("modulo", False)}
        if props["modulo"]:
            props["moduloValue"] = a["moduloValue"]
        ops.append(("PUT", f"motion/axs/{name}/cfg/properties", {"type": "object", "value": props}))
        if units:
            ops.append(("PUT", f"motion/axs/{name}/cfg/units", {"type": "object", "value": {
                "default": [{"valueType": k, "abbreviation": v} for k, v in units.items()]}}))
        limits = {"posMin": lim["posMin"], "posMax": lim["posMax"],
                  "velPos": lim.get("velPos", lim.get("vel")), "velNeg": lim.get("velNeg", lim.get("vel")),
                  "acc": lim["acc"], "dec": lim.get("dec", lim["acc"]),
                  "jrkAcc": lim.get("jrkAcc", lim.get("jerk", 0.0)), "jrkDec": lim.get("jrkDec", lim.get("jerk", 0.0))}
        if None in limits.values():
            sys.exit(f"{name}: limits need posMin, posMax, vel (or velPos/velNeg), acc")
        # Units travel with the values, so they are interpreted correctly whatever the defaults are
        for field, vt in UNIT_FIELDS.items():
            if vt in units:
                limits[field] = units[vt]
        ops.append(("PUT", f"motion/axs/{name}/cfg/lim", {"type": "object", "value": limits}))
        if "axisProfileName" in a:
            # Node resolved at apply time (profile_node); written only if the value differs
            ops.append(("PROFILE", f"motion/axs/{name}/cfg/<profile node>",
                        {"type": "string", "value": a["axisProfileName"]}))
        out.append((name, ops))
    return out


def main(argv):
    if not argv or argv[0] not in ("show", "plan", "apply"):
        sys.exit(__doc__)
    if argv[0] == "show":
        return show()
    spec = json.load(open(argv[1]))
    plan = build(spec)
    existing = axes()
    state = call("GET", "motion/state/opstate")["value"]
    missing = [n for n, _ in plan if n not in existing]
    print(f"motion state: {state}   existing axes: {existing}")
    if missing and state.upper() != "CONFIGURATION":
        print(f"WARNING: creating {missing} needs motion state CONFIGURATION (switch ctrlX OS to SETUP)")
    for name, ops in plan:
        print(("CREATE  " if name in missing else "UPDATE  ") + name)
        for m, p, b in ops:
            print(f"   {m} {p} {json.dumps(b['value'])}")
    if argv[0] == "plan":
        return
    for name, ops in plan:
        if name in missing:
            call("POST", "motion/axs", body={"type": "string", "value": name})
        for m, p, b in ops:
            if m == "PROFILE":
                write_profile(name, b)
            else:
                call(m, p, body=b)
        print(f"written {name}")
    if "--save" in argv:
        r = dl.save_configuration("motion_axes.py: " + ", ".join(n for n, _ in plan))
        print("saved active configuration:", r.get("configuration"), "task", r.get("id"))
    show()


if __name__ == "__main__":
    main(sys.argv[1:])
