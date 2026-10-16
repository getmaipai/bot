from __future__ import annotations

import pytest

from maipai_body.bodies.stackchan.adapter import StackChanRobotAdapter
from maipai_body.bodies.stackchan.fake import FakeStackChanDeviceClient
from maipai_body.hal.errors import BodyLost, NotPermitted, NotSupported


def test_idle_speak_is_gated_by_policy_and_reaches_device_when_allowed():
    device = FakeStackChanDeviceClient()
    adapter = StackChanRobotAdapter(device, proactive_policy=lambda action: True)
    adapter.robot.lease.acquire("person", "test")

    result = adapter.robot.audio.speaker.speak("Dinner is ready")

    assert result is True
    assert device.push_actions[-1] == ("speak", {"text": "Dinner is ready"})


def test_policy_denial_uses_robot_not_supported_error_with_fix():
    adapter = StackChanRobotAdapter(FakeStackChanDeviceClient())
    adapter.robot.lease.acquire("person", "test")

    with pytest.raises(NotSupported) as raised:
        adapter.robot.audio.speaker.speak("Hello")

    assert raised.value.part == "audio"
    assert raised.value.capability == "speaker"
    assert raised.value.fix


def test_push_verbs_require_lease():
    adapter = StackChanRobotAdapter(
        FakeStackChanDeviceClient(), proactive_policy=lambda action: True
    )

    with pytest.raises(NotPermitted, match="control lease"):
        adapter.robot.audio.speaker.speak("Hello")


def test_reminder_actions_queue_when_offline_and_flush_after_reconnect():
    device = FakeStackChanDeviceClient()
    adapter = StackChanRobotAdapter(device, proactive_policy=lambda action: True)
    robot = adapter.robot
    robot.lease.acquire("person", "test")
    device.connected = False

    with pytest.raises(BodyLost):
        robot.reminders.create_reminder(message="Take medicine", delay_seconds=60)

    assert len(adapter.queued_reminders) == 1
    device.connected = True
    adapter.flush_reminders()
    assert device.push_actions[-1][0] == "create_reminder"
    assert not adapter.queued_reminders


def test_alert_fallback_uses_face_led_and_spoken_line():
    device = FakeStackChanDeviceClient()
    device.supported_push_actions = {
        "speak",
        "create_reminder",
        "get_reminders",
        "stop_reminder",
        "listen_window",
    }
    adapter = StackChanRobotAdapter(device, proactive_policy=lambda action: True)
    robot = adapter.robot
    robot.lease.acquire("person", "test")

    robot.lease.acquire("person", "test")
    robot.alerts.show(message="Door is open")

    assert device.led_color != (0, 0, 0)
    assert device.push_actions[-1] == ("speak", {"text": "Door is open"})


def test_reminder_list_stop_and_listen_window_are_pushed():
    device = FakeStackChanDeviceClient()
    adapter = StackChanRobotAdapter(device, proactive_policy=lambda action: True)
    robot = adapter.robot
    robot.lease.acquire("person", "test")

    robot.reminders.create_reminder(message="Tea", delay_seconds=30)
    assert robot.reminders.get_reminders() == [{"message": "Tea", "delay_seconds": 30}]
    robot.reminders.stop_reminder(id="reminder-1")
    robot.audio.listen_window(duration_seconds=10)

    assert [action for action, _ in device.push_actions] == [
        "create_reminder",
        "get_reminders",
        "stop_reminder",
        "listen_window",
    ]


def test_alert_uses_notify_only_when_profile_opt_in_and_hello_feature_are_present():
    device = FakeStackChanDeviceClient()
    device.notify_feature = True
    adapter = StackChanRobotAdapter(
        device, proactive_policy=lambda action: True, notify_enabled=True
    )
    adapter.robot.lease.acquire("person", "test")

    adapter.robot.alerts.show(message="Door is open")

    assert device.push_actions[-1] == (
        "notify",
        {"audio_url": device.notification_audio_url},
    )
    assert device.led_color == (0, 0, 0)


def test_alert_falls_back_when_device_does_not_advertise_notify():
    device = FakeStackChanDeviceClient()
    adapter = StackChanRobotAdapter(
        device, proactive_policy=lambda action: True, notify_enabled=True
    )
    adapter.robot.lease.acquire("person", "test")

    adapter.robot.alerts.show(message="Door is open")

    assert device.led_color == (168, 36, 0)
    assert device.push_actions[-1] == ("speak", {"text": "Door is open"})
