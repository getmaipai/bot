"""Say that again, what did I miss: phrases, caps, the missed log, and the bridge with fakes."""

from __future__ import annotations

import asyncio
from datetime import datetime

import pytest

import maipai_body.bodies.stackchan.turn as turn_module
from maipai_body.bodies.stackchan.announce import Announcer
from maipai_body.bodies.stackchan.orientation import OrientationReactions
from maipai_body.bodies.stackchan.repeat import (
    KEEP_REPLIES,
    MAX_MISSED,
    NOTHING_MISSED,
    NOTHING_TO_REPEAT,
    MissedLog,
    RepeatControl,
    ReplyStore,
    parse_repeat_command,
)
from maipai_body.bodies.stackchan.timers import TimerService
from maipai_body.bodies.stackchan.volume import VolumeControl
from maipai_body.speech.stt_stream import SttStreamResult
from tests.test_stackchan_turn import (  # type: ignore[import-not-found]
    FakeCapture,
    FakeServer,
    FakeTts,
    FakeTurn,
    InlineExecutor,
    Link,
    Offline,
)

AGAIN = [
    "say that again", "What did you say?", "Repeat that.", "say it again", "come again",
    "pardon", "sorry what", "can you repeat that", "what was that", "Hey StackChan, say that again",
    "could you say that again", "repeat that please", "say it one more time",
]  # fmt: skip
MISSED = [
    "what did I miss", "did I miss anything", "anything happen", "what have I missed",
]  # fmt: skip


@pytest.mark.parametrize("text", AGAIN)
def test_every_repeat_phrase_is_answered_on_the_robot(text):
    assert parse_repeat_command(text).kind == "again"


@pytest.mark.parametrize("text", MISSED)
def test_every_missed_phrase_is_answered_on_the_robot(text):
    assert parse_repeat_command(text).kind == "missed"


def test_louder_and_slower_variants():
    assert parse_repeat_command("say that louder").kind == "louder"
    assert parse_repeat_command("can you say it louder").kind == "louder"
    assert parse_repeat_command("say that slower").kind == "slower"
    assert parse_repeat_command("repeat that more slowly").kind == "slower"


@pytest.mark.parametrize(
    "text",
    [
        "what did you say about dinner yesterday",
        "what did you say earlier",
        "what did you say when we talked about the trip",
        "repeat that back to me in french please now",
        "can you say that again but slower",
        "what was that song about",
        "tell me what did I miss on the news",
        "",
        None,
    ],
)
def test_longer_or_topical_asks_fall_through_to_the_hub(text):
    assert parse_repeat_command(text) is None


def test_the_store_keeps_five_per_session():
    store = ReplyStore()
    for i in range(KEEP_REPLIES + 3):
        store.add("a", f"reply {i}", [b"x" * 10])
    assert store.count("a") == KEEP_REPLIES
    assert store.last("a").text == f"reply {KEEP_REPLIES + 2}"
    assert store.last("other") is None


def test_the_store_stays_under_its_memory_cap_dropping_the_oldest():
    store = ReplyStore(max_bytes=1000)
    for i in range(20):
        assert store.add("s", f"r{i}", [b"x" * 300])
    assert store.total_bytes() <= 1000
    assert store.last("s").text == "r19"
    assert not store.add("s", "huge", [b"x" * 5000])  # alone larger than the cap: not kept
    assert store.last("s").text == "r19"


def test_the_default_cap_is_about_five_megabytes():
    from maipai_body.bodies.stackchan.repeat import MAX_BYTES

    assert 4 * 1024 * 1024 <= MAX_BYTES <= 6 * 1024 * 1024


def at(hour, minute):
    return datetime(2026, 11, 13, hour, minute).timestamp()


def test_the_missed_summary_wording():
    now = at(18, 30)
    log = MissedLog(clock=lambda: now)
    assert log.summary() == NOTHING_MISSED
    log.note("announcement", "Dinner is ready", at(18, 2))
    assert log.summary() == "While you were away: dinner is ready at 6:02."
    log.note("timer", "your timer finished", at(18, 10))
    assert log.summary() == (
        "While you were away: dinner is ready at 6:02 and your timer finished at 6:10."
    )
    log.note("alarm", "your alarm went off", at(18, 20))
    assert log.summary().endswith("6:10 and your alarm went off at 6:20.")


def test_the_missed_list_is_capped_aged_and_short_to_say():
    now = [at(18, 30)]
    log = MissedLog(clock=lambda: now[0])
    for i in range(MAX_MISSED + 5):
        log.note("announcement", f"Item {i}", now[0])
    assert log.count() == MAX_MISSED
    assert log.summary().endswith("and 15 more.")
    now[0] += 25 * 3600  # a day later everything has aged out
    assert log.count() == 0 and log.summary() == NOTHING_MISSED


def test_announcements_refused_while_muted_quiet_or_at_night_are_logged():
    for flag in ("muted", "quiet", "night"):
        log = MissedLog()
        state = {"night": flag == "night"}
        announcer = Announcer(
            show=lambda text: True,
            say=lambda text: True,
            night=lambda: state["night"],
            clock=lambda: 0.0,
            missed=log.note,
        )
        if flag in ("muted", "quiet"):
            setattr(announcer, flag, True)
        assert announcer.handle({"text": "Dinner is ready"})["status"] == "refused"
        assert log.count() == 1 and "dinner is ready" in log.summary()
    # urgent at night is delivered, so nothing was missed; a disabled feature is not "missed"
    log = MissedLog()
    announcer = Announcer(
        show=lambda t: True, say=lambda t: True, night=lambda: True, clock=lambda: 0.0,
        missed=log.note,
    )  # fmt: skip
    assert announcer.handle({"text": "Smoke", "urgent": True})["status"] == "delivered"
    announcer.enabled = False
    announcer.handle({"text": "Later"})
    assert log.count() == 0


def test_an_announcement_nobody_was_in_view_for_is_logged_after_it_is_said():
    log = MissedLog()
    view = {"seen": None}
    announcer = Announcer(
        show=lambda t: True,
        say=lambda t: True,
        clock=lambda: 0.0,
        missed=log.note,
        in_view=lambda: view["seen"],
    )
    announcer.handle({"text": "Dinner is ready"})
    announcer.tick()
    assert log.count() == 0  # unknown (camera off): not claimed missed
    view["seen"] = True
    announcer.handle({"text": "Dinner is ready"})
    announcer.tick()
    assert log.count() == 0
    view["seen"] = False
    announcer.handle({"text": "Dinner is ready"})
    announcer.tick()
    assert log.count() == 1


def test_an_announcement_that_could_not_be_said_in_time_is_logged():
    log = MissedLog()
    state = {"now": 0.0}
    announcer = Announcer(
        show=lambda t: True, say=lambda t: False, clock=lambda: state["now"], missed=log.note
    )
    announcer.handle({"text": "Time to go"})
    announcer.tick()
    assert log.count() == 0
    state["now"] = 13.0
    announcer.tick()
    assert log.count() == 1


def make_timers(log, *, muted=False, night=False):
    state = {"muted": muted, "night": night, "now": 0.0, "busy": False}
    timers = TimerService(
        lambda name, args: {},
        say=lambda text: not state["busy"],
        muted=lambda: state["muted"],
        night=lambda: state["night"],
        clock=lambda: state["now"],
        missed=log.note,
    )
    return timers, state


def test_a_timer_that_rang_while_muted_or_in_quiet_hours_is_logged():
    for kwargs in ({"muted": True}, {"night": True}):
        log = MissedLog()
        timers, _ = make_timers(log, **kwargs)
        timers.on_event("timer_fired", {"id": 1, "what": "timer"})
        timers.on_event("timer_fired", {"id": 2, "what": "alarm", "label": "school"})
        text = log.summary()
        assert "your timer finished" in text and "your school alarm went off" in text


def test_a_timer_line_never_said_is_logged_but_a_said_one_is_not():
    log = MissedLog()
    timers, state = make_timers(log)
    timers.on_event("timer_fired", {"id": 1, "what": "timer"})
    timers.tick()
    assert log.count() == 0  # said
    state["busy"] = True
    timers.on_event("timer_fired", {"id": 2, "what": "timer", "label": "pasta"})
    timers.tick()
    state["now"] = 100.0
    timers.tick()
    assert "your pasta timer finished" in log.summary()


def test_an_orientation_line_skipped_at_night_is_logged_but_not_other_skips():
    log = MissedLog()
    quiet = {"why": "night mode is on"}
    reactions = OrientationReactions(
        face=lambda e: None,
        say=lambda line: True,
        rotate=lambda d: None,
        hold_motion=lambda held: None,
        quiet=lambda: quiet["why"],
        missed=log.note,
    )
    reactions.on_event({"axis": "-y"})
    assert log.count() == 1 and "upside down" in log.summary()
    quiet["why"] = "asleep"
    reactions.on_event({"axis": "-x"})
    assert log.count() == 1
    quiet["why"] = "night mode is on"
    reactions.on_event({"axis": "+y"})  # back upright: nothing to tell
    assert log.count() == 1


# ---- the bridge, with fakes ----


class RecordingPlayback:
    """Plays like the real one for the parts the bridge touches; frames come from the TTS fake."""

    created: list = []
    replays: list = []

    def __init__(self, server, device, **kwargs):
        self.frames: list[bytes] = []
        self.on_first_audio = None
        RecordingPlayback.created.append(self)

    def recorded_frames(self):
        return list(self.frames)

    def replay_frames(self, frames):
        RecordingPlayback.replays.append(list(frames))

    def stop(self):
        pass

    def end(self):
        pass

    def flush(self):
        pass


class FramingTts(FakeTts):
    def speak(self, text, *, stop_event=None):
        super().speak(text, stop_event=stop_event)
        self.playback.frames.append(("frame:" + text).encode())


class ScriptedStt:
    heard: list[str] = []

    def __init__(self, base, cookie):
        pass

    def run(self, capture, **kwargs):
        return SttStreamResult(kind="final", text=ScriptedStt.heard.pop(0))


class Harness:
    def __init__(self, monkeypatch, *, volume=None, muted=False, person=None, base_ok=True):
        monkeypatch.setattr(turn_module, "StackChanAudioPlayback", RecordingPlayback)
        RecordingPlayback.created, RecordingPlayback.replays = [], []
        FakeTurn.streams, FakeTurn.urls = [], []
        FakeTts.sentences = []
        self.log = MissedLog()
        self.state = {"muted": muted, "person": person}
        self.control = RepeatControl(missed=self.log, muted=lambda: self.state["muted"])
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        server = FakeServer()
        server._loop = self.loop
        self.bridge = turn_module.StackChanTurnBridge(
            server,
            Link(),
            Offline(),
            stt_factory=ScriptedStt,
            turn_factory=FakeTurn,
            tts_factory=FramingTts,
            side_executor=InlineExecutor(),
            repeat_control=self.control,
            volume_control=volume,
            person_attribution=lambda result: (
                {"person_id": self.state["person"], "level": "confirmed"}
                if self.state["person"]
                else None
            ),
        )

    def say(self, text, session="s1"):
        ScriptedStt.heard = [text]
        self.loop.run_until_complete(self.bridge._run(session, "device", FakeCapture()))

    def close(self):
        self.loop.close()


@pytest.fixture
def harness(monkeypatch):
    made = []

    def build(**kwargs):
        h = Harness(monkeypatch, **kwargs)
        made.append(h)
        return h

    yield build
    for h in made:
        h.close()


def test_the_last_reply_is_replayed_verbatim_without_asking_the_hub(harness):
    h = harness()
    h.say("hello")
    assert len(FakeTurn.streams) == 1
    sent = RecordingPlayback.created[0].frames
    h.say("say that again")
    assert len(FakeTurn.streams) == 1  # no second hub call
    assert RecordingPlayback.replays == [sent]
    assert FakeTts.sentences == ["Hello there.", "How are you?"]  # nothing synthesized again


def test_again_twice_replays_the_same_reply_twice(harness):
    h = harness()
    h.say("hello")
    h.say("what did you say")
    h.say("repeat that")
    assert len(RecordingPlayback.replays) == 2
    assert RecordingPlayback.replays[0] == RecordingPlayback.replays[1]
    assert len(FakeTurn.streams) == 1


def test_nothing_to_repeat_says_so(harness):
    h = harness()
    h.say("say that again")
    assert FakeTts.sentences == [NOTHING_TO_REPEAT]
    assert FakeTurn.streams == [] and RecordingPlayback.replays == []


def test_hard_mute_keeps_repeat_silent_and_does_not_record(harness):
    h = harness(muted=True)
    h.control.record("s1", "private reply", [b"private audio"])
    h.say("say that again")
    assert FakeTurn.streams == []
    assert RecordingPlayback.replays == []
    assert FakeTts.sentences == []
    assert h.control.store.last("s1") is None


def test_a_longer_ask_goes_to_the_hub_unchanged(harness):
    h = harness()
    h.say("hello")
    h.say("what did you say about dinner yesterday")
    assert [text for text, _ in FakeTurn.streams] == [
        "hello",
        "what did you say about dinner yesterday",
    ]
    assert RecordingPlayback.replays == []


def test_replies_are_per_session(harness):
    h = harness()
    h.say("hello", session="s1")
    h.say("say that again", session="s2")
    assert RecordingPlayback.replays == []
    assert FakeTts.sentences[-1] == NOTHING_TO_REPEAT


def test_a_reply_said_to_another_known_person_is_not_replayed(harness):
    h = harness(person="person-aaaaaa")
    h.say("hello")
    h.state["person"] = "person-bbbbbb"
    h.say("say that again")
    assert RecordingPlayback.replays == []
    assert FakeTts.sentences[-1] == NOTHING_TO_REPEAT
    h.state["person"] = None  # speaker not known: same session, so it replays
    h.say("say that again")
    assert len(RecordingPlayback.replays) == 1


def test_louder_bumps_the_volume_one_step_for_the_replay_then_puts_it_back(harness):
    levels = []
    volume = VolumeControl(lambda name, args: {"audio_speaker": {"volume": 50}}, levels.append)
    h = harness(volume=volume)
    h.say("hello")
    h.say("say that louder")
    assert len(RecordingPlayback.replays) == 1
    assert levels == [65, 50]


def test_louder_with_nothing_to_repeat_stays_a_volume_command(harness):
    levels = []
    volume = VolumeControl(lambda name, args: {"audio_speaker": {"volume": 50}}, levels.append)
    h = harness(volume=volume)
    h.say("say that louder")
    assert levels == [65]
    assert FakeTts.sentences == ["Volume 65."]


def test_muted_stays_silent_and_keeps_the_missed_list(harness):
    h = harness()
    h.say("hello")
    h.log.note("timer", "your timer finished", at(18, 10))
    h.state["muted"] = True
    h.say("say that again")
    h.say("what did I miss")
    assert RecordingPlayback.replays == [] and len(FakeTurn.streams) == 1
    assert FakeTts.sentences == ["Hello there.", "How are you?"]
    assert h.log.count() == 1


def test_what_did_i_miss_speaks_the_summary_then_clears(harness):
    h = harness()
    h.log.note("announcement", "Dinner is ready", at(18, 2))
    h.log.note("timer", "your timer finished", at(18, 10))
    h.say("what did I miss")
    assert FakeTts.sentences == [
        "While you were away: dinner is ready at 6:02 and your timer finished at 6:10."
    ]
    assert h.log.count() == 0
    h.say("did I miss anything")
    assert FakeTts.sentences[-1] == NOTHING_MISSED
    assert FakeTurn.streams == []


def test_off_means_the_hub_answers_and_nothing_is_kept(harness):
    h = harness()
    h.control.apply_settings({"robot.repeat.enabled": False})
    h.say("hello")
    h.say("say that again")
    assert [t for t, _ in FakeTurn.streams] == ["hello", "say that again"]
    assert h.control.store.count() == 0
    h.control.apply_settings({"robot.repeat.enabled": True})
    h.say("hello")
    assert h.control.store.count() == 1


def test_the_real_playback_records_what_it_encodes_and_replays_it():
    import numpy as np

    sent: list[list[bytes]] = []

    class Server:
        _loop = None

        async def send_audio(self, device_id, frames, **kwargs):
            sent.append(list(frames))

        async def stop_audio(self, device_id):
            pass

    loop = asyncio.new_event_loop()
    import threading

    threading.Thread(target=loop.run_forever, daemon=True).start()
    server = Server()
    server._loop = loop
    playback = turn_module.StackChanAudioPlayback(
        server, "d", sleeper=lambda s: None, async_sleep=lambda s: asyncio.sleep(0)
    )
    playback.push_audio_sample(np.sin(np.linspace(0, 400, 24000)).astype(np.float32) * 0.3)
    playback.end_sentence()
    playback.stop_playing()
    recorded = playback.recorded_frames()
    assert recorded
    first = [f for batch in sent for f in batch]
    assert first == recorded
    sent.clear()
    second = turn_module.StackChanAudioPlayback(
        server, "d", sleeper=lambda s: None, async_sleep=lambda s: asyncio.sleep(0)
    )
    second.replay_frames(recorded)
    assert [f for batch in sent for f in batch] == recorded
    assert second.recorded_frames() == []  # a replay is not kept again
    loop.call_soon_threadsafe(loop.stop)
