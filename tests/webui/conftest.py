"""Shared pytest configuration for WebUI tests."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


pytest.register_assert_rewrite(
    "_webui_shared",
    "_webui_api_helpers",
)

@pytest.fixture
def client():
    from powers_tool_webui.app import app
    from powers_tool_webui.jobs import job_manager
    job_manager.jobs.clear()
    job_manager.active_job_id = None
    job_manager._shutdown_started = False
    job_manager._shutdown_job_ids.clear()
    return TestClient(app)
