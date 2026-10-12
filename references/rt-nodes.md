# RT node layouts seen on a controller

Read 2026-10-09 with `dl.py rtmap` on the controller at 192.168.10.130 (an example, not the default: ask the user which controller to use).

**The per-axis block layout of `cyclicStatusData` is the same on every controller** (the user confirmed this). You can write the code against the field table below without reading the map over REST first. What differs per machine is the **axis names**, and with them which blocks exist and where each block starts. **The PLC code must still read the live map at runtime** (`FB_AxisRtMap`): it finds and confirms every offset by `<axis>/<field>` name, and gets the map revision that `BeginAccess` needs. Never hard-code offsets or the revision from this table. Get those from the user or the project's axis config (e.g. `motion/*.json`), or browse `motion/axs` when a controller IP is known. Never reuse the example names below (Ax1, Ax2, VM).

## motion/realtime/cyclicStatusData

`info`: type Input, sizeBytes 177 (3 axes × 59 bytes), accessType NTelBuf. `map` revision 3939902176.

Each axis whose cyclic status data is enabled gets a **59-byte packed block**. The blocks are back to back (Ax1 at 0, Ax2 at 59, VM at 118). The field layout inside a block is the same for every axis:

| Byte in block | Size | Type | Field |
|---:|---:|---|---|
| 0 | 8 | float64 | ActualPos |
| 8 | 8 | float64 | ActualVel |
| 16 | 8 | float64 | ActualTRQ |
| 24 | 8 | float64 | ActualTRQPercent |
| 32 | 4 | uint32 | DeviceErrorCode |
| 36 | 4 | uint32 | PlcOpenState |
| 40 | 2 | uint16 | DriveStatusWord |
| 42 | 1 | bool8 | DataValid |
| 43 | 1 | bool8 | Homed |
| 44 | 1 | bool8 | Standstill |
| 45 | 1 | bool8 | PowerReady |
| 46 | 1 | bool8 | PowerOn |
| 47 | 1 | bool8 | HasError |
| 48 | 1 | bool8 | HasWarning |
| 49 | 1 | bool8 | AxisFollowCommand |
| 50 | 1 | bool8 | InPosition |
| 51 | 1 | bool8 | InVelocity |
| 52 | 1 | bool8 | InTorque |
| 53 | 1 | bool8 | InSynchronization |
| 54 | 1 | bool8 | OverrideIsZero |
| 55 | 1 | bool8 | ActualSafeMode (in the map, but the project doesn't use it) |
| 56 | 1 | bool8 | TorqueCtrlPosVelLim |
| 57 | 1 | bool8 | TorqueCtrlNegVelLim |
| 58 | 1 | bool8 | InSyncWindow |

Map names are `<axis>/<field>`, e.g. `Ax2/ActualVel` at bitoffset 536 (byte 67 = 59 + 8). The doubles are **not 8-byte aligned** past the first axis.

With no drives connected, DeviceErrorCode reads 0xFFFFFFFF and DriveStatusWord reads 0.

## Other RT nodes on this controller

`datalayer/retain/emu`, `plc/admin/retain`, `motion/realtime-data/input`, `motion/state/functions/somo/rt-data/signals_in|signals_out`, `motion/cmd-input/double`, `motion/axs/{Ax1,Ax2,VM}/cmd-input/double`, `scheduler/.../duration-rt|common-data-rt`.
