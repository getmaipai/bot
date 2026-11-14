from maipai_body.bodies.stackchan.meeting_faces import face_for_meeting
from maipai_body.bodies.stackchan.music_dance import mood_for_genre
from maipai_body.bodies.stackchan.sleep_z import SleepZ


def test_meeting_decisions_and_genre_hints():
    assert face_for_meeting("arrived") == ("surprised", "happy")
    assert face_for_meeting("child") == ("excited",)
    assert face_for_meeting("left") == ("sad",)
    assert mood_for_genre("heavy metal") == "angry"
    assert mood_for_genre("ambient") == "sleepy"
    assert mood_for_genre(None) is None


def test_sleep_z_is_silent_until_a_firmware_minimum_is_set(monkeypatch):
    from maipai_body.bodies.stackchan import sleep_z as module

    calls = []
    monkeypatch.setattr(module, "SLEEP_Z_FIRMWARE", None)
    sleep = SleepZ(lambda name, args: calls.append((name, args)), "0.2.86")
    sleep.drowsy()
    sleep.asleep()
    sleep.off()
    assert calls == []
    monkeypatch.setattr(module, "SLEEP_Z_FIRMWARE", (0, 2, 90))
    sleep = SleepZ(lambda name, args: calls.append((name, args)), "0.2.90")
    sleep.drowsy()
    sleep.asleep()
    sleep.off()
    assert calls == [
        ("self.face.sleep_z", {"stage": 1}),
        ("self.face.sleep_z", {"stage": 2}),
        ("self.face.sleep_z", {"stage": 0}),
    ]
