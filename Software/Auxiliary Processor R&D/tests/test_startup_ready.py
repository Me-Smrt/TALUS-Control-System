"""Offline tests for fail-closed TALUS voice startup readiness."""
from __future__ import annotations

import ast
import importlib.util
import threading
from pathlib import Path

import pytest

from aux_core.startup_ready import DEFAULT_READY_MESSAGE, StartupNotReady, StartupReadyGate
from aux_core.state import AuxiliaryState


class FakeTts:
    def __init__(self):
        self.calls = []

    def synthesize(self, text, *, language=None, voice_id=None):
        self.calls.append((text, language, voice_id))
        return b"fake wav", {"id": "user-selected-voice"}


def test_starts_locked_and_sets_phase_in_state():
    state = AuxiliaryState()
    gate = StartupReadyGate(state)
    assert not gate.ready
    assert state.snapshot()["startup"]["phase"] == "initializing"
    with pytest.raises(StartupNotReady):
        gate.require_ready()


def test_uses_active_tts_voice_and_announces_once():
    state = AuxiliaryState()
    gate = StartupReadyGate(state)
    tts = FakeTts()
    events = []

    def player(wav):
        events.append((wav, gate.ready))

    assert gate.announce(tts, play=player) is True
    assert gate.announce(tts, play=player) is False
    assert tts.calls == [(DEFAULT_READY_MESSAGE, "en", None)]
    assert events == [(b"fake wav", False)]
    assert gate.ready
    assert state.snapshot()["startup"]["phase"] == "ready"
    gate.require_ready()


def test_blocks_other_thread_through_entire_playback():
    started = threading.Event()
    finish = threading.Event()
    gate = StartupReadyGate()
    failure = []

    def player(wav):
        started.set()
        if not finish.wait(3.0):
            failure.append("timed out")

    thread = threading.Thread(target=lambda: gate.announce(FakeTts(), play=player))
    thread.start()
    try:
        assert started.wait(1.0)
        assert not gate.ready
        with pytest.raises(StartupNotReady):
            gate.require_ready()
    finally:
        finish.set()
        thread.join(2)
    assert not failure
    assert gate.ready


def test_fail_closed_on_tts_failure():
    gate = StartupReadyGate()
    with pytest.raises(RuntimeError, match="speaker disconnected"):
        gate.announce(FakeTts(), play=lambda wav: (_ for _ in ()).throw(RuntimeError("speaker disconnected")))
    assert not gate.ready
    assert gate.phase == "failed"
    with pytest.raises(StartupNotReady):
        gate.require_ready()


def test_fail_closed_if_mic_dies_during_playback():
    gate = StartupReadyGate()
    with pytest.raises(RuntimeError, match="mic stopped"):
        gate.announce(FakeTts(), play=lambda wav: None, verify_ready=lambda: (_ for _ in ()).throw(RuntimeError("mic stopped")))
    assert not gate.ready


def test_main_wires_startup_gate_before_console_input():
    """The current main.py owns readiness; no installer tool is needed."""
    here = Path(__file__).resolve().parents[1]
    main_text = (here / "main.py").read_text(encoding="utf-8")
    tree = ast.parse(main_text)
    imports = [node for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert any(node.module == "aux_core.startup_ready" and
               any(alias.name == "StartupReadyGate" for alias in node.names)
               for node in imports)
    assert "startup_gate = StartupReadyGate(state)" in main_text
    assert "conversation.startup_gate = startup_gate" in main_text
    assert main_text.index("startup_gate.announce(tts") < main_text.index("if a.listen:")
    assert 'text = input("you> "' in main_text


def test_listening_loop_gates_capture_through_greeting():
    """Live audio must release capture only after the greeting completes."""
    here = Path(__file__).resolve().parents[1]
    source = (here / "aux_core" / "audio_loop.py").read_text(encoding="utf-8")
    ast.parse(source)
    assert "capture_ready.wait(" in source
    assert "gate.announce(" in source
    assert "capture_allowed.set()" in source
    assert source.index("gate.announce(") < source.index("capture_allowed.set()")


def test_conversation_input_rejected_before_ready():
    from aux_core.conversation import ConversationManager

    conv = ConversationManager.__new__(ConversationManager)
    conv.startup_gate = StartupReadyGate()
    # This fails before a model, detector, network, or history is needed.
    with pytest.raises(StartupNotReady):
        conv.handle_text("hello")


def test_explicit_voice_selection_is_respected():
    class Registry:
        active_id = "chosen-voice"
        active_set_id = None

    gate = StartupReadyGate()
    tts = FakeTts()
    tts.registry = Registry()
    gate.announce(tts, play=lambda wav: None)
    assert tts.calls == [(DEFAULT_READY_MESSAGE, "en", "chosen-voice")]


def test_selected_voice_set_does_not_force_a_single_voice_id():
    class Registry:
        active_id = "preview-of-active-set"
        active_set_id = "voice-set-male"

    gate = StartupReadyGate()
    tts = FakeTts()
    tts.registry = Registry()
    gate.announce(tts, play=lambda wav: None)
    assert tts.calls == [(DEFAULT_READY_MESSAGE, "en", None)]


def test_http_conversation_returns_503_until_greeting_finishes():
    import json
    import urllib.error
    import urllib.request

    from aux_core.api_server import AuxApiServer

    class FakeConversation:
        startup_gate = StartupReadyGate()

        def handle_text(self, text, **kwargs):
            self.startup_gate.require_ready()
            return {"reply": "ok"}

        def clear_history(self, reason):
            pass

    conv = FakeConversation()
    api = AuxApiServer({"bind_host": "127.0.0.1", "port": 0}, AuxiliaryState(), FakeTts(), None, conv)
    api.start()
    try:
        url = f"http://127.0.0.1:{api.port}/v1/conversation/text"

        def request():
            req = urllib.request.Request(url, data=b'{"text":"hello"}', headers={"Content-Type": "application/json"}, method="POST")
            return urllib.request.urlopen(req, timeout=3)

        with pytest.raises(urllib.error.HTTPError) as error:
            request()
        assert error.value.code == 503
        assert json.loads(error.value.read())["error"] == "startup_not_ready"
        conv.startup_gate.announce(FakeTts(), play=lambda wav: None)
        with request() as response:
            assert response.status == 200
            assert json.load(response)["reply"] == "ok"
    finally:
        api.stop()
