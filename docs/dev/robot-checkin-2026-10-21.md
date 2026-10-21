# Robot check-in (0.2.31)

The StackChan unit cannot call the hub, so the body reports for it: `PUT {hub}/api/devices/me/checkin`, session cookie
as for `/me/state`, JSON body, sent on connect, when the unit reports a boot or firmware, and every 60 seconds.
A 404 means the hub has no route yet; the body asks again in ten minutes.

| Field | Source | Null when |
|---|---|---|
| `device_id` | MAC the unit sent as Device-Id | no unit connected |
| `board` | constant `m5stack-stack-chan` | never |
| `online` | a voice socket is open | never |
| `last_seen` | body clock, ISO 8601 UTC | never |
| `connected_since` | when the socket opened | offline |
| `ip` | socket remote address | offline |
| `firmware_version` | `fw` event (patch 062) | unit not yet flashed with 062 |
| `bot_version` | installed `maipai-bot` | bare checkout |
| `rssi` | `fw` event, dBm | not flashed with 062, or not connected |
| `signal` | `self.get_device_status` network class (strong, medium, weak) | unit did not answer |
| `free_heap_internal`, `free_heap_min`, `psram_free` | `heap_stats` event | none seen yet |
| `boot_reason`, `crash_resets` | `boot` event | none seen since the body started |
| `battery_level`, `charging` | battery tool | unit did not answer |

The SSID is never sent. `link/checkin.py` holds the payload and the reporter; `UnitFacts` keeps the newest values.
