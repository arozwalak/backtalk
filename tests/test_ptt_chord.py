"""A chord interrupt key (e.g. 'shift+control+command+m') needs every
named key resolved the same way a single key would be, so a chord is
just a list of the same key objects PTTListener already understands.
"""
from pynput import keyboard

from backtalk.ptt import ChordListener, parse_chord, resolve_key


def test_parse_chord_resolves_each_part_by_name():
    assert parse_chord("shift+control+command+m") == [
        resolve_key("shift"), resolve_key("control"),
        resolve_key("command"), resolve_key("m"),
    ]


def test_parse_chord_single_key_is_one_item_list():
    assert parse_chord("end") == [resolve_key("end")]


def test_chord_does_not_fire_on_partial_press():
    """Holding only some of the chord's keys must never fire it — a
    partial chord is indistinguishable from someone typing normally."""
    cl = ChordListener(parse_chord("shift+m"))
    cl.on_press(resolve_key("shift"))
    assert cl.wait_press(timeout=0.05) is False


def test_chord_fires_once_every_key_is_held_together():
    cl = ChordListener(parse_chord("shift+m"))
    cl.on_press(resolve_key("shift"))
    cl.on_press(resolve_key("m"))
    assert cl.wait_press(timeout=0.05) is True


def test_chord_does_not_refire_while_still_held():
    """Holding the chord doesn't repeat-fire — same spirit as PTTListener's
    key-repeat filter, just for a set of keys instead of one."""
    cl = ChordListener(parse_chord("shift+m"))
    cl.on_press(resolve_key("shift"))
    cl.on_press(resolve_key("m"))
    assert cl.wait_press(timeout=0.05) is True
    assert cl.wait_press(timeout=0.05) is False


def test_chord_fires_despite_control_translating_letter_to_control_code():
    """On macOS, holding Control turns the letter key's reported character
    into its C0 control code (Control+M arrives as '\\r', not 'm') even
    though the physical key is still M. The chord must fire anyway."""
    cl = ChordListener(parse_chord("control+m"))
    cl.on_press(resolve_key("control"))
    cl.on_press(keyboard.KeyCode.from_char("\r"))
    assert cl.wait_press(timeout=0.05) is True


def test_chord_refires_after_full_release_and_repress():
    cl = ChordListener(parse_chord("shift+m"))
    cl.on_press(resolve_key("shift"))
    cl.on_press(resolve_key("m"))
    assert cl.wait_press(timeout=0.05) is True
    cl.on_release(resolve_key("shift"))
    cl.on_release(resolve_key("m"))
    cl.on_press(resolve_key("shift"))
    cl.on_press(resolve_key("m"))
    assert cl.wait_press(timeout=0.05) is True
