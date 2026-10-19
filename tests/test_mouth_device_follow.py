"""Mouth follows the system OUTPUT device when it changes.

A long-lived stream (audio law #1) is bound to the device it opened on;
CoreAudio never re-routes a running stream when the user changes the
system default output later (e.g. AirPods connect after open). So
Mouth._get_out must compare the current default with the device behind
the held stream and rebuild when they differ.
"""

from unittest.mock import MagicMock, patch

from backtalk.mouth import Mouth


def _fresh_mouth():
    """A Mouth without its threads — just the stream fields _get_out needs."""
    m = Mouth.__new__(Mouth)
    m._out = None
    m._out_rate = None
    m._out_device = None
    return m


def test_get_out_opens_on_current_default_device():
    with patch("backtalk.mouth.sd") as mock_sd:
        mock_sd.query_devices.return_value = {"name": "MacBook Pro Speakers", "index": 0}
        first = MagicMock()
        mock_sd.OutputStream.return_value = first

        m = _fresh_mouth()
        m._get_out(44100)

        assert mock_sd.OutputStream.call_count == 1
        assert m._out is first
        assert m._out_device == "MacBook Pro Speakers"


def test_get_out_reuses_stream_when_default_unchanged():
    with patch("backtalk.mouth.sd") as mock_sd:
        mock_sd.query_devices.return_value = {"name": "MacBook Pro Speakers", "index": 0}
        stream = MagicMock()
        mock_sd.OutputStream.return_value = stream

        m = _fresh_mouth()
        m._get_out(44100)
        m._get_out(44100)

        assert mock_sd.OutputStream.call_count == 1
        stream.start.assert_called_once()


def test_get_out_reopens_when_user_switches_default_output():
    """AirPods become the system default -> the next sentence plays there."""
    with patch("backtalk.mouth.sd") as mock_sd:
        # First playback: default is the built-in speakers.
        mock_sd.query_devices.return_value = {"name": "MacBook Pro Speakers", "index": 0}
        speakers_stream, airpods_stream = MagicMock(), MagicMock()
        mock_sd.OutputStream.side_effect = [speakers_stream, airpods_stream]

        m = _fresh_mouth()
        m._get_out(44100)
        assert m._out is speakers_stream

        # The user flips the system output to AirPods; nothing else changes
        # (same rate, stream healthy) — the device tracking must notice.
        mock_sd.query_devices.return_value = {"name": "AirPods Pro", "index": 3}
        reopened = m._get_out(44100)

        assert reopened is airpods_stream
        assert speakers_stream.close.call_count == 1
        assert m._out_device == "AirPods Pro"


def test_get_out_keeps_stream_when_only_rate_guard_differs():
    """A rate change still rebuilds (ElevenLabs 44.1k <-> Kokoro 24k), as before."""
    with patch("backtalk.mouth.sd") as mock_sd:
        mock_sd.query_devices.return_value = {"name": "MacBook Pro Speakers", "index": 0}
        first, second = MagicMock(), MagicMock()
        mock_sd.OutputStream.side_effect = [first, second]

        m = _fresh_mouth()
        m._get_out(44100)
        m._get_out(24000)

        assert mock_sd.OutputStream.call_count == 2
        assert m._out is second