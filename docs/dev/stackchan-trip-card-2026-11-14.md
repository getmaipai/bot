# StackChan trip card: using the robot away from home (2026-11-14)

For the owner on the road. Plain words. Written from the firmware 0.2.102 source and the relay v2 program; **nothing here has run with a real
robot through the relay yet**, so each "not verified" note below is a real gap. An HTML copy for a phone is `data-scratch/trip-card.html`.

## What you need

The robot, your iPhone and its USB cable, the laptop with Tailscale signed in, and the relay file `trip-relay.py` (also in the bot
repo as `body/scripts/trip_relay.py`). The robot's firmware must be 0.2.102 or newer.

## At the friend's house, in order

1. iPhone: Settings, Personal Hotspot on. Plug it into the laptop by USB (tap Trust if asked).
2. Laptop: System Settings, General, Sharing, Internet Sharing. Share from the iPhone USB connection to Wi-Fi. Wi-Fi options: name
   **`maipai-trip`** (it must start with `maipai`), WPA2 Personal, your password. Turn Internet Sharing on.
3. Laptop: Tailscale on in the menu bar.
4. Terminal: `python3 ~/Downloads/trip-relay.py` and leave the window open. It opens a status page: http://127.0.0.1:8899
5. Switch the robot on. It joins `maipai-trip` (once it has been taught the network, see "Teach the robot").
6. Watch the status page. Four lights: Internet Sharing, Tailscale, the Studio, the robot. When all are green, talk to the robot.

The friend's own Wi-Fi is never used, so its address range cannot clash.

## Teach the robot the laptop's network (once, before leaving if you can)

The robot opens its own setup page **only when it powers up** and has no saved Wi-Fi it can reach within about 60 seconds (read from the firmware).
There is no gesture that opens it while it is running.

1. At home: in Home, Devices, the robot, Robot Wi-Fi: forget your home network. (The robot stays connected until it restarts.)
2. Switch the robot off and on. The face says to join a hotspot called `Xiaozhi-...`.
3. Join that hotspot with your own phone (not the one plugged into the laptop). Open `http://192.168.4.1`.
4. Add **two** networks: `maipai-trip` with its password, and your home Wi-Fi again. Press the page's exit button.
5. The robot joins your home Wi-Fi again (stronger). It now knows both.

Not verified on this robot: adding two networks in one visit and the exit button. If the page takes only one network per visit, power-cycle
and repeat for the second. At the friend's house you can also do this there: the robot sees no saved network, opens the page by itself.

## What the status page lights mean

- **Internet Sharing red:** it is off. Turn it on (step 2). The relay starts by itself when it appears.
- **Tailscale red:** open Tailscale in the menu bar, sign in, turn it on. The relay keeps trying.
- **The Studio red:** the laptop cannot reach your home hub. Check Tailscale here; check the Studio shows online in the Tailscale app on your phone.
  If the Studio is off at home, nothing helps until it is on.
- **Robot grey or red:** the robot is not connected. Wait a minute; check it joined the `maipai` network; if not, "If something is wrong" below.
- **All green:** the robot is connected through your laptop. Leave the window open.

The relay also sends a Mac notification when the robot connects or is lost, when the Studio cannot be reached, and when Tailscale or Internet Sharing is off.

## What the robot's screen tells you

- **"Offline" in the upper left** appears after 45 seconds without the hub. A shorter drop (a hub restart) shows nothing.
- **A hotspot named `Xiaozhi-...` on its face** (at power-up): it has no saved network in reach. Use "Teach the robot".
- **Swipe up on the face** opens the quick-settings panel: volume, brightness and the saved Wi-Fi list, where you can pick another saved network
  (from the firmware notes; not verified on this robot).

Home also shows how the robot is connected: Settings, Robots, the robot, Connection: "Connected at home", "Connected away from home (through your
laptop)", or "Offline since 14:10", plus "The robot is reconnecting to the hub (try 3)" while it retries.

## If something is wrong, in this order

1. Run `python3 ~/Downloads/trip-relay.py --doctor`. Each line says OK or FIX with what to do.
2. **Robot never connects:** switch the robot off and on, wait one minute. Check the network name starts with `maipai`. Check Internet Sharing is on and the
   laptop shows the sharing address in the doctor output.
3. **The robot joined your friend's Wi-Fi instead:** forget that network on the robot (Home, Robot Wi-Fi, or the setup page after a power-up), or switch
   the robot off and on near the laptop only. The relay is used only on a `maipai...` network.
4. **The laptop's sharing address is not 192.168.2.1:** fine. The robot tries its own network's gateway, which is the laptop, whatever the address.
5. **The relay says it cannot start:** another copy is open (close the other Terminal window), then it retries by itself.
6. **Chat is slow or drops:** the iPhone's signal is the usual cause; move near a window. The robot reconnects by itself.
7. **The laptop slept:** wake it; the relay notices and starts again by itself.
8. **Still nothing:** the robot works alone, with faces, timers, dancing and phrases, but without chat. Everything returns when you are home: it
   retries your home address about once a minute.

## What heals itself and what does not

By itself: the robot retries the hub (growing pauses up to about a minute), tries the laptop after two failures on a `maipai` network, and tries home again
about every minute; the relay waits for Internet Sharing, restarts its listeners, notices sleep and wake, and retries the Studio every few seconds.
Not by itself (needs your hands): switching Internet Sharing on, Tailscale signed in, teaching the robot the `maipai-trip` network.
