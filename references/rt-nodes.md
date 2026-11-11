# RT node layouts seen on a controller

Read with `dl.py rtmap` on a ctrlX CORE with three axes (Ax1, Ax2, VM). Ask the user which controller to use; there is no default.

**The per-axis block layout of `cyclicStatusData` is the same on every controller**, so PLC code can be written against the field table below without reading the map first. Only the axis names (and so which blocks exist and where each starts) differ per machine. The PLC still reads the live map at runtime and never hard-codes offsets or the revision: see the ctrlx-engineer skill, `references/datalayer-rt.md`. Never reuse the example axis names (Ax1, Ax2, VM).

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
| 55 | 1 | bool8 | ActualSafeMode |
| 56 | 1 | bool8 | TorqueCtrlPosVelLim |
| 57 | 1 | bool8 | TorqueCtrlNegVelLim |
| 58 | 1 | bool8 | InSyncWindow |

Map names are `<axis>/<field>`, e.g. `Ax2/ActualVel` at bitoffset 536 (byte 67 = 59 + 8). The doubles are **not 8-byte aligned** past the first axis.

With no drives connected, DeviceErrorCode reads 0xFFFFFFFF and DriveStatusWord reads 0.

## Other RT nodes on that controller

`datalayer/retain/emu`, `plc/admin/retain`, `motion/realtime-data/input`, `motion/state/functions/somo/rt-data/signals_in|signals_out`, `motion/cmd-input/double`, `motion/axs/{Ax1,Ax2,VM}/cmd-input/double`, `scheduler/.../duration-rt|common-data-rt`.
