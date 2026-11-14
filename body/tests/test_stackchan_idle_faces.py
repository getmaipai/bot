import random

from maipai_body.bodies.stackchan.idle_faces import FACES, IdleFaces


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def _run(seed=7):
    clock = FakeClock()
    shown = []
    idle = IdleFaces(shown.append, lambda: True, clock=clock, rng=random.Random(seed))
    return clock, shown, idle


def test_waits_at_least_30_seconds_and_looks_within_90_seconds():
    clock, shown, idle = _run()
    idle.tick(29.0)
    assert shown == []
    for second in range(30, 92):
        clock.now = float(second)
        idle.tick(clock.now)
        if shown:
            break
    assert shown
    assert clock.now <= 90.0


def test_never_repeats_a_face_or_looks_within_25_seconds():
    clock, shown, idle = _run()
    look_times = []
    previous = len(shown)
    for second in range(1, 5000):
        clock.now = float(second)
        idle.tick(clock.now)
        if len(shown) != previous:
            look_times.append(clock.now)
            previous = len(shown)
    assert len(shown) > 30
    assert all(a != b for a, b in zip(shown, shown[1:]))
    assert all(b - a >= 25 for a, b in zip(look_times, look_times[1:]))


def test_only_allowed_faces_are_used_over_500_looks():
    clock, shown, idle = _run()
    while len(shown) < 500:
        clock.now += 2
        idle.tick(clock.now)
    assert set(shown) <= {name for name, _weight in FACES}


def test_false_can_show_restarts_the_wait():
    clock = FakeClock()
    shown = []
    allowed = [True]
    idle = IdleFaces(shown.append, lambda: allowed[0], clock=clock, rng=random.Random(3))
    clock.now = 50
    allowed[0] = False
    idle.tick(clock.now)
    allowed[0] = True
    clock.now = 79
    idle.tick(clock.now)
    assert shown == []
    while not shown:
        clock.now += 1
        idle.tick(clock.now)
    assert clock.now >= 80


def test_happy_is_most_common_over_many_looks():
    clock, shown, idle = _run(seed=19)
    while len(shown) < 1200:
        clock.now += 2
        idle.tick(clock.now)
    assert shown.count("happy") > max(shown.count(face) for face in set(shown) - {"happy"})
