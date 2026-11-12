from maipai_body.expression.rest import RestPolicy


def test_a_unit_that_just_connected_does_not_inherit_the_old_quiet_time():
    policy = RestPolicy(0.0, drowsy_after_s=120.0, asleep_after_s=300.0)
    assert policy.update(299.0, person_present=False, turn_active=False).stage == "drowsy"
    policy.reset(1000.0)
    assert policy.stage == "awake"
    assert policy.update(1010.0, person_present=False, turn_active=False).stage == "awake"
