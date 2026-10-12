# Configuring ctrlX MOTION over the Data Layer (axes, units, limits, saving)

These notes were verified against this project's controller (ctrlX COREvirtual, Motion 4.6, Data Layer API 2.1.5) on 2026-10-09. The manual background is in ctrlx-engineer `references/motion/04-01_General_information.md`, sections 4.1.5–4.1.9.

**Use the scripts.** `scripts/motion_axes.py plan|apply <spec.json> [--save]` does everything below from a JSON spec, and `show` prints a summary table. `references/examples/press_axes.json` is a worked spec.

## Before writing

- `motion/state/opstate` must read `Configuration` to create or delete axes. It follows the ctrlX OS state: SETUP gives Configuration, OPERATION gives Running. Limits can usually still be changed while Running, but objects can't be added or removed.
- `motion/axs` (browse) lists the existing axes.
- **Real or virtual?** `axisprofile/profiles` (browse) lists the drive profiles. An empty list, or no EtherCAT master in the Data Layer root, means only **virtual axes** are possible (`axisProfileName: ""`). On a COREvirtual it's always virtual. To make an axis real later, write a profile name to the axis' profile node, which is only allowed in SETUP. The node name depends on the Motion version (see the table below).
- **Names** are at most 16 chars of `[A-Za-z0-9_]` and must be unique across axes and kinematics. The PLC `AXIS_REF.AxisName` is `STRING(15)`, so keep names ≤ 15 characters.

## Nodes

| Action | Call |
|---|---|
| Create axis | `POST motion/axs` with `{"type":"string","value":"<name>"}` (metadata `createType` = string) |
| Delete axis | `DELETE motion/axs/<name>` (Configuration only) |
| Whole axis config | `GET/PUT motion/axs/<name>/cfg` (type `types/motion/axs/cfg`) |
| Properties | `PUT .../cfg/properties` with `{"type":"object","value":{"axsType":"LINEAR"\|"ROTATIONAL","modulo":false,"moduloValue":360}}` |
| Default units | `PUT .../cfg/units` with `{"type":"object","value":{"default":[{"valueType":"position+length","abbreviation":"mm"},…]}}` |
| Limits | `PUT .../cfg/lim` with posMin, posMax, velPos, velNeg, acc, dec, jrkAcc, jrkDec (+ trqPos/trqNeg), each with an optional `<field>Unit` |
| Profile link | `PUT .../cfg/axisprofile` (string, SETUP only). Older Motion versions use `.../cfg/axisProfileName`. In the whole `cfg` struct, the field is always `axisProfileName`. Verified on Motion RM26 (88.1.2), 2026-10-12: `cfg/axisProfileName` returns 404 there. `motion_axes.py` browses `cfg` to pick the node that exists. |
| Unsaved changes? | `GET motion/cfg/unsaved` → bool |
| Supported units | `GET motion/state/units` → list of `{name, unitObjType, unitValueType, abbreviation, abbreviationURI, isDefault}` |

Write **properties first**. Changing LINEAR↔ROTATIONAL resets the axis units and limits.

Put the unit strings **inside the limits struct** (`posMinUnit`, `velPosUnit`, `accUnit`, `jrkAccUnit`, …). The values are then interpreted correctly whatever the default units are. A PUT returns the stored struct, so check it.

### Factory defaults of a new axis
LINEAR, non-modulo, virtual. Position ±1000 mm, velocity 6000 mm/min, acc/dec 2 m/s², jerk 0, torque 10 Nm. Default units: mm, mm/min, m/s², m/s³. **PLC commands use the default units**, so set them to what the PLC code assumes (e.g. mm, mm/s, mm/s², mm/s³).

### Unit abbreviations (linear)
- position: `mm` `cm` `m` `um` `in` `thou`
- velocity: `mm/s` `mm/min` `m/s` `m/min` `in/s` `in/min`
- acceleration: `mm/s^2` `m/s^2` `cm/s^2` `in/s^2` `g`
- jerk: `mm/s^3` `m/s^3` `in/s^3`

### Unit abbreviations (rotary)
- position: `deg` `rev` `rad`
- velocity: `rpm` `deg/s` `rev/s` `rad/s`
- acceleration: `deg/s^2` `rad/s^2` `rev/s^2`
- jerk: `deg/s^3` `rad/s^3`

The valueType strings are `position+length`, `velocity`, `acceleration`, `jerk`, `force`, `torque`, `time`.

To read or write a single value in another unit, append the unit's `abbreviationURI` to the path, e.g. `.../cfg/lim/acc/in-per-s^2`.

## Saving (making it survive a reboot)

The Motion manual says to POST `motion/axs/<ax>/cfg/save` or `motion/cfg/save-all`. On this controller these, and `motion/admin/cfg/make-persistent/<ax>`, take a `types/datalayer/persistence_param` (`configurationPath`, `id`, `phase`). Sent empty, they fail with **HTTP 500 "Invalid parameter"** (main 090F0054, detail 0C570101, DL_SUBMODULE_FAILURE).

**What works** is saving the active configuration through the Solutions app, the same as the web UI "Save":

```
GET  /solutions/api/v1/solutions                              -> [{"name":"DefaultSolution","active":true}]
GET  /solutions/api/v1/solutions/<sol>/configurations         -> [{"name":"appdata","active":true,...}]
POST /solutions/api/v1/tasks  {"action":"save","properties":{"solution":"DefaultSolution","configuration":"appdata","comment":"..."}}
     -> 200 {"id":..., "partialResults":[{"phase":"save","app":"rexroth-motion","subject":"motion settings"}, ...]}
```

`dl.py save "comment"` does exactly this. It saves **every app's** current state (motion, axis profiles, scheduler, PLC runtime data, Data Layer mappings…), not just motion, so tell the user. Afterwards `motion/cfg/unsaved` reads `false`.
