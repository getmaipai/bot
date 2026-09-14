# Build record: the owned parts

The final parts of the build guide, per the org's build-doc rule (final
parts only, never interim ones). This record lists every part the design
in [`../dev.md`](../dev.md) is written onto, by build stage, as the
design names it. The owner's parts record (`owned-parts.md`, kept
outside git beside the design scratch) confirms the exact model of each;
where it has not answered yet, the "As owned" column holds a question
mark and the question is numbered in `dev.md`'s "Open questions". No
row proposes a part the owner does not have, and no row is a
recommendation: an open row is a documentation gap, filled by the owner's
answer and by nothing else.

A parts list is not household content; this file carries no address,
network, name or recording.

## Core: the brain

| Part | Design class | As owned | Open |
|---|---|---|---|
| Compute | Raspberry Pi 5, 16 GB | Pi 5, 16 GB | |
| Power supply (bench) | Official Pi 5 supply, 27 W USB-C | official 27 W | |
| Cooling | Official Active Cooler | official | |
| AI accelerator | Raspberry Pi AI HAT+ 2, Hailo-10H, 40 TOPS, on the Pi's PCIe | AI HAT+ 2 | HailoRT and driver versions recorded at bring-up |
| Boot drive | M.2 SSD, B+M key, 256 GB or more | ? | model, SATA or NVMe (question 9) |
| SSD enclosure | USB 3.2 Gen 2 M.2 enclosure, RTL9210B bridge, 2242 to 2280, on a USB 3 port | ? | model (question 9) |
| Recovery card | microSD, 16 GB or more, optional | ? | |
| Compute UPS | Waveshare UPS HAT (E), 5 V 6 A out, USB-C PD in, under the Pi | UPS HAT (E) | measured reserve and runtime |
| UPS cells | Four matched flat-top 21700, 5,000 mAh | ? | cell model (question 9) |
| Clock | Pi 5 RTC battery | ? | battery and connection (question 9) |
| Header and breakout | 2x20 male header, 40-pin ribbon, T-type breakout, breadboard | ? | |

## Stage 1: the head

| Part | Design class | As owned | Open |
|---|---|---|---|
| Body screen | Freenove 5-inch DSI touchscreen, 800x480, 50 cm 22-to-15-pin cable, CAM/DISP 0 | Freenove 5-inch | panel cutout and touch orientation on the final shell |
| Camera | Raspberry Pi Camera Module 3, standard 75 degrees, 50 cm 22-to-15-pin cable, CAM/DISP 1 | ? | the exact variant (question 9) |
| Eyes | Two 2-inch 240x320 ST7789 SPI displays, 3.3 V | ? | module variant (question 10) |
| Mouth | Two WS2812B 8x8 matrices | ? | module variant (question 10) |
| Face controller | Raspberry Pi Pico 2 W (RP2350), driving the eyes and the mouth | Pico 2 W | firmware version recorded at bring-up |
| Level shifter | 74AHCT125, DIP-14 | ? | |
| Neck | Two-axis metal pan-tilt kit, Yahboom class: 20 kg 270-degree pan servo, 25 kg 180-degree tilt servo, aluminium brackets with bearings | ? | exact kit and servo models, horn geometry, stops, head mass (question 2) |
| Servo driver | PCA9685 16-channel PWM at 0x40, ALLCALL cleared at init | PCA9685 | |
| Joint encoders | Two AS5600 magnetic encoders with diametric magnets, each on its own mux channel (fixed 0x36) | AS5600 x2 | magnet mounting and alignment (question 2) |
| I2C multiplexer | TCA9548A, strapped to 0x71 | TCA9548A | channel allocation recorded at bring-up |
| Motion sensor | MPU-6050 (GY-521) at 0x68 | MPU-6050 | mounting orientation |
| Distance | VL53L5CX 8x8 time-of-flight, all at 0x29 behind the mux | ? | count installed and positions: two bought against seven in the design (question 7) |
| Presence | Two 24 GHz FMCW micro-motion radars, UART and GPIO out | ? | exact modules (the docs once name LD2410), placement (question 7) |
| Ambient light | VEML7700 on I2C | VEML7700 | |
| Touch | MPR121 capacitive controller with copper tape | ? | |
| Expander | MCP23017 at 0x20 | ? | |
| Environment | BME688 | ? | |
| Microphone | Four-mic USB array with echo cancelling and direction finding, XVF3800 class, on a USB 2 port directly, never behind a hub; firmware 2.1.0 or later, checked by the self-test | XVF3800 array | the mute mechanism (question 1); until answered the product says "software mute" and claims no physical mute |
| Speaker | A small powered speaker with a 3.5 mm input on the array's line-out, never USB or Bluetooth audio | ? | model and its supply in the finished build (question 8) |
| Servo rail | An isolated 5 V servo supply separate from compute and audio | ? | the finished rail against the stated stall past 5 A (question 3); expression is gated on its measurement under a two-servo stall (BODY-04) |
| Mouth supply | 5 V, 3 A or more, never the Pi's pins | ? | |

## Bench equipment for the neck test (not robot parts)

| Part | Design class | As owned | Open |
|---|---|---|---|
| Bench supply | 5 V, 6 A or more, screw or barrel terminals | ? | |
| Breaker | 10 A push-button resettable, manual reset, rated 65 V DC | ? | |

## Later stages (after Robot v0.1's head and voice)

| Part | Design class | As owned | Open |
|---|---|---|---|
| Main battery | 36 V nominal, 10S, about 10 Ah, 21700 pack, BMS 20 A or more | ? | pack, cells, BMS, charge limits (question 4) |
| Distribution | 36-to-12 V 15 A converter, fused 12 V block, 12 V-to-USB-C PD feed to the UPS, 5 V peripheral buck 8 to 10 A, 30 A breaker rated to interrupt DC at 42 V | ? | converters, fuses, breaker as wired (question 4) |
| Pack sensing | INA228 strapped to 0x44, DS18B20 pack thermometers on 1-Wire | ? | shunt rating, probe attachment (question 4) |
| Drive | Donor hoverboard motors and controller, ADuM1201 isolated UART, ST-Link V2 for firmware | ? | controller, firmware, wheels, brake actuator and feedback (question 5) |
| Chassis | Three-tier plastic nightstand, about 12.6 x 12.6 x 22.6 in, plywood deck, two 3 to 4 inch rubber swivel casters | ? | caster model, loaded center of gravity (question 5) |
| Physical safety | 22 mm emergency-stop button, bumper microswitches, in the fail-safe chain that interrupts motion power and, for the head, the servo rail | ? | spare contacts for a sense line (question 6); the chain proven to cut the servo rail before expression runs (BODY-04) |
| Body controller | A second Pico 2 | ? | |
| Body screen and knob | Round "heart" display with rotary control | ? | module (question 10) |
| Cooling and light | 60 mm fan, 12 V WS2815 underglow | ? | fan, strip length (question 10) |
| USB | Four-port hub on the second USB 3 port | ? | model and port allocation (question 8) |
| Navigation | RPLIDAR C1, 12 m, at the waist; a rear camera | RPLIDAR C1 | the rear camera (question 7) |
| Follow and carry | Fold-flat wire basket with HX711 load cells; a UWB tag pair; TSOP38238 IR receiver and a 38 kHz IR transmitter; 433 MHz RX and TX | ? | modules, load cell capacity and count (question 10) |
| Dock | Spring contacts, weight switches, reed and magnet, a leak trip, in series into an enclosed certified mains switch; a normally closed charge gate on the robot; a 42 V charger | ? | charger, switch rating, contact geometry, gate part (question 4) |

## Wiring facts carried from the mirror (to verify on the assembled head)

Pi 5 header, BCM numbering, as the legacy hardware record left it: I2C1
on 2 and 3; UART2 on 4 and 5 for the UWB tag; the eyes on SPI0 (CS 7
and 8, DC 6, RST 25, MOSI 10, SCLK 11) until the Pico takes them; the
DS18B20 bus on 13; UART0 on 14 and 15 through the isolator to the motor
board; fan PWM on 17; the brake heartbeat on 18 (PWM0) into a
retriggerable monostable; mouth data on 19 through the level shifter;
HX711 on 20 and 21; radar out on 22 with 23 held for a rear radar; IR
receive on 24 and transmit on 26; 433 MHz TX on 27; 9, 12 and 16 free
(12 and 16 were the underglow data and the removed shutter switch; a
Pi 5 cannot drive WS281x directly). I2C: 0x15 CST816S (knob fallback),
0x20 MCP23017, 0x2D UPS HAT (E), 0x29 every VL53L5CX, 0x36 both AS5600,
0x40 PCA9685, 0x44 INA228, 0x5A MPR121, 0x68 MPU-6050, 0x71 TCA9548A.
The mux budget is seven channels for seven ToF units with the two
encoders sharing channels with a ToF each (0x29 and 0x36 do not
collide), one channel spare. The PCA9685 answers on All Call 0x70 out
of reset, which is the mux's default: strap the mux to 0x71 and clear
ALLCALL in the driver, both.

Every stage page of the build guide ends in a check that proves the
stage worked (the array's wake score on the self-test, the encoder
sweep, the calibration run's envelope) before the next stage starts.
