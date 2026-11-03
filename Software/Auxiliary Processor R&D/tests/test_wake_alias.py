from aux_core.engagement import EngagementManager


def cfg():
    return {
        "enabled": True,
        "wake_phrases": ["hey robot"],
        "wake_name": "TALUS",
        "wake_name_aliases": ["talus", "talos", "talis"],
        "wake_name_prefixes": ["hey", "okay", "ok"],
        "allow_bare_wake_name": True,
        "wake_score": 1.0,
        "idle_accept_score": 0.72,
        "active_window_s": 25,
    }


def test_stt_alias_wakes_talus_with_prefix():
    e = EngagementManager(cfg())
    r = e.evaluate("Hey Talos, can you see me?", {}, now=1)
    assert r["accept"] is True
    assert r["wake"]["canonical"] == "TALUS"
    assert r["wake"]["raw_alias"] == "talos"


def test_bare_alias_at_start_is_direct_address():
    e = EngagementManager(cfg())
    assert e.evaluate("Talus can you help me?", {}, now=1)["accept"] is True


def test_alias_in_middle_is_not_globally_rewritten_or_wake():
    e = EngagementManager(cfg())
    r = e.evaluate("Tell me about Talos from Greek mythology", {}, now=1)
    assert r["accept"] is False
    assert "wake" not in r


def test_existing_hey_robot_still_works():
    e = EngagementManager(cfg())
    assert e.evaluate("hey robot what time is it", {}, now=1)["accept"] is True


def test_wake_phrase_uses_token_boundaries():
    e = EngagementManager(cfg())
    assert e.evaluate("book robot design", {}, now=1)["accept"] is False
