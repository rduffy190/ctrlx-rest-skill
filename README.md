# ctrlx-rest

An agent skill (`SKILL.md` format) for reading and writing the Bosch Rexroth **ctrlX CORE / ctrlX OS Data Layer** over its REST API (`https://<host>/automation/api/v2`).

An agent using it can browse nodes, read values, metadata and type definitions, bulk-read, subscribe (SSE), and decode real-time (RT) memory maps such as `motion/realtime/cyclicStatusData`. It can also create and configure ctrlX MOTION axes (units, limits, virtual or real) and save the active configuration so changes survive a reboot. Writes are planned and confirmed before they reach the controller.

## Install

Put this folder in the skills directory your agent loads skills from, under the folder name `ctrlx-rest`. It works on its own; the `ctrlx-engineer` skill refers to it for live node paths and RT map layouts before writing PLC code.

The scripts also work without an agent:

```bash
export CTRLX_HOST=<controller-ip>          # no default; CTRLX_USER / CTRLX_PASS default to the factory login
python3 -I scripts/dl.py browse motion/axs
python3 -I scripts/dl.py rtmap motion/realtime/cyclicStatusData
python3 -I scripts/motion_axes.py plan references/examples/example_axes.json
```

## Requirements

- Python 3.10+, standard library only. On Windows, use `python` or `py -3` where the docs say `python3`.
- `openssl`, only for the offline tests (the mock controller uses a throwaway HTTPS certificate).

## What's inside

| Path | Contents |
|---|---|
| `SKILL.md` | The skill: helper commands, controller address rules, API essentials, RT nodes, where things live in ctrlX MOTION |
| `scripts/dl.py` | Data Layer client: browse, read, meta, type, bulk, write, create, delete, RT map and data decode, save the configuration |
| `scripts/motion_axes.py` | Create and configure axes from a JSON spec (`show`, `plan`, `apply [--save]`) |
| `references/datalayer-openapi-2.1.5.json` | The Data Layer REST API spec (grep it, don't read it whole) |
| `references/motion-config.md` | Configuring axes, units and limits over the Data Layer, and saving |
| `references/rt-nodes.md` | The `cyclicStatusData` per-axis field layout |
| `references/examples/example_axes.json` | A worked axis spec for `motion_axes.py` |
| `tests/run.sh` | Offline suite against `tests/mock_ctrlx.py`; `--live` adds a read-only smoke test against `CTRLX_HOST` |

## Tests

```bash
tests/run.sh            # should end with ALL OK (bash; Git Bash on Windows)
```
