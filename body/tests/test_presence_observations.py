"""RM-06: this body's own inputs to the presence funnel, combined into one read."""

from __future__ import annotations

from maipai_body.bodies.reachy_mini.client import ReachyMiniClient
from maipai_body.bodies.reachy_mini.fake import FakeReachyMiniClient
from maipai_body.hal.seam import DirectionOfArrival, FaceTrackTarget
from maipai_body.presence.observations import read_presence


def test_no_face_and_no_doa_reads_as_absent():
    client = FakeReachyMiniClient()
    observation = read_presence(client)
    assert observation.face_detected is False
    assert observation.doa_angle_rad is None
    assert observation.speech_detected is False


def test_a_tracked_face_is_reported_with_its_position():
    client = FakeReachyMiniClient()
    client.face_target = FaceTrackTarget(detected=True, x=120.0, y=80.0, roll=0.1)

    observation = read_presence(client)

    assert observation.face_detected is True
    assert observation.face_x == 120.0
    assert observation.face_y == 80.0


def test_enabling_tracking_is_recorded_on_the_fake():
    client = FakeReachyMiniClient()
    client.enable_tracking(weight=0.7)
    assert client.tracking_enabled is True
    assert client.tracking_weight == 0.7

    client.disable_tracking()
    assert client.tracking_enabled is False


def test_direction_of_arrival_from_a_recorded_fixture_reaches_the_observation():
    """No fixture frame has a real DoA reading (the sim has no mic input); the
    seam's own None-when-unavailable path is what this asserts.
    """
    client = FakeReachyMiniClient()
    doa = client.get_doa()
    assert doa is None or isinstance(doa, DirectionOfArrival)

    observation = read_presence(client)
    assert observation.doa_angle_rad == (doa.angle_rad if doa else None)


def test_enabling_and_disabling_tracking_does_not_raise(body_client):
    body_client.enable_tracking(weight=0.5)
    if isinstance(body_client, ReachyMiniClient):
        body_client.get_face_target()  # confirms the daemon accepted the enable call
    body_client.disable_tracking()


def test_a_presence_read_never_raises_on_either_client(body_client):
    """The simulator has no camera scene, mic input, or IMU to report; a live
    read must still come back as a well-typed absence, not an exception.
    """
    observation = read_presence(body_client)
    assert observation.face_detected in (True, False)
    assert observation.tip_detected in (True, False)
    assert observation.freefall_detected in (True, False)
