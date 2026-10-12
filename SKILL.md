---
name: ctrlx-rest
description: Read and write the Bosch Rexroth ctrlX CORE / ctrlX OS Data Layer over its REST API (https://<host>/automation/api/v2). Use it to browse nodes, read values, metadata and type definitions, bulk-read, subscribe (SSE), and decode real-time (RT) memory maps such as motion/realtime/cyclicStatusData/map. Also use it to create and configure ctrlX MOTION axes (units, limits, virtual or real) and to save the active configuration so changes survive a reboot. Use it whenever you need to see what is actually on a ctrlX controller (axis names, node paths, RT buffer layouts, config values) before writing PLC code or tooling, or when the user mentions the Data Layer, the ctrlX REST API, a controller IP, or a node path like motion/axs/....
---

# ctrlX Data Layer REST API

The Data Layer is ctrlX OS's central data bus. Everything (motion, PLC, I/O, apps) publishes nodes in one tree. The REST API exposes the whole tree. The API version here is 2.1.5. The full OpenAPI spec is `references/datalayer-openapi-2.1.5.json`. Grep it; don't read all of it.

## Quick use: the helper script

`scripts/dl.py` uses only the standard library. Run it with `python3 -I`:

```bash
D=~/.claude/skills/ctrlx-rest/scripts/dl.py
python3 -I $D browse /                                     # root nodes
python3 -I $D browse motion/axs                            # axis names
python3 -I $D read   motion/axs/Ax1/state/values/actual/pos
python3 -I $D meta   motion/realtime/cyclicStatusData/map  # node class, ops, readType
python3 -I $D type   types/datalayer/memory_map            # JSON schema of a type
python3 -I $D bulk   motion/axs/Ax1/state/values/actual/pos motion/axs/Ax2/state/values/actual/pos
python3 -I $D nodesrt                                      # all RT (shared memory) nodes
python3 -I $D rtmap  motion/realtime/cyclicStatusData      # RT layout sorted by offset, revision, size
python3 -I $D rtdata motion/realtime/cyclicStatusData      # live RT buffer decoded with its map
python3 -I $D token                                        # bearer token for curl
python3 -I $D create motion/axs string '"Ax1"'             # POST: create a node / run a method
python3 -I $D delete motion/axs/Ax1                        # DELETE
python3 -I $D save "what changed"                          # save the ACTIVE configuration (persist)

M=~/.claude/skills/ctrlx-rest/scripts/motion_axes.py
python3 -I $M show                                         # axes: type, virtual/profile, limits, units
python3 -I $M plan  spec.json                              # what apply would write (no writes)
python3 -I $M apply spec.json --save                       # create/configure axes, then save
```

## Controller address: ask, don't guess

The scripts have **no default controller**. `CTRLX_HOST` (`<ip>[:port]`) must be set on every call, e.g. `CTRLX_HOST=192.168.1.1 python3 -I $D browse /`. `CTRLX_USER` / `CTRLX_PASS` default to `boschrexroth` / `boschrexroth` (factory default).

- Before the first controller call in a conversation, use the IP the user gave in this conversation. If they haven't given one, **ask for the ctrlX CORE IP address** and wait. Don't take an IP from memory, a reference file or a previous session: the user works with several controllers and networks, and a wrong IP either fails or, worse, reads or writes the wrong machine.
- Ask again when the user mentions a different controller, or when a call fails with `cannot reach the ctrlX at <ip>` (no route, timeout, refused). Report the error and ask them to confirm the IP and that the controller is reachable from this machine. Don't scan the network for it.
- If the login fails (HTTP 401), ask for the user name and password instead of retrying.
- Once confirmed, reuse that IP for the rest of the conversation.

**Configuring motion (axes, units, limits) and saving config:** read `references/motion-config.md` first. In short, create axes by POSTing to `motion/axs` in CONFIGURATION, write `cfg/properties`, then `cfg/units`, then `cfg/lim`. Persist with `dl.py save`, because the per-axis `cfg/save` nodes reject an empty persistence param.

**Reads are safe. Writes are not.** `write`, and any PUT/POST/DELETE, change a live controller that may be connected to machinery. Confirm with the user before every write, create or delete, and say what node and value will change.

## Regression tests

`tests/run.sh` runs `dl.py` and `motion_axes.py` against `tests/mock_ctrlx.py`, a local HTTPS mock of the token, nodes, bulk and Solutions endpoints, with the real controller's behaviour (including the per-axis `cfg/save` rejection). No controller is needed. `tests/run.sh --live` adds a **read-only** smoke test against `CTRLX_HOST`.

Run it after changing a script. When the real API turns out to behave differently, update the mock to match, then fix the script.

## API essentials

| | |
|---|---|
| Base URL | `https://<host>[:port]/automation/api/v2` (the cert is self-signed, so use `curl -k`) |
| Auth | `POST https://<host>/identity-manager/api/v1.0/auth/token` with body `{"name":"<user>","password":"<pw>"}` → 201 `{"access_token": "...", "token_type": "Bearer"}`. Send `Authorization: Bearer <token>` on every call. Without it: 401. |
| Swagger UI | `https://<host>/automationcore/api/datalayer/` (spec in `openapi.js`) |

### Node access: `/nodes/{path}`

| Call | Does |
|---|---|
| `GET /nodes/{path}` | Read. Returns `{"type": "<dl type>", "value": ..., "schema"?: "types/...", "responseType": "read"}` |
| `GET /nodes/{path}?type=browse` | Child names: `{"type":"arstring","value":[...]}`. Use `/nodes/` with an empty path (or `browse /` with the helper) for the root. |
| `GET /nodes/{path}?type=metadata` | `nodeClass` (Folder/Variable/Method/...), `operations` {read, write, create, delete, browse}, `description`, `unit`, `references` (e.g. `readType` → `types/...`) |
| `PUT /nodes/{path}` | Write. Body `{"type":"int32","value":5}`. Returns 200/202/204. |
| `POST /nodes/{path}` | Create (also used to *execute* method nodes, e.g. motion commands). Body as for PUT. |
| `DELETE /nodes/{path}` | Delete |
| `GET /nodes/types/{TypeName}` | Type definition (JSON schema) of a complex/flatbuffer type |

Value `type`s: `bool8, int8, uint8, int16, uint16, int32, uint32, int64, uint64, float32, float64` (also `float`/`double`), `string`, `ar<type>` arrays, `timestamp`, `object` (a flatbuffer shown as JSON with `schema`), `raw`, `empty`.

**Errors** are RFC 7807 `Problem` JSON: `{"title":"DL_INVALID_ADDRESS","status":404,"instance":"<path>","detail":...}`. The common titles are `DL_INVALID_ADDRESS` (no such node, 404), `DL_UNSUPPORTED` (operation not allowed on this node, 501), and `DL_TYPE_MISMATCH`.

### Bulk: `PUT /bulk?type=read|write|create|delete|browse|metadata`

The body is an array `[{"address":"<path>", "type"?:..., "value"?:...}]`. The response is an array with `address, result ("DL_OK" or an error), type, value, timestamp` per entry. Each entry fails on its own, and the HTTP status is still 200. A query string in an address doesn't work; use the `type=` of the bulk call.

### Subscriptions (SSE): `/events`

- `GET /events?nodes=a,b&publishIntervalMs=100` opens a Server-Sent Events stream. You get one initial event per node, then events only on change. The event types are `update`, `keepalive`, `error`, `browse` and `metadata`. Data: `{"node", "timestamp", "type", "value"}`.
- `POST /events` with `{"properties":{"id":"subID","publishInterval":100,...},"nodes":[...]}` creates a named subscription. Then `GET /events/{id}` streams it, and `PUT`/`DELETE /events/{id}` changes or removes it. A subscription that isn't started within 1 min is deleted.
- With curl, use `curl -N -k -H "Authorization: Bearer $T" ...` and stop it with a timeout. Don't leave it hanging.

### Other system nodes

`datalayer/nodes` (all NRT node names), `datalayer/nodesrt` (RT nodes), `datalayer/retain/stats`, `datalayer/subscriptions/settings`, `datalayer/server/settings`, `devices/remotes/{name}/{path}` (a remote Data Layer).

## Real-time (RT) nodes and memory maps

Some nodes are **shared-memory buffers**, not values: `motion/realtime/cyclicStatusData`, `plc/admin/retain`, `motion/axs/<ax>/cmd-input/double` and so on (see `datalayer/nodesrt`). RT nodes are folders with these children:

| Child | Content |
|---|---|
| `info` | `{"type":"Input"/"Output"/"Retain"..., "sizeBytes": N, "accessType": ...}` |
| `map` | `{"variables":[{"name","bitoffset","bitsize","type":"types/datalayer/<t>"}], "revision": <uint32>, "disableInputImage": bool}` |
| `data` | the raw buffer as `aruint8` (little-endian) |
| `access`, `maps-custom` | access type, custom maps |

- **Offsets are in bits.** Byte = bitoffset / 8. The layout is **packed**: an LREAL can start on an odd byte, so a PLC struct overlay only works with `pack_mode 1`. Reading field by field from the offsets is safer.
- `bool8` takes 1 byte (0/1).
- The `revision` changes when the variable list changes. The PLC's `DL_MemUser.BeginAccess` takes it, so store it with any offsets you hard-code, and check it before trusting them.
- Map entries come back unsorted. `dl.py rtmap` sorts them, and `dl.py rtdata` decodes the live buffer, which is a quick check of any offset table.

See `references/rt-nodes.md` for the layouts already read from this project's controller. For reading a map on the PLC (`DL_MemUser.GetMemoryMap` and `comm_datalayer_MemoryMap`), see the `ctrlx-engineer` skill, `references/datalayer-rt.md`.

## Where things live (ctrlX MOTION)

- `motion/axs` → axis names. Under each axis: `state/values/actual/{pos,vel,acc,torque}`, `state/opstate/plcopen`, `cfg/...`, `cmd/...` (POST to execute commands).
- `motion/axs/<ax>/cfg/functions/cyclic-status-data/{remanent,windows}` enables the axis in `motion/realtime/cyclicStatusData`.
- `motion/kin`, `motion/state` (`functions/somo` = safe motion), `scheduler/tasks`, `plc/app/...` (PLC symbols exported to the Data Layer).

- `motion/state/opstate` is `Configuration` or `Running`. `motion/state/units` lists the supported units. `motion/cfg/unsaved` is TRUE while there are unsaved config changes.
- `axisprofile/profiles` lists the drive profiles. If it's empty and there's no EtherCAT master, only virtual axes are possible (e.g. on a COREvirtual).

Browse before you assume a path. Names differ between Motion App versions.

## Other REST services on the same host

These all use the same bearer token. Use `dl.http(method, url, body)` for them.

| Service | Base | Notes |
|---|---|---|
| Solutions (configurations) | `/solutions/api/v1` | `solutions`, `solutions/<s>/configurations`, `POST tasks` with `{"action":"save",...}`. See `references/motion-config.md`. |
| Identity | `/identity-manager/api/v1.0` | `auth/token` |
