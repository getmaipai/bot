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


def test_unreadable_light_ends_night_after_grace_when_quiet_hours_end():
    from maipai_body.presence.night import UNREADABLE_LIGHT_GRACE_S

    clock = Clock()
    policy = NightPolicy(clock)
    # The camera may watch but neither the sensor nor the camera gives a reading.
    assert policy.update(quiet_hours=True, lux=None, watch_level="presence")
    assert policy.update(quiet_hours=False, lux=None, watch_level="presence")
    clock.value = UNREADABLE_LIGHT_GRACE_S - 1
    assert policy.update(quiet_hours=False, lux=None, watch_level="presence")
    clock.value = UNREADABLE_LIGHT_GRACE_S
    assert not policy.update(quiet_hours=False, lux=None, watch_level="presence")


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


def test_entering_night_makes_the_five_calls_with_half_the_volume():
    rig = _Rig(lux=100)
    rig.quiet = True
    rig.night.apply_settings({FACE_COLOR_KEY: "sky"})
    rig.device.calls.clear()
    assert rig.night.tick() is True
    assert ("self.screen.set_face_background", {"palette": "sky", "night": True}) in rig.names()
    assert ("self.screen.set_brightness", {"brightness": NIGHT_BRIGHTNESS}) in rig.names()
    assert ("self.audio_speaker.set_volume", {"volume": 25}) in rig.names()
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
    # Day never enables the wandering: that is the power rule's decision, not the night rule's.
    assert ("self.robot.set_idle_motion", {"enabled": True}) not in rig.names()
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


def test_reconnect_resyncs_morning_state_even_when_host_already_believes_day(tmp_path):
    from maipai_body.bodies.stackchan.owner_levels import OwnerLevels

    rig = _Rig(lux=100)
    levels = OwnerLevels(tmp_path / "owner_levels.json")
    levels.load()
    rig.night = NightController(
        rig.device,
        clock=rig.clock,
        quiet_hours=lambda: rig.quiet,
        levels=levels,
    )
    rig.night.on_connect()
    assert rig.night.tick() is False
    assert ("self.screen.set_face_background", {"palette": "mint", "night": False}) in rig.names()
    assert ("self.screen.set_brightness", {"brightness": 100}) in rig.names()
    assert ("self.audio_speaker.set_volume", {"volume": 70}) in rig.names()


def test_reconnect_during_quiet_hours_sends_night_state(tmp_path):
    from maipai_body.bodies.stackchan.owner_levels import OwnerLevels

    rig = _Rig(lux=100)
    rig.quiet = True
    levels = OwnerLevels(tmp_path / "owner_levels.json")
    levels.load()
    rig.night = NightController(
        rig.device,
        clock=rig.clock,
        quiet_hours=lambda: rig.quiet,
        levels=levels,
    )
    rig.night.on_connect()
    assert rig.night.tick() is True
    assert ("self.screen.set_face_background", {"palette": "mint", "night": True}) in rig.names()
    assert ("self.audio_speaker.set_volume", {"volume": 35}) in rig.names()


def test_reconnect_writes_the_default_owner_volume_when_none_was_ever_saved(tmp_path):
    from maipai_body.bodies.stackchan.owner_levels import OwnerLevels

    levels = OwnerLevels(tmp_path / "levels.json")
    levels.load()
    rig = _Rig(lux=100)
    rig.night = NightController(
        rig.device, clock=rig.clock, quiet_hours=lambda: rig.quiet, levels=levels
    )
    rig.night.on_connect()
    rig.night.tick()
    assert ("self.audio_speaker.set_volume", {"volume": 70}) in rig.names()
    assert levels.volume == 70  # never adopts a value the unit happens to have


def test_no_calls_are_made_while_no_unit_is_connected_and_the_unit_is_synced_when_it_joins(
    tmp_path,
):
    from maipai_body.bodies.stackchan.owner_levels import OwnerLevels

    levels = OwnerLevels(tmp_path / "levels.json")
    levels.load()
    rig = _Rig(lux=100)
    connected = {"value": False}
    rig.night = NightController(
        rig.device,
        clock=rig.clock,
        quiet_hours=lambda: rig.quiet,
        levels=levels,
        connected=lambda: connected["value"],
    )
    rig.night.tick()
    assert rig.names() == []
    connected["value"] = True
    rig.night.on_connect()
    rig.night.tick()
    assert ("self.screen.set_face_background", {"palette": "mint", "night": False}) in rig.names()


def test_unreadable_light_with_the_camera_barred_ends_night_at_once_after_quiet_hours():
    rig = _Rig(lux=None, level="off")
    rig.quiet = True
    rig.night.tick()  # quiet hours: night on
    assert rig.night.night is True
    rig.quiet = False
    rig.night.tick()
    assert rig.night.night is False


def test_voice_volume_is_owner_level_by_day_and_temporary_at_night(tmp_path):
    from maipai_body.bodies.stackchan.owner_levels import OwnerLevels

    levels = OwnerLevels(tmp_path / "levels.json")
    levels.load()
    rig = _Rig(lux=100)
    rig.night = NightController(
        rig.device,
        clock=rig.clock,
        quiet_hours=lambda: rig.quiet,
        levels=levels,
    )
    rig.night.set_owner_volume_from_voice(85)
    assert levels.volume == 85
    rig.quiet = True
    rig.night.tick()
    rig.night.set_owner_volume_from_voice(45)
    assert levels.volume == 85
    rig.quiet = False
    rig.night.tick()
    rig.clock.value = 120
    rig.device.ambient_lux = 100
    rig.night.tick()
    assert rig.device.volume == 85
    assert rig.night.night_volume_override is None


def test_failed_face_warning_is_short_each_poll_and_traceback_is_rate_limited(caplog):
    import logging

    rig = _Rig(lux=100)
    rig.quiet = True
    rig.device.connected = False
    with caplog.at_level(logging.WARNING, logger="maipai_body.presence.night"):
        rig.night.tick()
        rig.clock.value = 10
        rig.night.tick()
    records = [r for r in caplog.records if "night call failed" in r.message]
    assert len(records) == 2
    assert sum(bool(r.exc_info) for r in records) == 1
    assert all("Traceback" not in r.message for r in records)
    rig.clock.value = 300
    with caplog.at_level(logging.WARNING, logger="maipai_body.presence.night"):
        rig.night.tick()
    assert sum(bool(r.exc_info) for r in caplog.records if "night call failed" in r.message) == 2


def test_alarm_at_night_plays_at_full_volume_and_night_never_lowers_it():
    rig = _Rig(lux=100)
    rig.quiet = True
    rig.night.tick()
    assert rig.device.volume == 25
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
    assert rig.device.volume == 25


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


def test_entering_night_turns_the_wandering_off_and_leaving_it_never_turns_it_on():
    rig = _Rig(lux=100)
    rig.quiet = True
    rig.night.tick()
    assert ("self.robot.set_idle_motion", {"enabled": False}) in rig.names()
    rig.device.calls.clear()
    rig.quiet = False
    rig.night.tick()
    rig.clock.value = 120
    rig.night.tick()
    rig.night.on_connect()
    rig.night.tick()
    assert not any(
        name == "self.robot.set_idle_motion" and args.get("enabled") for name, args in rig.names()
    )


def test_the_after_edge_hook_runs_so_the_power_rule_can_write_its_value():
    rig = _Rig(lux=100)
    edges = []
    rig.night.after_edge = lambda: edges.append(1)
    rig.quiet = True
    rig.night.tick()
    rig.quiet = False
    rig.night.tick()
    rig.clock.value = 120
    rig.night.tick()
    assert len(edges) == 2


def test_a_reconnect_by_day_with_the_still_level_leaves_the_idle_motion_off():
    from maipai_body.bodies.stackchan.power_idle import PowerIdle

    rig = _Rig(lux=100)
    power = PowerIdle(
        rig.device.set_idle_motion,
        night_active=lambda: rig.night.night,
        configured_level=lambda: "still",
    )
    rig.night.after_edge = power.refresh
    power.on_battery_status(False)
    rig.night.on_connect()
    power.on_reconnect()
    rig.night.tick()
    power.tick()
    writes = [args["enabled"] for name, args in rig.names() if name == "self.robot.set_idle_motion"]
    assert writes and not any(writes)  # every write says off


def test_home_default_calm_counts_as_still_and_lively_is_a_choice():
    from maipai_body.app import _effective_idle_level

    assert _effective_idle_level("calm") == "still"
    assert _effective_idle_level("still") == "still"
    assert _effective_idle_level("lively") == "lively"


def test_a_lit_room_seen_by_the_camera_never_starts_night_even_if_the_sensor_reads_dark():
    clock = Clock()
    policy = NightPolicy(clock)
    for t in (0, 60, 130, 600):
        clock.value = t
        assert not policy.update(
            quiet_hours=False, lux=0.0, watch_level="presence", camera_luma=120.0
        )


def test_night_starts_only_when_the_sensor_and_the_camera_both_say_dark():
    clock = Clock()
    policy = NightPolicy(clock)
    policy.update(quiet_hours=False, lux=0.0, watch_level="presence", camera_luma=5.0)
    clock.value = 130
    assert policy.update(quiet_hours=False, lux=0.0, watch_level="presence", camera_luma=5.0)


def test_a_bright_frame_ends_night_after_two_minutes_though_the_sensor_still_reads_low():
    clock = Clock()
    policy = NightPolicy(clock)
    policy.update(quiet_hours=False, lux=0.0, watch_level="presence", camera_luma=5.0)
    clock.value = 130
    assert policy.update(quiet_hours=False, lux=0.0, watch_level="presence", camera_luma=5.0)
    clock.value = 140
    assert policy.update(quiet_hours=False, lux=1.7, watch_level="presence", camera_luma=110.0)
    clock.value = 270
    assert not policy.update(quiet_hours=False, lux=1.7, watch_level="presence", camera_luma=110.0)


def test_a_tilted_unit_does_not_read_its_sensors_for_night():
    from maipai_body.presence.night import NightController

    class Device:
        def __init__(self):
            self.reads = 0

        def get_ambient_light(self):
            self.reads += 1
            return 0.0

        def set_face_background(self, palette, night):
            return None

        def set_idle_motion(self, enabled):
            return None

        def set_volume(self, volume):
            return None

        def set_brightness(self, brightness):
            return None

    clock = Clock()
    device = Device()
    controller = NightController(
        device,
        clock=clock,
        quiet_hours=lambda: False,
        camera_luma=lambda: 3.0,
        connected=lambda: True,
        sensors_blocked=lambda: True,
    )
    for t in (0, 60, 130, 300):
        clock.value = t
        controller.tick()
    assert device.reads == 0 and controller.night is False
