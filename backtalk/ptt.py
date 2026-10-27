# backtalk: talk to your Claude Code agent out loud.
# Copyright (C) 2026 Jared Rhodenizer
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.
#
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Hold-to-talk — a global key listener.

HOLD the key -> mic opens. RELEASE -> mic closes and the utterance is
processed. The button IS the voice-activity detector, which is why this
mode is speaker-safe with no headphones: the mic simply isn't open while
the assistant talks, unless you press the key — and pressing while it
talks interrupts it.

THE KEY-REPEAT TRAP (the bug that kills every naive build): the OS fires
on_press events CONTINUOUSLY while a key is held. Without the held-state
filter below, every repeat reads as a fresh press and keeps cancelling
the reply before it can speak.

AND THE HALF THAT TRAP HIDES: some keyboards send auto-repeat as full
DOWN/UP PAIRS rather than the repeated DOWN-only stream. Filtering the
presses and trusting every release then breaks the OTHER way -- a single
hold is chopped into dozens of ~50ms recordings, each too short to
transcribe, and the whole thing is SILENT. No exception, no log line,
nothing to search for; it simply reads as "the microphone does not work".
Measured in the field on a Logitech MX Mechanical through a Bolt
receiver: one 2.6-second hold produced 186 key events and about fifty
recordings. So a release is never trusted on sight -- see is_held().

macOS needs Input Monitoring permission for the hosting terminal
(System Settings -> Privacy & Security -> Input Monitoring). Windows
works out of the box; some Linux desktops need the user in the `input`
group or an X11 session.
"""
import threading
import time

from pynput import keyboard


def resolve_key(name: str):
    """'home' / 'f13' / 'right_alt' / any single character -> pynput key."""
    name = (name or "home").strip().lower()
    if len(name) == 1:
        return keyboard.KeyCode.from_char(name)
    # Friendly names -> pynput's names. pynput calls the right option key
    # alt_r, not right_alt; the docs speak human, this map translates.
    # (Field-caught: right_alt silently fell back to home, which Mac
    # laptops cannot press, so the voice looked healthy and never fired.)
    aliases = {
        "right_alt": "alt_r", "left_alt": "alt_l",
        "right_option": "alt_r", "left_option": "alt_l",
        "right_ctrl": "ctrl_r", "left_ctrl": "ctrl_l",
        "right_cmd": "cmd_r", "left_cmd": "cmd_l",
        "right_shift": "shift_r", "left_shift": "shift_l",
        "control": "ctrl", "command": "cmd", "option": "alt",
    }
    name = aliases.get(name, name)
    try:
        return getattr(keyboard.Key, name)
    except AttributeError:
        print(f"[ptt] unknown key {name!r} — falling back to 'home'",
              flush=True)
        return keyboard.Key.home


def parse_chord(name: str) -> list:
    """'shift+control+command+m' -> [Key.shift, Key.ctrl, Key.cmd, 'm'
    as a KeyCode]. A plain key with no '+' is a one-item chord, so a
    single key behaves exactly like it always has."""
    parts = [p.strip() for p in (name or "").split("+") if p.strip()]
    return [resolve_key(p) for p in parts]


def interrupt_key_conflicts(ptt_key: str, interrupt_key: str) -> bool:
    """True when the interrupt key names the same physical key as the
    talk key. Both use the same tap-to-fire listener, so a duplicate
    would race the talk key's own listener instead of doing anything —
    the caller should disable the second listener rather than create it."""
    if not interrupt_key:
        return False
    chord = parse_chord(interrupt_key)
    # A chord needs every key held at once; it can never equal the single
    # ptt_key, so only a lone key can conflict.
    if len(chord) != 1:
        return False
    return chord[0] == resolve_key(ptt_key)


def _decontrol(k):
    """Undo macOS's Control+letter translation. Holding Control turns the
    letter key's reported character into its C0 control code (Control+M
    arrives as '\\r', not 'm') even though the physical key is still M, so
    a chord that includes Control would otherwise never match its own
    configured letter. Only codes 1-26 are ASCII control codes for a-z;
    anything else (actual Tab/Enter/Backspace) arrives as a Key enum, not
    a KeyCode, and never reaches here."""
    if (isinstance(k, keyboard.KeyCode) and k.char is not None
            and len(k.char) == 1 and 1 <= ord(k.char) <= 26):
        return keyboard.KeyCode.from_char(chr(ord(k.char) + 96))
    return k


class ChordListener:
    """Tap-to-fire, but the 'key' is several keys held at once (e.g. an
    interrupt bound to shift+control+command+m so it can't be hit by
    accident). Fires once per full hold — every member down together —
    and re-arms only once every member has been released, so holding
    past the fire or re-pressing one key while others are still down
    can't fire it twice."""

    def __init__(self, keys):
        self._keys = set(keys)
        self._held = set()
        self._armed = True
        self._press_evt = threading.Event()
        self._listener = keyboard.Listener(on_press=self.on_press,
                                           on_release=self.on_release)
        self._listener.daemon = True
        self._listener.start()

    def on_press(self, k):
        k = _decontrol(k)
        if k not in self._keys:
            return
        self._held.add(k)
        if self._armed and self._held == self._keys:
            self._armed = False
            self._press_evt.set()

    def on_release(self, k):
        self._held.discard(_decontrol(k))
        if not self._held:
            self._armed = True

    def wait_press(self, timeout=None):
        fired = self._press_evt.wait(timeout)
        if fired:
            self._press_evt.clear()
        return fired


class PTTListener:
    # How long a release must stand unchallenged before it is believed.
    # Comfortably longer than any keyboard's auto-repeat period (measured
    # at ~50ms on the hardware that exposed this; Windows' fastest setting
    # is ~30ms) and short enough that letting go still feels instant.
    RELEASE_GRACE = 0.12

    def __init__(self, key="home"):
        self._key = resolve_key(key) if isinstance(key, str) else key
        self._held = False
        self._release_t = None          # a release awaiting confirmation
        self._press_evt = threading.Event()
        self._listener = keyboard.Listener(on_press=self._on_press,
                                           on_release=self._on_release)
        self._listener.daemon = True
        self._listener.start()

    def _on_press(self, k):
        if k != self._key:
            return
        # A press cancels any pending release: that release was auto-repeat,
        # not a human letting go.
        self._release_t = None
        if not self._held:                      # filter key-repeat
            self._held = True
            self._press_evt.set()

    def _on_release(self, k):
        if k == self._key:
            # PROVISIONAL. Believed only if no press follows; see _settle().
            self._release_t = time.monotonic()

    def _settle(self):
        """Commit a release that has stood unchallenged for the grace window."""
        r = self._release_t
        if self._held and r is not None and \
                time.monotonic() - r >= self.RELEASE_GRACE:
            self._held = False
            self._release_t = None

    def wait_press(self):
        """Block until the key goes DOWN (one event per physical press)."""
        # Settled on a loop, not once. A release landing after the last
        # is_held() poll leaves _held provisionally True, and a single
        # settle-then-wait would then block forever: the next press is
        # filtered as key-repeat, so nothing ever sets the event again.
        while True:
            self._settle()
            if self._press_evt.wait(timeout=self.RELEASE_GRACE):
                self._press_evt.clear()
                return

    def is_held(self) -> bool:
        self._settle()
        return self._held
