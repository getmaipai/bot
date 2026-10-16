"""Firmware-faithful StackChan helpers and local peers for protocol tests."""

from .firmware import StackChanFirmware


class FakeHubVoiceReply:
    """Simulated per-utterance hub match, deliberately held in memory only."""

    def __init__(self, *, person_id="person-7abc12", level="confirmed"):
        self.speaker_evidence = {
            "person_id": person_id,
            "basis": "voice",
            "level": level,
        }


__all__ = ["FakeHubVoiceReply", "StackChanFirmware"]
