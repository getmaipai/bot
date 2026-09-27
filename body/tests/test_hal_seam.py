"""Both the real client and the fake satisfy the same HAL seam methods."""

from __future__ import annotations

from maipai_body.bodies.reachy_mini.client import ReachyMiniClient
from maipai_body.bodies.reachy_mini.fake import FakeReachyMiniClient

_SEAM_METHODS = {
    "HeadActuator": ["goto", "set_target", "hold", "enable", "disable"],
    "AudioIO": ["get_audio_sample", "push_audio_sample", "get_doa"],
    "Camera": ["get_frame"],
    "Imu": ["read"],
    "StateFeed source": ["state_feed"],
}


def test_fake_and_client_both_implement_the_seam_methods():
    for kind in (ReachyMiniClient, FakeReachyMiniClient):
        for protocol_name, methods in _SEAM_METHODS.items():
            for method in methods:
                assert hasattr(kind, method), f"{kind.__name__} is missing {protocol_name}.{method}"
