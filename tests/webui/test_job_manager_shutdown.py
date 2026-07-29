from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import pytest

from powers_tool_webui.jobs import JobManager, JobStatus


def test_idle_shutdown_succeeds_and_is_repeatable() -> None:
    async def check() -> None:
        manager = JobManager()

        await manager.shutdown(timeout_s=0)
        await manager.shutdown(timeout_s=0)

        assert manager.active_job_id is None

    asyncio.run(check())


def test_shutdown_cancels_active_job_and_waits_for_terminal_state() -> None:
    async def check() -> None:
        manager = JobManager()
        job_id = await manager.submit_job(
            "output-on",
            {"resource": "USB0::FAKE::INSTR", "simulate": False, "dry_run": False},
            {"channel": 1},
        )
        assert await manager.start_job(job_id) is True

        async def complete_after_cancellation() -> None:
            while not manager.jobs[job_id].cancel_requested:
                await asyncio.sleep(0)
            await manager.complete_cancel(job_id)

        worker = asyncio.create_task(complete_after_cancellation())
        await manager.shutdown(timeout_s=0.5)
        await worker

        assert manager.jobs[job_id].status == JobStatus.CANCELLED
        assert manager.active_job_id is None

    asyncio.run(check())


def test_shutdown_cancels_simulation_background_job() -> None:
    async def check() -> None:
        manager = JobManager()
        job_id = await manager.submit_job(
            "sequence",
            {"simulate": True, "dry_run": False},
            {"document": {"version": 2, "steps": []}},
        )
        assert await manager.start_job(job_id) is True
        assert manager.active_job_id is None

        async def complete_after_cancellation() -> None:
            while not manager.jobs[job_id].cancel_requested:
                await asyncio.sleep(0)
            await manager.complete_cancel(job_id)

        worker = asyncio.create_task(complete_after_cancellation())
        await manager.shutdown(timeout_s=0.5)
        await worker

        assert manager.jobs[job_id].status == JobStatus.CANCELLED

    asyncio.run(check())


def test_shutdown_waits_for_live_data_io_to_finish() -> None:
    async def check() -> None:
        manager = JobManager()
        job_id = await manager.submit_job(
            "live-data",
            {"resource": "USB0::FAKE::INSTR", "simulate": False, "dry_run": False},
            {"interval_ms": 50},
        )
        assert await manager.start_job(job_id) is True
        job = manager.jobs[job_id]
        job.io_in_progress = True
        cancellation_seen = asyncio.Event()
        release_live_io = asyncio.Event()

        async def finish_live_io_after_cancellation() -> None:
            while not job.cancel_requested:
                await asyncio.sleep(0)
            cancellation_seen.set()
            await release_live_io.wait()
            job.io_in_progress = False
            await manager.complete_cancel(job_id)

        worker = asyncio.create_task(finish_live_io_after_cancellation())
        shutdown_task = asyncio.create_task(manager.shutdown(timeout_s=0.5))
        await cancellation_seen.wait()

        assert job.status == JobStatus.CANCEL_REQUESTED
        assert shutdown_task.done() is False

        release_live_io.set()
        await shutdown_task
        await worker

        assert job.status == JobStatus.CANCELLED
        assert job.io_in_progress is False

    asyncio.run(check())


def test_shutdown_waits_for_live_data_blocked_on_hardware_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from powers_tool_webui import app as web_app
    from powers_tool_webui import commands

    async def check() -> None:
        manager = JobManager()
        monkeypatch.setattr(web_app, "job_manager", manager)

        read_calls = 0

        def fake_live_panel_read(*_args, **_kwargs):
            nonlocal read_calls
            read_calls += 1
            return {}

        monkeypatch.setattr(commands, "execute_live_panel_read", fake_live_panel_read)

        original_hardware_io = manager.hardware_io
        lock_attempts = 0
        live_waiting_for_lock = asyncio.Event()

        @asynccontextmanager
        async def observed_hardware_io():
            nonlocal lock_attempts
            lock_attempts += 1
            if lock_attempts == 2:
                live_waiting_for_lock.set()
            async with original_hardware_io():
                yield

        monkeypatch.setattr(manager, "hardware_io", observed_hardware_io)

        release_real_io = asyncio.Event()
        real_io_acquired = asyncio.Event()

        async def hold_real_hardware_io() -> None:
            async with manager.hardware_io():
                real_io_acquired.set()
                await release_real_io.wait()

        real_io_task = asyncio.create_task(hold_real_hardware_io())
        await real_io_acquired.wait()

        live_job_id = await manager.submit_job(
            "live-data",
            {"resource": "USB0::FAKE::INSTR", "simulate": False, "dry_run": False},
            {"interval_ms": 50},
        )
        live_task = asyncio.create_task(
            web_app._execute_live_data_background(live_job_id)
        )
        await live_waiting_for_lock.wait()

        shutdown_task = asyncio.create_task(manager.shutdown(timeout_s=0.5))

        async def wait_for_cancel_requested() -> None:
            while manager.jobs[live_job_id].status != JobStatus.CANCEL_REQUESTED:
                if shutdown_task.done():
                    raise AssertionError(
                        "shutdown completed before Live Data left the hardware-I/O path"
                    )
                await asyncio.sleep(0)

        await asyncio.wait_for(wait_for_cancel_requested(), timeout=0.5)

        assert shutdown_task.done() is False

        release_real_io.set()
        await real_io_task
        await shutdown_task

        assert live_task.done() is True
        assert manager.jobs[live_job_id].status == JobStatus.CANCELLED
        assert manager.jobs[live_job_id].io_in_progress is False
        assert read_calls == 0

    asyncio.run(check())


def test_shutdown_cancels_accepted_job() -> None:
    async def check() -> None:
        manager = JobManager()
        job_id = await manager.submit_job("measure", {"simulate": True}, {"channel": 1})

        await manager.shutdown(timeout_s=0.5)

        assert manager.jobs[job_id].status == JobStatus.CANCELLED

    asyncio.run(check())


def test_shutdown_timeout_does_not_claim_success() -> None:
    async def check() -> None:
        manager = JobManager()
        job_id = await manager.submit_job(
            "output-on",
            {"resource": "USB0::FAKE::INSTR", "simulate": False, "dry_run": False},
            {"channel": 1},
        )
        assert await manager.start_job(job_id) is True

        with pytest.raises(TimeoutError, match="pending jobs"):
            await manager.shutdown(timeout_s=0.01)

        assert manager.jobs[job_id].status == JobStatus.CANCEL_REQUESTED
        assert manager.active_job_id == job_id

    asyncio.run(check())


def test_shutdown_rejects_new_jobs() -> None:
    async def check() -> None:
        manager = JobManager()
        await manager.shutdown(timeout_s=0)

        with pytest.raises(RuntimeError, match="shutting down"):
            await manager.submit_job("measure", {"simulate": True}, {"channel": 1})

    asyncio.run(check())


def test_shutdown_reports_cleanup_failure() -> None:
    async def check() -> None:
        manager = JobManager()
        job_id = await manager.submit_job(
            "ramp",
            {"resource": "USB0::FAKE::INSTR", "simulate": False, "dry_run": False},
            {"channel": 1},
        )
        assert await manager.start_job(job_id) is True

        async def fail_cleanup_after_cancellation() -> None:
            while not manager.jobs[job_id].cancel_requested:
                await asyncio.sleep(0)
            await manager.fail_job(
                job_id,
                "controlled cleanup failure",
                code="cleanup_failed",
            )

        worker = asyncio.create_task(fail_cleanup_after_cancellation())
        with pytest.raises(RuntimeError, match="cleanup failed"):
            await manager.shutdown(timeout_s=0.5)
        await worker
        with pytest.raises(RuntimeError, match="cleanup failed"):
            await manager.shutdown(timeout_s=0.5)

    asyncio.run(check())


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        (
            "/api/jobs",
            {
                "command": "measure",
                "runtime": {
                    "resource": "USB0::SIM::E36312A::INSTR",
                    "simulate": True,
                },
                "parameters": {"channel": 1},
            },
        ),
        (
            "/api/live",
            {
                "runtime": {
                    "resource": "USB0::FAKE::E36312A::INSTR",
                    "simulate": False,
                },
                "parameters": {"interval_ms": 50},
            },
        ),
    ],
)
def test_api_rejects_new_work_during_shutdown(client, path: str, payload: dict) -> None:
    from powers_tool_webui.jobs import job_manager

    job_manager._shutdown_started = True

    response = client.post(path, json=payload)

    assert response.status_code == 503
    assert "shutting down" in response.json()["detail"]
