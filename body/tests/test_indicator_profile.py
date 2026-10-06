"""EYES-02: the Reachy profile declares ``eyes`` only while the Eyes are
enumerated and ready."""

from __future__ import annotations

from maipai_body.bodies.reachy_mini.fake import FakeEyes
from maipai_body.bodies.reachy_mini.profile import REACHY_MINI_PROFILE, profile_for_eyes
from maipai_body.hal.seam import NullIndicator


def test_the_static_profile_never_claims_eyes():
    assert "eyes" not in REACHY_MINI_PROFILE.capabilities


def test_eyes_is_declared_while_the_device_is_connected():
    profile = profile_for_eyes(FakeEyes(connected=True))
    assert profile.capabilities.count("eyes") == 1
    assert set(profile.capabilities) - {"eyes"} == set(REACHY_MINI_PROFILE.capabilities)


def test_eyes_is_not_declared_for_an_absent_or_unplugged_device_or_no_indicator():
    unplugged = FakeEyes(connected=True)
    unplugged.unplug()
    for indicator in (FakeEyes(connected=False), unplugged, NullIndicator(), None):
        assert "eyes" not in profile_for_eyes(indicator).capabilities


def test_asking_does_not_change_the_shared_profile():
    profile_for_eyes(FakeEyes(connected=True))
    assert "eyes" not in REACHY_MINI_PROFILE.capabilities
