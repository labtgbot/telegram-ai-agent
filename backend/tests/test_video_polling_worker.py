"""Tests for the video polling worker CLI."""

from __future__ import annotations


def test_video_polling_parse_args_accepts_loop_options() -> None:
    from app.workers.video_polling import _parse_args

    args = _parse_args(["--loop", "--interval-s", "2.5", "--limit", "7"])

    assert args.loop is True
    assert args.interval_s == 2.5
    assert args.limit == 7


def test_video_polling_main_runs_single_pass_with_limit(monkeypatch, capsys) -> None:
    from app.workers import video_polling as worker_module

    captured: dict[str, int] = {}

    async def fake_pass(*, limit, composio=None):  # noqa: ANN001
        captured["limit"] = limit
        return [object(), object()]

    monkeypatch.setattr(worker_module, "run_video_polling_pass", fake_pass)

    code = worker_module.main(["--limit", "2"])

    assert code == 0
    assert captured == {"limit": 2}
    assert "video_jobs_polled=2" in capsys.readouterr().out


def test_video_polling_main_runs_loop_with_interval(monkeypatch) -> None:
    from app.workers import video_polling as worker_module

    captured: dict[str, float | int] = {}

    async def fake_loop(*, interval_s, limit, iterations=None):  # noqa: ANN001
        captured["interval_s"] = interval_s
        captured["limit"] = limit

    monkeypatch.setattr(worker_module, "run_video_polling_loop", fake_loop)

    code = worker_module.main(["--loop", "--interval-s", "3", "--limit", "5"])

    assert code == 0
    assert captured == {"interval_s": 3.0, "limit": 5}


def test_video_polling_main_returns_one_on_failure(monkeypatch) -> None:
    from app.workers import video_polling as worker_module

    async def fake_pass(*, limit, composio=None):  # noqa: ANN001
        raise RuntimeError("poll failed")

    monkeypatch.setattr(worker_module, "run_video_polling_pass", fake_pass)

    assert worker_module.main([]) == 1
