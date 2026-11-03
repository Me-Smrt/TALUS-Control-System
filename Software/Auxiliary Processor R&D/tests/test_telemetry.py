import json
from pathlib import Path

from aux_core.telemetry import TelemetryStore


def test_telemetry_rolls_up_turn_metrics(tmp_path: Path):
    store = TelemetryStore({"enabled": True, "path": "runtime/telemetry.jsonl", "dashboard_window": 10}, tmp_path)
    store.record_turn({
        "turn_ms": 1000,
        "reasoning_mode": "fast",
        "visual_used": False,
        "rag_attempted": True,
        "rag_hits": 2,
        "llm": {"total_ms": 800, "ttft_ms": 100, "tokens_per_second": 20, "completion_tokens": 40, "token_count_source": "api", "finish_reason": "stop"},
    })
    store.record_turn({
        "turn_ms": 2000,
        "reasoning_mode": "deep",
        "visual_used": True,
        "rag_attempted": False,
        "rag_hits": 0,
        "llm": {"total_ms": 1600, "ttft_ms": None, "tokens_per_second": 30, "completion_tokens": 60, "token_count_source": "estimated", "finish_reason": "stop"},
    })
    snap = store.snapshot()
    assert snap["window_turns"] == 2
    assert snap["averages"]["tokens_per_second"] == 25
    assert snap["averages"]["turn_ms"] == 1500
    assert snap["rates"]["deep_reasoning"] == 0.5
    assert snap["rates"]["vision_used"] == 0.5
    assert snap["rates"]["rag_hit_when_attempted"] == 1.0
    assert snap["rates"]["exact_llm_token_count"] == 0.5
    lines = (tmp_path / "runtime/telemetry.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["event_type"] == "conversation_turn"


def test_stt_eval_telemetry_is_separate_from_conversation_average(tmp_path: Path):
    store = TelemetryStore({"enabled": True, "path": "telemetry.jsonl"}, tmp_path)
    store.record_stt_eval({"rtf": 0.25, "wer": 0.1, "expected_language": "en", "detected_language": "en"})
    snap = store.snapshot()
    assert snap["window_turns"] == 0
    assert snap["averages"]["stt_rtf"] == 0.25
    assert snap["averages"]["stt_wer"] == 0.1
