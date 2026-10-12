#!/usr/bin/env python3
"""ctrlX Data Layer REST client (stdlib only).

Usage:
  dl.py read     <path>                 read a node (JSON: type/value)
  dl.py browse   <path>                 list child nodes ('/' for root)
  dl.py meta     <path>                 metadata (node class, allowed ops, readType reference)
  dl.py type     <type-path>            type definition, e.g. types/datalayer/memory_map
  dl.py write    <path> <type> <json>   write a value (PUT), e.g. write foo/bar int32 5
  dl.py create   <path> <type> <json>   create a node / execute a method (POST),
                                        e.g. create motion/axs string '"Ax1"'
  dl.py delete   <path>                 delete a node (DELETE)
  dl.py save     [comment]              save the ACTIVE configuration (Solutions app) so
                                        Data Layer config changes (motion, scheduler...) survive reboot
  dl.py bulk     <path> [<path> ...]    bulk read several nodes in one request
  dl.py rtmap    <rt-node>              decode an RT memory map (sorted by offset) + revision + size
  dl.py rtdata   <rt-node>              read the RT buffer and decode it with its map
  dl.py nodesrt                         list all RT (memory) nodes
  dl.py token                           print a bearer token (for curl)

Connection (env vars):
  CTRLX_HOST  host[:port]  default 192.168.10.130:8443
  CTRLX_USER / CTRLX_PASS  default boschrexroth / boschrexroth (factory default)

Self-signed certificates are accepted (ctrlX ships with one).
"""
import json
import os
import ssl
import struct
import sys
import urllib.error
import urllib.parse
import urllib.request

HOST = os.environ.get("CTRLX_HOST", "192.168.10.130:8443")
USER = os.environ.get("CTRLX_USER", "boschrexroth")
PASS = os.environ.get("CTRLX_PASS", "boschrexroth")
BASE = f"https://{HOST}"
API = f"{BASE}/automation/api/v2"
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

_token = None


def token():
    global _token
    if _token is None:
        body = json.dumps({"name": USER, "password": PASS}).encode()
        req = urllib.request.Request(f"{BASE}/identity-manager/api/v1.0/auth/token", body,
                                     {"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, context=CTX, timeout=10) as r:
            _token = json.load(r)["access_token"]
    return _token


def call(method, path, query=None, body=None):
    url = f"{API}/nodes/{urllib.parse.quote(path.strip('/'), safe='/')}"
    if query:
        url += "?" + urllib.parse.urlencode(query)
    return http(method, url, body, label=f"{method} {path}")


def http(method, url, body=None, label=None, timeout=15):
    """Authenticated JSON request to any ctrlX REST URL (exits with the Problem JSON on error)."""
    label = label or f"{method} {url}"
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Authorization": f"Bearer {token()}"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data, headers, method=method)
    try:
        with urllib.request.urlopen(req, context=CTX, timeout=timeout) as r:
            raw = r.read()
            return json.loads(raw) if raw else {"status": r.status}
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            problem = json.loads(raw)
        except ValueError:
            problem = raw.decode(errors="replace")
        sys.exit(f"HTTP {e.code} on {label}: {json.dumps(problem)}")


def active_configuration():
    """(solution, configuration) that is currently active, e.g. ('DefaultSolution', 'appdata')."""
    for sol in http("GET", f"{BASE}/solutions/api/v1/solutions"):
        if sol.get("active"):
            for cfg in http("GET", f"{BASE}/solutions/api/v1/solutions/{sol['name']}/configurations"):
                if cfg.get("active"):
                    return sol["name"], cfg["name"]
    sys.exit("no active solution/configuration found")


def save_configuration(comment=""):
    """Save the active configuration through the Solutions app (all apps: motion, scheduler, PLC...).
    This is what the web UI 'Save' does. The per-object save nodes (motion/axs/<ax>/cfg/save,
    motion/admin/cfg/make-persistent/<ax>) need a persistence_param with a configurationPath and
    reject an empty one with 'Invalid parameter' (090F0054 / 0C570101)."""
    sol, cfg = active_configuration()
    body = {"action": "save", "properties": {"solution": sol, "configuration": cfg, "comment": comment}}
    return http("POST", f"{BASE}/solutions/api/v1/tasks", body, timeout=120)


# Data Layer RT types -> struct format (little-endian)
FMT = {"bool8": "?", "int8": "b", "uint8": "B", "int16": "h", "uint16": "H", "int32": "i",
       "uint32": "I", "int64": "q", "uint64": "Q", "float32": "f", "float64": "d"}


def rtmap(node):
    m = call("GET", f"{node}/map")["value"]
    info = call("GET", f"{node}/info")["value"]
    variables = sorted(m["variables"], key=lambda v: v["bitoffset"])
    return m["revision"], info.get("sizeBytes"), variables


def main(argv):
    if len(argv) < 1:
        sys.exit(__doc__)
    cmd, args = argv[0], argv[1:]
    out = None
    if cmd == "read":
        out = call("GET", args[0])
    elif cmd == "browse":
        out = call("GET", args[0], {"type": "browse"})
    elif cmd == "meta":
        out = call("GET", args[0], {"type": "metadata"})
    elif cmd == "type":
        p = args[0]
        out = call("GET", p if p.startswith("types/") else f"types/{p}")
    elif cmd == "write":
        out = call("PUT", args[0], body={"type": args[1], "value": json.loads(args[2])})
    elif cmd == "create":
        out = call("POST", args[0], body={"type": args[1], "value": json.loads(args[2])})
    elif cmd == "delete":
        out = call("DELETE", args[0])
    elif cmd == "save":
        out = save_configuration(" ".join(args))
    elif cmd == "bulk":
        out = _bulk(args)
    elif cmd == "nodesrt":
        out = call("GET", "datalayer/nodesrt")
    elif cmd == "token":
        print(token())
        return
    elif cmd == "rtmap":
        rev, size, variables = rtmap(args[0])
        print(f"revision {rev}   sizeBytes {size}")
        print(f"{'byte':>5} {'bit':>5} {'bits':>4}  {'type':<8} name")
        for v in variables:
            print(f"{v['bitoffset'] // 8:>5} {v['bitoffset']:>5} {v['bitsize']:>4}  "
                  f"{v['type'].rsplit('/', 1)[-1]:<8} {v['name']}")
        return
    elif cmd == "rtdata":
        rev, size, variables = rtmap(args[0])
        buf = bytes(call("GET", f"{args[0]}/data")["value"])
        print(f"revision {rev}   sizeBytes {size}   read {len(buf)} bytes")
        for v in variables:
            t = v["type"].rsplit("/", 1)[-1]
            o = v["bitoffset"] // 8
            val = struct.unpack_from("<" + FMT[t], buf, o)[0] if t in FMT else buf[o:o + v["bitsize"] // 8].hex()
            print(f"{o:>5}  {v['name']:<40} {val}")
        return
    else:
        sys.exit(__doc__)
    print(json.dumps(out, indent=2))


def _bulk(paths):
    url = f"{API}/bulk?type=read"
    body = json.dumps([{"address": p} for p in paths]).encode()
    req = urllib.request.Request(url, body, {"Authorization": f"Bearer {token()}",
                                             "Content-Type": "application/json"}, method="PUT")
    with urllib.request.urlopen(req, context=CTX, timeout=15) as r:
        return json.load(r)


if __name__ == "__main__":
    main(sys.argv[1:])
