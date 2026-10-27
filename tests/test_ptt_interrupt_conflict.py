"""The interrupt key and the talk key share the same tap-to-fire listener
design. If a user points both at the same physical key, wiring up a second
listener wouldn't add a feature — it would just race the first one for the
same key-down event. The guard below is what main.py consults before
creating that second listener at all.
"""
from backtalk.ptt import interrupt_key_conflicts


def test_same_key_conflicts():
    assert interrupt_key_conflicts("end", "end") is True


def test_different_keys_do_not_conflict():
    assert interrupt_key_conflicts("right_cmd", "end") is False


def test_empty_interrupt_key_never_conflicts():
    """Empty interrupt_key means "feature off" — never a conflict."""
    assert interrupt_key_conflicts("end", "") is False


def test_aliased_spelling_of_the_same_key_conflicts():
    """'right_cmd' and 'cmd_r' name the same physical key."""
    assert interrupt_key_conflicts("right_cmd", "cmd_r") is True


def test_chord_interrupt_key_never_conflicts_with_default_ptt_key():
    """An unparseable multi-key name must not silently fall back to the
    default key ('home') and then read as a false conflict against a
    ptt_key of 'home' — a chord is structurally never equal to a single
    key, so it can never conflict."""
    assert interrupt_key_conflicts("home", "shift+control+command+m") is False
