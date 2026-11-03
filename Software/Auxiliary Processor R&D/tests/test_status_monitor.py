from aux_core.status_monitor import ComponentStatusMonitor


def test_status_monitor_publishes_only_transitions():
    status = {"llm": "ready"}
    events = []
    monitor = ComponentStatusMonitor(
        lambda name, value: events.append((name, value)),
        {"llm": lambda: status["llm"]},
        period_s=2.0,
    )
    assert monitor.probe_once() == {"llm": "ready"}
    monitor.probe_once()
    status["llm"] = "offline"
    monitor.probe_once()
    assert events == [("llm", "ready"), ("llm", "offline")]
