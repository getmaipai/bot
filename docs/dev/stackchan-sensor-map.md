# StackChan sensor map

Status: source research only. Hardware has not arrived. The addresses and
registers below are not verified on a MaiPai paired unit, and this bot's
xiaozhi translator does not expose them yet.

| Part | Source-derived device facts | Source and reading | Current Bot status |
|---|---|---|---|
| Battery and charge state | AXP2101 at I2C `0x34`; status registers `0x00` and `0x01`; battery level register `0xA4`; temperature `0xA5`; charge LED `0x69`; power-key/plug IRQ status `0x49`. | i41-eu/i41eu-StackChan `firmware/main/apps/app_embody_mode/HARDWARE.md` and `hal_bridge.h`; M5 pinned xiaozhi `main/boards/common/axp2101.cc` reads current direction from `0x01`, level from `0xA4`, temperature from `0xA5`. | NotSupported. Patch 009 changes failed common I2C register reads to log and return zero, so `IsCharging()` yields false on a failed read instead of aborting. |
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

Battery, touch and IMU API parts remain unavailable in `adapter.py` until a
paired unit measurement and supported protocol path exist. Run the unit kit
described in [stackchan-unit-measurements.md](stackchan-unit-measurements.md)
after arrival. Its simulator output is a schema rehearsal and must not be
reported as hardware evidence.
