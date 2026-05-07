"""Tests for Agent Gateway API endpoints."""

import time
from unittest.mock import MagicMock, patch

from app.main import (
    AgentType,
    Job,
    JobStatus,
    PermissionLevel,
    RunRequest,
    build_claude_command,
    build_codex_command,
    build_command,
    job_queue,
)

MAX_POLL = 50
POLL_SLEEP = 0.05

# --- Health endpoint ---


class TestHealth:
    def test_health_returns_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "queue_length" in data
        assert "running_jobs" in data

    def test_health_queue_length_zero(self, client):
        resp = client.get("/health")
        data = resp.json()
        assert data["queue_length"] == 0
        assert data["running_jobs"] == []
        assert "max_concurrent" in data


# --- POST /agent/run ---


class TestRunAgent:
    def test_run_returns_202(self, client):
        resp = client.post("/agent/run", json={"agent": "claude", "prompt": "hello"})
        assert resp.status_code == 202
        data = resp.json()
        assert "job_id" in data
        assert data["status"] == "queued"

    def test_run_missing_agent(self, client):
        resp = client.post("/agent/run", json={"prompt": "hello"})
        assert resp.status_code == 422

    def test_run_missing_prompt(self, client):
        resp = client.post("/agent/run", json={"agent": "claude"})
        assert resp.status_code == 422

    def test_run_invalid_agent(self, client):
        resp = client.post("/agent/run", json={"agent": "invalid", "prompt": "hello"})
        assert resp.status_code == 422

    def test_run_invalid_permissions(self, client):
        resp = client.post("/agent/run", json={"agent": "claude", "prompt": "hello", "permissions": "invalid"})
        assert resp.status_code == 422

    def test_run_with_all_params(self, client):
        resp = client.post(
            "/agent/run",
            json={
                "agent": "codex",
                "prompt": "test prompt",
                "cwd": "/tmp",
                "model": "gpt-4",
                "system_prompt": "be helpful",
                "timeout": 600,
                "permissions": "full",
            },
        )
        assert resp.status_code == 202

    def test_run_default_values(self, client):
        resp = client.post("/agent/run", json={"agent": "claude", "prompt": "hello"})
        assert resp.status_code == 202
        job_id = resp.json()["job_id"]
        job = job_queue.get(job_id)
        assert job is not None
        assert job.request.cwd == "/workspace"
        assert job.request.timeout == 1800
        assert job.request.permissions == PermissionLevel.readonly


# --- GET /agent/jobs/{job_id} ---


class TestGetJob:
    def test_get_nonexistent_job(self, client):
        resp = client.get("/agent/jobs/nonexistent-id")
        assert resp.status_code == 404

    def test_get_queued_job(self, client):
        resp = client.post("/agent/run", json={"agent": "claude", "prompt": "hello"})
        job_id = resp.json()["job_id"]
        resp = client.get(f"/agent/jobs/{job_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["job_id"] == job_id
        assert data["status"] in ["queued", "running", "done", "failed"]


# --- GET /agent/jobs ---


class TestListJobs:
    def test_list_empty(self, client):
        resp = client.get("/agent/jobs")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_after_submit(self, client):
        client.post("/agent/run", json={"agent": "claude", "prompt": "hello"})
        resp = client.get("/agent/jobs")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1


# --- DELETE /agent/jobs/{job_id} ---


class TestCancelJob:
    def test_cancel_nonexistent(self, client):
        resp = client.delete("/agent/jobs/nonexistent-id")
        assert resp.status_code == 404

    def test_cancel_completed_job(self, client):
        resp = client.post("/agent/run", json={"agent": "claude", "prompt": "hello"})
        job_id = resp.json()["job_id"]
        job = job_queue.get(job_id)
        # Simulate completed state
        job.status = JobStatus.done
        job.end_time = time.time()
        resp = client.delete(f"/agent/jobs/{job_id}")
        assert resp.status_code == 409


# --- CLI Command Builder ---


class TestBuildCommand:
    def test_claude_basic(self):
        req = RunRequest(agent=AgentType.claude, prompt="test prompt")
        cmd, stdin = build_claude_command(req)
        assert cmd == ["claude", "-p", "--output-format", "json"]
        assert stdin == "test prompt"

    def test_claude_with_system_prompt(self):
        req = RunRequest(agent=AgentType.claude, prompt="test", system_prompt="be helpful")
        cmd, _stdin = build_claude_command(req)
        assert "--system-prompt" in cmd
        assert "be helpful" in cmd

    def test_claude_with_model(self):
        req = RunRequest(agent=AgentType.claude, prompt="test", model="opus")
        cmd, _stdin = build_claude_command(req)
        assert "--model" in cmd
        assert "opus" in cmd

    def test_claude_full_permissions(self):
        req = RunRequest(agent=AgentType.claude, prompt="test", permissions=PermissionLevel.full)
        cmd, _stdin = build_claude_command(req)
        assert "--dangerously-skip-permissions" in cmd

    def test_claude_readonly_no_dangerous_flag(self):
        req = RunRequest(agent=AgentType.claude, prompt="test", permissions=PermissionLevel.readonly)
        cmd, _stdin = build_claude_command(req)
        assert "--dangerously-skip-permissions" not in cmd

    def test_claude_prompt_not_in_args(self):
        req = RunRequest(agent=AgentType.claude, prompt="large prompt data")
        cmd, stdin = build_claude_command(req)
        assert "large prompt data" not in cmd
        assert stdin == "large prompt data"

    def test_codex_basic(self):
        req = RunRequest(agent=AgentType.codex, prompt="test prompt")
        cmd, stdin = build_codex_command(req)
        assert cmd == ["codex", "exec", "-", "--json"]
        assert stdin == "test prompt"

    def test_codex_with_system_prompt(self):
        req = RunRequest(agent=AgentType.codex, prompt="test", system_prompt="be helpful")
        cmd, stdin = build_codex_command(req)
        assert "test" not in cmd
        assert stdin == "be helpful\n\ntest"

    def test_codex_with_model(self):
        req = RunRequest(agent=AgentType.codex, prompt="test", model="gpt-4")
        cmd, _stdin = build_codex_command(req)
        assert "-m" in cmd
        assert "gpt-4" in cmd

    def test_codex_with_custom_cwd(self):
        req = RunRequest(agent=AgentType.codex, prompt="test", cwd="/tmp")
        cmd, _stdin = build_codex_command(req)
        assert "-C" in cmd
        assert "/tmp" in cmd

    def test_codex_default_cwd_no_flag(self):
        req = RunRequest(agent=AgentType.codex, prompt="test", cwd="/workspace")
        cmd, _stdin = build_codex_command(req)
        assert "-C" not in cmd

    def test_codex_full_permissions(self):
        req = RunRequest(agent=AgentType.codex, prompt="test", permissions=PermissionLevel.full)
        cmd, _stdin = build_codex_command(req)
        assert "--dangerously-bypass-approvals-and-sandbox" in cmd

    def test_build_command_dispatches_claude(self):
        req = RunRequest(agent=AgentType.claude, prompt="test")
        cmd, _stdin = build_command(req)
        assert cmd[0] == "claude"

    def test_build_command_dispatches_codex(self):
        req = RunRequest(agent=AgentType.codex, prompt="test")
        cmd, _stdin = build_command(req)
        assert cmd[0] == "codex"


# --- Job lifecycle with mocked subprocess ---


def _wait_for_job(job_id: str, *terminal: JobStatus) -> Job:
    targets = terminal or (JobStatus.done, JobStatus.failed)
    for _ in range(MAX_POLL):
        job = job_queue.get(job_id)
        if job and job.status in targets:
            return job
        time.sleep(POLL_SLEEP)
    return job_queue.get(job_id)


class TestJobLifecycle:
    @patch("app.main.subprocess.Popen")
    def test_job_completes_successfully(self, mock_popen, client):
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ('{"output": "done"}', "")
        mock_proc.returncode = 0
        mock_popen.return_value = mock_proc

        resp = client.post("/agent/run", json={"agent": "claude", "prompt": "hello"})
        job_id = resp.json()["job_id"]
        _wait_for_job(job_id)

        resp = client.get(f"/agent/jobs/{job_id}")
        data = resp.json()
        assert data["status"] == "done"
        assert data["exit_code"] == 0
        assert "result" in data

    @patch("app.main.subprocess.Popen")
    def test_job_fails_on_nonzero_exit(self, mock_popen, client):
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("", "error occurred")
        mock_proc.returncode = 1
        mock_popen.return_value = mock_proc

        resp = client.post("/agent/run", json={"agent": "claude", "prompt": "hello"})
        job_id = resp.json()["job_id"]
        _wait_for_job(job_id)

        resp = client.get(f"/agent/jobs/{job_id}")
        data = resp.json()
        assert data["status"] == "failed"
        assert data["exit_code"] == 1
        assert "error" in data

    @patch("app.main.subprocess.Popen", side_effect=FileNotFoundError("not found"))
    def test_job_fails_on_missing_cli(self, mock_popen, client):
        resp = client.post("/agent/run", json={"agent": "claude", "prompt": "hello"})
        job_id = resp.json()["job_id"]
        _wait_for_job(job_id)

        resp = client.get(f"/agent/jobs/{job_id}")
        data = resp.json()
        assert data["status"] == "failed"
        assert "CLI not found" in data["error"]

    @patch("app.main.subprocess.Popen")
    def test_concurrent_jobs_run_in_parallel(self, mock_popen, client):
        barrier = __import__("threading").Barrier(2, timeout=5)

        def slow_communicate(input=None, timeout=None):
            barrier.wait()
            return ('{"ok": true}', "")

        def make_proc():
            proc = MagicMock()
            proc.communicate.side_effect = slow_communicate
            proc.returncode = 0
            return proc

        mock_popen.side_effect = lambda *a, **kw: make_proc()

        r1 = client.post("/agent/run", json={"agent": "claude", "prompt": "a"})
        r2 = client.post("/agent/run", json={"agent": "claude", "prompt": "b"})
        id1, id2 = r1.json()["job_id"], r2.json()["job_id"]

        _wait_for_job(id1)
        _wait_for_job(id2)

        assert job_queue.get(id1).status == JobStatus.done
        assert job_queue.get(id2).status == JobStatus.done
