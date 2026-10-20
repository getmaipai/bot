from maipai_body.presence.night import NIGHT_DARK_LUX, NIGHT_LIGHT_LUX, NightPolicy
from maipai_body.settings_keys import FACE_COLOR_KEY, NIGHT_MODE_KEY, face_color, night_mode


class Clock:
    value = 0.0

    def __call__(self):
        return self.value


def test_dark_must_persist_two_minutes_and_hysteresis_holds_between_thresholds():
    clock = Clock()
    policy = NightPolicy(clock)
    assert not policy.update(quiet_hours=False, lux=NIGHT_DARK_LUX - 1, watch_level="presence")
    clock.value = 119
    assert not policy.update(quiet_hours=False, lux=NIGHT_DARK_LUX - 1, watch_level="presence")
    clock.value = 120
    assert policy.update(quiet_hours=False, lux=NIGHT_DARK_LUX - 1, watch_level="presence")
    clock.value = 500
    assert policy.update(
        quiet_hours=False,
        lux=(NIGHT_DARK_LUX + NIGHT_LIGHT_LUX) / 2,
        watch_level="presence",
    )


def test_quiet_hours_enter_immediately_and_light_ends_after_two_minutes():
    clock = Clock()
    policy = NightPolicy(clock)
    assert policy.update(quiet_hours=True, lux=100, watch_level="presence")
    assert policy.update(quiet_hours=False, lux=NIGHT_LIGHT_LUX + 1, watch_level="presence")
    clock.value = 120
    assert not policy.update(quiet_hours=False, lux=NIGHT_LIGHT_LUX + 1, watch_level="presence")


def test_disabled_mode_never_enters_night_and_off_watch_does_not_use_darkness():
    clock = Clock()
    policy = NightPolicy(clock)
    policy.enabled = False
    assert not policy.update(quiet_hours=True, lux=0, watch_level="off")
    policy.enabled = True
    clock.value = 200
    assert not policy.update(quiet_hours=False, lux=None, watch_level="off")


def test_setting_names_default_and_validate_face_palette():
    assert face_color({}) == "mint"
    assert face_color({FACE_COLOR_KEY: "rose"}) == "rose"
    assert face_color({FACE_COLOR_KEY: "ultraviolet"}) == "mint"
    assert night_mode({}) is True
    assert night_mode({NIGHT_MODE_KEY: False}) is False


# -- the controller, against the fake StackChan ------------------------------

from maipai_body.bodies.stackchan.adapter import StackChanRobotAdapter  # noqa: E402
from maipai_body.bodies.stackchan.fake import FakeStackChanDeviceClient  # noqa: E402
from maipai_body.initiative.alarm import VOLUME_FLOOR, AlarmController  # noqa: E402
from maipai_body.presence.night import NIGHT_BRIGHTNESS, NightController  # noqa: E402


class _Rig:
    def __init__(self, *, lux=None, level="presence", luma=None):
        self.clock = Clock()
        self.device = FakeStackChanDeviceClient()
        self.device.ambient_lux = lux
        self.quiet = False
        self.level = level
        self.luma = luma
        self.luma_reads = 0
        self.led_calls: list[bool] = []
        self.alarm = False

        def read_luma():
            self.luma_reads += 1
            return self.luma

        self.night = NightController(
            self.device,
            clock=self.clock,
            quiet_hours=lambda: self.quiet,
            watch_level=lambda: self.level,
            camera_luma=read_luma,
            leds=self.led_calls.append,
            alarm_active=lambda: self.alarm,
        )
        self.night.owner_volume = 50

    def names(self):
        return [(c.name, c.arguments) for c in self.device.calls]

    def tools(self):
        return [c.name for c in self.device.calls]


def test_entering_night_makes_the_five_calls_with_forty_percent_volume():
    rig = _Rig(lux=100)
    rig.quiet = True
    rig.night.apply_settings({FACE_COLOR_KEY: "sky"})
    rig.device.calls.clear()
    assert rig.night.tick() is True
    assert ("self.screen.set_face_background", {"palette": "sky", "night": True}) in rig.names()
    assert ("self.screen.set_brightness", {"brightness": NIGHT_BRIGHTNESS}) in rig.names()
    assert ("self.audio_speaker.set_volume", {"volume": 20}) in rig.names()
    assert ("self.robot.set_idle_motion", {"enabled": False}) in rig.names()
    assert rig.led_calls == [False]


def test_leaving_night_restores_the_owner_values_and_day_palette():
    rig = _Rig(lux=100)
    rig.quiet = True
    rig.night.tick()
    rig.quiet = False
    rig.night.tick()  # light starts counting
    rig.device.calls.clear()
    rig.clock.value = 120
    assert rig.night.tick() is False
    assert ("self.screen.set_face_background", {"palette": "mint", "night": False}) in rig.names()
    assert ("self.screen.set_brightness", {"brightness": 100}) in rig.names()
    assert ("self.audio_speaker.set_volume", {"volume": 50}) in rig.names()
    assert ("self.robot.set_idle_motion", {"enabled": True}) in rig.names()
    assert rig.led_calls == [False, True]


def test_polls_the_light_only_while_night_mode_is_on():
    rig = _Rig(lux=100)
    rig.night.tick()
    assert rig.tools().count("self.screen.get_ambient_light") == 1
    rig.night.apply_settings({NIGHT_MODE_KEY: False})
    rig.device.calls.clear()
    rig.quiet = True
    assert rig.night.tick() is False
    assert rig.device.calls == []


def test_turning_night_mode_off_at_night_returns_to_day():
    rig = _Rig(lux=100)
    rig.quiet = True
    rig.night.tick()
    rig.device.calls.clear()
    rig.night.apply_settings({NIGHT_MODE_KEY: False})
    assert ("self.screen.set_face_background", {"palette": "mint", "night": False}) in rig.names()
    assert rig.device.volume == 50


def test_face_color_change_shows_at_once_with_the_current_night_state():
    rig = _Rig(lux=100)
    rig.night.apply_settings({FACE_COLOR_KEY: "peach"})
    expected = ("self.screen.set_face_background", {"palette": "peach", "night": False})
    assert rig.names() == [expected]
    rig.device.calls.clear()
    rig.night.apply_settings({FACE_COLOR_KEY: "no-such-color"})
    expected = ("self.screen.set_face_background", {"palette": "mint", "night": False})
    assert rig.names() == [expected]


def test_dark_room_with_the_sensor_enters_night_after_two_minutes():
    rig = _Rig(lux=NIGHT_DARK_LUX - 1)
    rig.night.tick()
    rig.clock.value = 119
    assert rig.night.tick() is False
    rig.clock.value = 120
    assert rig.night.tick() is True


def test_watch_off_without_a_sensor_never_reads_the_camera_or_enters_night_by_dark():
    rig = _Rig(lux=None, level="off", luma=0.0)
    for t in (0, 60, 130, 300):
        rig.clock.value = t
        assert rig.night.tick() is False
    assert rig.luma_reads == 0
    rig.quiet = True
    assert rig.night.tick() is True
    rig.quiet = False
    assert rig.night.tick() is False  # nothing can confirm light: night ends with quiet hours
    assert rig.luma_reads == 0


def test_camera_fallback_is_used_without_a_sensor_when_the_watch_allows():
    rig = _Rig(lux=None, level="presence", luma=5.0)
    rig.night.tick()
    rig.clock.value = 120
    assert rig.night.tick() is True
    assert rig.luma_reads == 2


def test_a_failed_face_call_is_retried_next_poll():
    rig = _Rig(lux=100)
    rig.quiet = True
    rig.device.connected = False
    assert rig.night.tick() is False
    rig.device.connected = True
    assert rig.night.tick() is True


def test_alarm_at_night_plays_at_full_volume_and_night_never_lowers_it():
    rig = _Rig(lux=100)
    rig.quiet = True
    rig.night.tick()
    assert rig.device.volume == 20
    played: list[int] = []

    class Player:
        def chime(self):
            played.append(rig.device.volume)

        def clips(self, ids):
            played.append(rig.device.volume)
            return True

        def stop(self):
            pass

    alarm = AlarmController(
        player=Player(),
        present=lambda _on: None,
        resolve_clips=lambda kind, area: ["alarm-generic"],
        child_clips=lambda: [],
        send_action=lambda m: True,
        audience=lambda: [],
        is_child=lambda e: False,
        evidence=lambda: {},
        volume=rig.night.alarm_volume(),
    )
    rig.alarm = True
    alarm.handle_command({"alarm_id": "a1", "area": "kitchen", "kind": "smoke", "state": "active"})
    assert played and all(v >= VOLUME_FLOOR for v in played)
    rig.clock.value = 500
    rig.night.tick()  # a poll mid-alarm must not lower it
    assert rig.device.volume >= VOLUME_FLOOR
    rig.alarm = False
    alarm.handle_command({"alarm_id": "a1", "state": "cleared"})
    rig.night.tick()
    assert rig.device.volume == 20


def test_stackchan_settings_reach_the_night_controller_through_the_command_channel():
    from maipai_body.link.channel import CommandChannel
    from maipai_body.presence.sleep_auto import QuietHours

    rig = _Rig(lux=100)
    quiet = QuietHours()

    def apply(payload):
        quiet.apply(payload["values"])
        rig.night.apply_settings(payload["values"])

    channel = CommandChannel("http://192.0.2.1", "c", settings_handler=apply)
    channel.handlers["settings_changed"]({"values": {FACE_COLOR_KEY: "rose"}})
    assert ("self.screen.set_face_background", {"palette": "rose", "night": False}) in rig.names()
    assert StackChanRobotAdapter(rig.device)  # the adapter wraps the same client seam


def test_adapter_exposes_the_new_calls():
    import asyncio

    device = FakeStackChanDeviceClient()
    device.ambient_lux = 12.0
    adapter = StackChanRobotAdapter(device)

    async def go():
        await adapter.set_face_background("lemon", True)
        await adapter.set_idle_motion(False)
        await adapter.set_brightness(15)
        return await adapter.get_ambient_light()

    assert asyncio.run(go()) == 12.0
    assert [c.name for c in device.calls] == [
        "self.screen.set_face_background",
        "self.robot.set_idle_motion",
        "self.screen.set_brightness",
        "self.screen.get_ambient_light",
    ]


def test_behavior_makes_no_gestures_at_night_but_one_turn_to_face_a_speaker():
    from maipai_body.app import StackChanBehavior

    device = FakeStackChanDeviceClient()
    behavior = StackChanBehavior(StackChanRobotAdapter(device).robot)
    try:
        behavior.night_active = lambda: True
        assert behavior.render_primitive("settle") is False
        behavior.render_turn_state("thinking")
        assert not any(c.name == "self.robot.set_head_angles" for c in device.calls)
        behavior.render_turn_state("listening")
        turns = sum(c.name == "self.robot.set_head_angles" for c in device.calls)
        assert turns > 0
        behavior.render_turn_state("listening")
        assert sum(c.name == "self.robot.set_head_angles" for c in device.calls) == turns
        behavior.render_turn_state("settle")
    finally:
        behavior.close()
