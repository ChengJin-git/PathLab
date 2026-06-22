import signal


def test_cancel_session_processes_sends_term_then_kill(monkeypatch):
    from backend.pathscientist.runtime import session_registry

    sent: list[tuple[int, int]] = []
    monkeypatch.setattr(session_registry.os, "killpg", lambda pgid, sig: sent.append((pgid, sig)))
    monkeypatch.setattr(session_registry.time, "sleep", lambda _seconds: None)

    session_registry.register_active_process(
        session_id="s-registry-stop",
        run_id="run_a",
        pid=111,
        pgid=222,
        tool_name="run_experiment",
    )

    result = session_registry.cancel_session_processes(
        "s-registry-stop",
        term_timeout=0.0,
        kill_timeout=0.0,
    )

    assert sent == [(222, signal.SIGTERM), (222, signal.SIGKILL)]
    assert result["active_process_count"] == 1
    assert result["terminated_process_groups"] == [222]
    assert result["sigterm_sent"] == [222]
    assert result["sigkill_sent"] == [222]
    assert session_registry.active_processes("s-registry-stop") == []
