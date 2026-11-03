from aux_core.system_health import SystemHealthSampler


def test_system_health_sampler_has_dashboard_fields():
    sample = SystemHealthSampler().sample()
    expected = {
        "cpu_percent",
        "memory_percent",
        "memory_used_mb",
        "disk_percent",
        "cpu_temperature_c",
        "load_1m",
        "process_rss_mb",
        "hostname",
        "platform",
    }
    assert expected.issubset(sample)
    assert sample["sampled_monotonic_ns"] > 0
    assert isinstance(sample["hostname"], str)
    assert isinstance(sample["platform"], str)
