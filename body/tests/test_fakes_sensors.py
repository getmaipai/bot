"""The fake's scripted sensors: DoA, IMU, camera frames, the loopback recorder, the face tracker.

The seam-shape checks take ``body_client``, so they run against the fake
always and against the simulator when ``MAIPAI_BODY_LIVE=1`` (the same
suite, two backends). The scripted behaviour is the fake's own, so it
runs on the fake only.
"""

from __future__ import annotations

import numpy as np
import pytest

from maipai_body.bodies.reachy_mini.fake import (
    FACES_DIR,
    FakeReachyMiniClient,
    LoopbackRecorder,
    ManualClock,
    freefall_reading,
    load_face_fixture,
    rest_reading,
    tipped_reading,
)
from maipai_body.hal.seam import (
    DirectionOfArrival,
    FaceTrackTarget,
    ImuReading,
)
from maipai_body.presence.safety import is_freefall, is_tipped

# -- the seam suite: fake always, simulator opt-in --


def test_get_doa_answers_the_seam_shape(body_client):
    reading = body_client.get_doa()
    assert reading is None or isinstance(reading, DirectionOfArrival)


def test_imu_read_answers_the_seam_shape(body_client):
    reading = body_client.read()
    assert reading is None or isinstance(reading, ImuReading)


def test_get_frame_answers_the_seam_shape(body_client):
    frame = body_client.get_frame()
    if frame is not None:
        assert frame.ndim == 3 and frame.shape[2] == 3 and frame.dtype == np.uint8


def test_face_target_answers_the_seam_shape(body_client):
    target = body_client.get_face_target()
    assert isinstance(target, FaceTrackTarget)


def test_push_audio_sample_is_accepted(body_client):
    body_client.start_playing()
    body_client.push_audio_sample(np.zeros(160, dtype=np.float32))
    body_client.stop_playing()


# -- scripted DoA --


def test_doa_follows_the_script_by_the_clock():
    clock = ManualClock()
    client = FakeReachyMiniClient(
        doa_script=[(0.5, 0.3, False), (1.0, -0.4, True), (2.0, -0.4, False)], clock=clock
    )
    assert client.get_doa() is None  # nothing before the first entry
    clock.advance(0.5)
    assert client.get_doa() == DirectionOfArrival(angle_rad=0.3, speech_detected=False)
    clock.advance(0.6)
    assert client.get_doa() == DirectionOfArrival(angle_rad=-0.4, speech_detected=True)
    clock.advance(5.0)
    assert client.get_doa() == DirectionOfArrival(angle_rad=-0.4, speech_detected=False)


def test_doa_script_must_be_time_ordered():
    with pytest.raises(ValueError, match="time order"):
        FakeReachyMiniClient(doa_script=[(1.0, 0.0, False), (0.5, 0.0, True)])


def test_doa_without_a_script_replays_the_recorded_sample():
    reading = FakeReachyMiniClient().get_doa()
    assert reading is None or isinstance(reading, DirectionOfArrival)


# -- scripted IMU --


def test_imu_script_walks_rest_then_tip_then_freefall():
    clock = ManualClock()
    client = FakeReachyMiniClient(
        imu_script=[(0.0, rest_reading()), (1.0, tipped_reading()), (2.0, freefall_reading())],
        clock=clock,
    )
    first = client.read()
    assert first is not None and not is_tipped(first) and not is_freefall(first)
    clock.advance(1.0)
    tipped = client.read()
    assert tipped is not None and is_tipped(tipped) and not is_freefall(tipped)
    clock.advance(1.0)
    falling = client.read()
    assert falling is not None and is_freefall(falling)


def test_imu_without_a_script_is_none():
    assert FakeReachyMiniClient().read() is None


def test_imu_script_must_be_time_ordered():
    with pytest.raises(ValueError, match="time order"):
        FakeReachyMiniClient(imu_script=[(1.0, rest_reading()), (0.0, rest_reading())])


# -- camera fixtures --


def test_faces_directory_names_its_provenance():
    readme = (FACES_DIR / "README.md").read_text()
    assert "synthetic" in readme.lower()
    assert "no household photos" in readme.lower()


@pytest.mark.parametrize("name", ["face_center", "face_left", "face_right", "no_face"])
def test_face_fixtures_are_bgr_uint8_frames(name):
    frame = load_face_fixture(name)
    assert frame.dtype == np.uint8 and frame.ndim == 3 and frame.shape[2] == 3


def test_an_unknown_face_fixture_is_an_error_not_a_blank_frame():
    with pytest.raises(FileNotFoundError):
        load_face_fixture("nobody_home")


def test_get_frame_steps_through_scripted_fixtures_by_the_clock():
    clock = ManualClock()
    client = FakeReachyMiniClient(
        frame_script=[(0.0, "no_face"), (1.0, "face_center")], clock=clock
    )
    assert np.array_equal(client.get_frame(), load_face_fixture("no_face"))
    clock.advance(1.0)
    assert np.array_equal(client.get_frame(), load_face_fixture("face_center"))


def test_explicit_camera_frame_still_wins_without_a_script():
    frame = np.zeros((4, 4, 3), dtype=np.uint8)
    assert FakeReachyMiniClient(camera_frame=frame).get_frame() is frame


# -- loopback recorder --


def test_loopback_recorder_stamps_what_push_audio_sample_received():
    clock = ManualClock()
    recorder = LoopbackRecorder(clock=clock)
    client = FakeReachyMiniClient(recorder=recorder, clock=clock)
    client.start_playing()
    client.push_audio_sample(np.full(1600, 0.1, dtype=np.float32))
    clock.advance(0.1)
    client.push_audio_sample(np.full(800, 0.2, dtype=np.float32))
    client.stop_playing()

    assert [round(c.t_s, 3) for c in recorder.chunks] == [0.0, 0.1]
    assert [c.frames for c in recorder.chunks] == [1600, 800]
    assert recorder.total_frames == 2400
    assert recorder.duration_s(16000) == pytest.approx(0.15)
    assert recorder.first_push_t_s == 0.0
    assert recorder.events == ["start", "push", "push", "stop"]
    assert recorder.samples().shape == (2400,)


def test_loopback_recorder_keeps_pushed_audio_visible_on_the_client_too():
    client = FakeReachyMiniClient()
    client.push_audio_sample(np.zeros(10, dtype=np.float32))
    assert len(client.pushed_audio) == 1


def test_loopback_recorder_is_empty_before_any_push():
    recorder = LoopbackRecorder()
    assert recorder.first_push_t_s is None and recorder.total_frames == 0
    assert recorder.samples().shape == (0,)


# -- face tracker script --


def test_face_tracker_detects_then_loses_by_the_clock():
    clock = ManualClock()
    client = FakeReachyMiniClient(
        face_script=[
            (0.0, FaceTrackTarget(detected=False)),
            (1.0, FaceTrackTarget(detected=True, x=0.1, y=-0.2, roll=0.0)),
            (3.0, FaceTrackTarget(detected=False)),
        ],
        clock=clock,
    )
    assert client.get_face_target().detected is False
    clock.advance(1.0)
    assert client.get_face_target() == FaceTrackTarget(detected=True, x=0.1, y=-0.2, roll=0.0)
    clock.advance(2.0)
    assert client.get_face_target().detected is False


def test_face_script_reports_nothing_while_tracking_is_off():
    clock = ManualClock()
    client = FakeReachyMiniClient(
        face_script=[(0.0, FaceTrackTarget(detected=True, x=0.0, y=0.0, roll=0.0))],
        clock=clock,
        require_tracking=True,
    )
    assert client.get_face_target().detected is False
    client.enable_tracking()
    assert client.get_face_target().detected is True
    client.disable_tracking()
    assert client.get_face_target().detected is False


def test_directly_assigned_face_target_still_works_without_a_script():
    client = FakeReachyMiniClient()
    client.face_target = FaceTrackTarget(detected=True)
    assert client.get_face_target().detected is True


def test_scripted_reads_refuse_after_a_disconnect():
    from maipai_body.hal.errors import BodyLost

    client = FakeReachyMiniClient(imu_script=[(0.0, rest_reading())])
    client.simulate_disconnect()
    for call in (client.read, client.get_doa, client.get_frame, client.get_face_target):
        with pytest.raises(BodyLost):
            call()
