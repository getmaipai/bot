# StackChan sensor map

Status: source research plus a firmware-backed battery status path. Hardware
has not arrived. The addresses and registers below are not verified on a
MaiPai paired unit.

| Part | Source-derived device facts | Source and reading | Current Bot status |
|---|---|---|---|
| Battery and charge state | AXP2101 at I2C `0x34`; status registers `0x00` and `0x01`; battery level register `0xA4`; temperature `0xA5`; charge LED `0x69`; power-key/plug IRQ status `0x49`. Read-only MCP result is `{ "percent": integer 0..100, "charging": boolean }`. | i41-eu/i41eu-StackChan `firmware/main/apps/app_embody_mode/HARDWARE.md` and `hal_bridge.h`; M5 pinned xiaozhi `main/boards/common/axp2101.cc`; MaiPai firmware patch 010 registers `self.battery.get_status` using existing HAL methods. Patch 009 makes failed common I2C reads log and return zero. Recorded 2026-10-15. | Shared `battery` API reads the MCP result on demand. Timeout or invalid shape maps to `BodyLost`; charging may safely be false when the device's protected I2C read times out. No hardware verification. |
| Body current and power | INA226 at I2C `0x41`, with 10 mΩ shunt R18; M5 source does not use this sensor in the pinned xiaozhi profile. | i41 `HARDWARE.md`; i41 `hal/drivers/INA226`; source says current sign is positive for drain and negative for charging, marked as author's measurement, not ours. | NotSupported; sensor map only. |
| Accelerometer and gyroscope | BMI270 at I2C `0x69`; source reports acceleration in g and angular rate in degrees/second. | i41 `HARDWARE.md`; i41 `hal/drivers/BMI270` and Embody telemetry implementation. The pinned M5 xiaozhi build has no corresponding translator tool. | NotSupported. |
| Head touch | Si12T at I2C `0x68`; three zones, per-zone intensity 0..3. Source reports press, release and swipe events. | i41 `HARDWARE.md`; i41 head-touch driver and event publisher. | NotSupported. |
| NFC | ST25R3916 at I2C `0x50`; IRQ not wired; source polls NFC-A tags and reads UID/type and a first NDEF record. | i41 `HARDWARE.md`; i41 `hal/drivers/ST25R3916`. | Not included in the shared robot API adapter. |
| Light and proximity | LTR-553ALS-WA at I2C `0x23`; light channels and proximity values. | i41 `HARDWARE.md`; i41 `hal/drivers/LTR553`. | Not included in the shared robot API adapter. |
| RTC | BM8563 at I2C `0x51`; source reads Unix time through the PCF8563 driver. Alarm use is not implemented there. | i41 `HARDWARE.md`; i41 `hal/drivers/PCF8563` and `Hal::getRtcUnix`. | Not included in the shared robot API adapter. |

M5 source read for this map is the pinned `m5stack/StackChan` commit
`1b5765599fba8aaad1811d9a79358ccc7051f5f3`, including its pinned xiaozhi
commit `e77dedb1309153bb63fed285772962c920c97dd4`. The comparison source is
`i41-eu/i41eu-StackChan`, branch `embody`, file
`firmware/main/apps/app_embody_mode/HARDWARE.md`. The i41 firmware is a
different build and these facts do not establish what a stock or MaiPai unit
reports at runtime.

Touch and IMU remain unavailable in `adapter.py`: the pinned translator has
no read-only MCP tool for either part. i41 source findings do not establish a
supported path on the pinned build. Run the unit kit described in
[stackchan-unit-measurements.md](stackchan-unit-measurements.md) after arrival.
Its simulator output is a schema rehearsal and must not be reported as
hardware evidence.
