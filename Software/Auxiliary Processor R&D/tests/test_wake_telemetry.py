from pathlib import Path

from aux_core.audio_loop import AudioConversationLoop


def test_audio_loop_accepts_telemetry_dependency():
    sentinel = object()
    loop = AudioConversationLoop({}, None, None, None, None, None, None, telemetry=sentinel)
    assert loop.telemetry is sentinel
