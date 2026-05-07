"""Shared test fixtures."""

import pytest
from fastapi.testclient import TestClient

from app.main import JobQueue, app, job_queue


@pytest.fixture(autouse=True)
def _reset_job_queue():
    """Reset the global job queue before each test."""
    job_queue.jobs.clear()
    job_queue.queue.clear()
    job_queue.running_job_ids.clear()
    yield


@pytest.fixture
def client():
    """Provide a FastAPI test client."""
    return TestClient(app)


@pytest.fixture
def fresh_queue():
    """Provide a fresh JobQueue instance for isolated testing."""
    return JobQueue()
