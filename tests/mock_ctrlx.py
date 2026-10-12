"""Minimal mock of a ctrlX CORE REST API, for testing dl.py and motion_axes.py offline.

    python3 mock_ctrlx.py <port> <certfile> <keyfile>

Implements what the scripts use, with the behaviour seen on a real controller (2026-10):
  POST /identity-manager/api/v1.0/auth/token     -> 201 {"access_token": ...}; everything else needs the Bearer token
  /automation/api/v2/nodes/<path>                GET (read, ?type=browse|metadata), PUT, POST, DELETE
  PUT  /automation/api/v2/bulk?type=read
  GET  /solutions/api/v1/solutions, .../<s>/configurations, POST /solutions/api/v1/tasks
Motion: motion/axs (create axis by POSTing its name, only in CONFIGURATION), motion/axs/<ax>/cfg with
properties/units/lim sub-nodes, motion/cfg/unsaved, motion/state/opstate. motion/axs/<ax>/cfg/save rejects an
empty persistence param with the real 500 "Invalid parameter". A Solutions save clears 'unsaved'.
GET /__log returns every request seen (for tests to assert that nothing unexpected was written).
"""
import copy
import json
import ssl
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOKEN = "mock-token"
LOG = []
STATE = {"opstate": "Configuration", "unsaved": False, "axes": {}}
VALUES = {"system/info/name": {"type": "string", "value": "MockCore"},
          "motion/realtime/cyclicStatusData/info": {"type": "object", "value": {"type": "Input", "sizeBytes": 9}},
          "motion/realtime/cyclicStatusData/map": {"type": "object", "value": {"revision": 7, "variables": [
              {"name": "Ax/flag", "bitoffset": 64, "bitsize": 8, "type": "types/datalayer/bool8"},
              {"name": "Ax/pos", "bitoffset": 0, "bitsize": 64, "type": "types/datalayer/float64"}]}},
          # Ax/pos = 12.5 (LREAL, little-endian) at byte 0, Ax/flag = TRUE at byte 8
          "motion/realtime/cyclicStatusData/data": {"type": "aruint8", "value": [0, 0, 0, 0, 0, 0, 41, 64, 1]}}


def new_axis_cfg():
    return {"objectType": "Axis", "axisProfileName": "",
            "properties": {"axsType": "LINEAR", "modulo": False, "moduloValue": 0.0, "activated": True},
            "units": {"default": [{"valueType": "position+length", "abbreviation": "mm"},
                                  {"valueType": "velocity", "abbreviation": "mm/min"},
                                  {"valueType": "acceleration", "abbreviation": "m/s^2"},
                                  {"valueType": "jerk", "abbreviation": "m/s^3"}]},
            "limits": {"posMin": -1000.0, "posMax": 1000.0, "velPos": 6000.0, "velNeg": 6000.0, "acc": 2.0,
                       "dec": 2.0, "jrkAcc": 0.0, "jrkDec": 0.0, "posMinUnit": "mm", "posMaxUnit": "mm",
                       "velPosUnit": "mm/min", "velNegUnit": "mm/min", "accUnit": "m/s^2", "decUnit": "m/s^2",
                       "jrkAccUnit": "m/s^3", "jrkDecUnit": "m/s^3"}}


def problem(status, title, instance, detail=None):
    return status, {"type": "about:blank", "title": title, "status": status, "instance": instance,
                    "detail": detail or title}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def reply(self, status, body=None):
        raw = json.dumps(body).encode() if body is not None else b""
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n)) if n else None

    def handle_any(self, method):
        url = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(url.query)
        path = urllib.parse.unquote(url.path)
        body = self.body()
        if path == "/__log":
            return self.reply(200, LOG)
        LOG.append({"method": method, "path": path, "query": url.query, "body": body})
        if path == "/identity-manager/api/v1.0/auth/token" and method == "POST":
            if body == {"name": "boschrexroth", "password": "boschrexroth"}:
                return self.reply(201, {"access_token": TOKEN, "token_type": "Bearer"})
            return self.reply(*problem(401, "Unauthorized", path))
        if self.headers.get("Authorization") != f"Bearer {TOKEN}":
            return self.reply(*problem(401, "Unauthorized", path))
        if path.startswith("/solutions/api/v1"):
            return self.reply(*self.solutions(method, path[len("/solutions/api/v1"):], body))
        if path == "/automation/api/v2/bulk" and method == "PUT":
            out = []
            for item in body:
                st, val = self.node("GET", item["address"], {}, None)
                out.append({"address": item["address"], "result": "DL_OK" if st == 200 else val["title"],
                            **({k: val[k] for k in ("type", "value")} if st == 200 else {})})
            return self.reply(200, out)
        if path.startswith("/automation/api/v2/nodes"):
            return self.reply(*self.node(method, path[len("/automation/api/v2/nodes"):].strip("/"), query, body))
        return self.reply(*problem(404, "Not Found", path))

    def solutions(self, method, sub, body):
        if method == "GET" and sub == "/solutions":
            return 200, [{"name": "DefaultSolution", "description": "Default Solution", "active": True}]
        if method == "GET" and sub == "/solutions/DefaultSolution/configurations":
            return 200, [{"name": "Mapping"}, {"name": "appdata", "active": True}]
        if method == "POST" and sub == "/tasks":
            p = (body or {}).get("properties", {})
            if (body or {}).get("action") != "save" or p.get("solution") != "DefaultSolution" \
                    or p.get("configuration") != "appdata":
                return problem(400, "Bad Request", "/solutions/api/v1/tasks")
            STATE["unsaved"] = False
            return 200, {"id": "mock1", "configuration": "appdata",
                         "partialResults": [{"phase": "save", "app": "rexroth-motion", "subject": "motion settings"}]}
        return problem(404, "Not Found", sub)

    def node(self, method, path, query, body):
        kind = (query.get("type") or ["read"])[0]
        axs = STATE["axes"]
        parts = path.split("/")
        if method == "GET" and kind == "browse":
            if path == "":
                return 200, {"type": "arstring", "value": ["motion", "system"], "responseType": "browse"}
            if path == "motion/axs":
                return 200, {"type": "arstring", "value": list(axs), "responseType": "browse"}
        if method == "GET" and kind == "metadata" and path == "motion/axs":
            return 200, {"type": "object", "value": {"nodeClass": "Collection", "operations": {"create": True},
                                                     "references": [{"type": "createType",
                                                                     "targetAddress": "types/datalayer/string"}]}}
        if path == "motion/state/opstate" and method == "GET":
            return 200, {"type": "string", "value": STATE["opstate"]}
        if path == "motion/cfg/unsaved" and method == "GET":
            return 200, {"type": "bool8", "value": STATE["unsaved"]}
        if path == "motion/axs" and method == "POST":
            name = (body or {}).get("value")
            if STATE["opstate"] != "Configuration":
                return problem(405, "DL_INVALID_OPERATION_MODE", path, "create needs CONFIGURATION")
            if name in axs:
                return problem(409, "DL_CREATION_FAILED", path, "exists")
            axs[name] = new_axis_cfg()
            STATE["unsaved"] = True
            return 200, {"type": "string", "value": name, "responseType": "create"}
        if len(parts) >= 3 and parts[:2] == ["motion", "axs"] and parts[2] in axs:
            cfg = axs[parts[2]]
            rest = "/".join(parts[3:])
            if method == "DELETE" and rest == "":
                del axs[parts[2]]
                STATE["unsaved"] = True
                return 200, None
            if rest == "cfg" and method == "GET" and kind == "read":
                return 200, {"type": "object", "value": copy.deepcopy(cfg), "schema": "types/motion/axs/cfg"}
            if rest == "cfg/save" and method == "POST":
                if not (body or {}).get("value"):
                    return 500, {"title": "Error during backup or restoration", "status": 500,
                                 "detail": "Invalid parameter", "mainDiagnosisCode": "090F0054",
                                 "detailedDiagnosisCode": "0C570101"}
            sub = {"cfg/properties": "properties", "cfg/units": "units", "cfg/lim": "limits"}.get(rest)
            if sub and method == "PUT":
                val = body["value"]
                if sub == "properties" and val.get("axsType") != cfg["properties"]["axsType"]:
                    cfg.update(new_axis_cfg() | {"axisProfileName": cfg["axisProfileName"]})  # type change resets
                if sub == "units":
                    cfg["units"] = val
                else:
                    cfg[sub].update(val)
                STATE["unsaved"] = True
                return 200, {"type": "object", "value": copy.deepcopy(cfg[sub]), "responseType": "write"}
            # Like the real controller (Motion RM26): the cfg struct field is axisProfileName, but the node
            # is cfg/axisprofile; cfg/axisProfileName is DL_INVALID_ADDRESS
            if rest == "cfg" and method == "GET" and kind == "browse":
                return 200, {"type": "arstring", "value": ["axisprofile", "lim", "properties", "save", "units"],
                             "responseType": "browse"}
            if rest == "cfg/axisprofile" and method == "GET":
                return 200, {"type": "string", "value": cfg["axisProfileName"], "responseType": "read"}
            if rest == "cfg/axisprofile" and method == "PUT":
                cfg["axisProfileName"] = body["value"]
                STATE["unsaved"] = True
                return 200, {"type": "string", "value": body["value"]}
        if path in VALUES and method == "GET" and kind == "read":
            return 200, VALUES[path] | {"responseType": "read"}
        if path in VALUES and method == "PUT":
            VALUES[path] = {"type": body["type"], "value": body["value"]}
            return 200, VALUES[path]
        return problem(404, "DL_INVALID_ADDRESS", path)

    def do_GET(self): self.handle_any("GET")
    def do_PUT(self): self.handle_any("PUT")
    def do_POST(self): self.handle_any("POST")
    def do_DELETE(self): self.handle_any("DELETE")


if __name__ == "__main__":
    port, cert, key = int(sys.argv[1]), sys.argv[2], sys.argv[3]
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert, key)
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    print("ready", flush=True)
    srv.serve_forever()
