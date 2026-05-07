"""Tests for Agent Gateway API endpoints."""

import time
from unittest.mock import MagicMock, patch

from app.main import (
    AgentType,
    JobStatus,
    PermissionLevel,
    RunRequest,
    build_claude_command,
    build_codex_command,
    build_command,
    job_queue,
)

# --- Health endpoint ---


class TestHealth:
    def test_health_returns_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "queue_length" in data
        assert "current_job" in data

    def test_health_queue_length_zero(self, client):
        resp = client.get("/health")
        assert resp.json()["queue_length"] == 0


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
        cmd = build_claude_command(req)
        assert cmd == ["claude", "-p", "test prompt", "--output-format", "json"]

    def test_claude_with_system_prompt(self):
        req = RunRequest(agent=AgentType.claude, prompt="test", system_prompt="be helpful")
        cmd = build_claude_command(req)
        assert "--system-prompt" in cmd
        assert "be helpful" in cmd

    def test_claude_with_model(self):
        req = RunRequest(agent=AgentType.claude, prompt="test", model="opus")
        cmd = build_claude_command(req)
        assert "--model" in cmd
        assert "opus" in cmd

    def test_claude_full_permissions(self):
        req = RunRequest(agent=AgentType.claude, prompt="test", permissions=PermissionLevel.full)
        cmd = build_claude_command(req)
        assert "--dangerously-skip-permissions" in cmd

    def test_claude_readonly_no_dangerous_flag(self):
        req = RunRequest(agent=AgentType.claude, prompt="test", permissions=PermissionLevel.readonly)
        cmd = build_claude_command(req)
        assert "--dangerously-skip-permissions" not in cmd

    def test_codex_basic(self):
        req = RunRequest(agent=AgentType.codex, prompt="test prompt")
        cmd = build_codex_command(req)
        assert cmd == ["codex", "exec", "test prompt", "--json"]

    def test_codex_with_system_prompt(self):
        req = RunRequest(agent=AgentType.codex, prompt="test", system_prompt="be helpful")
        cmd = build_codex_command(req)
        assert cmd[2] == "be helpful\n\ntest"

    def test_codex_with_model(self):
        req = RunRequest(agent=AgentType.codex, prompt="test", model="gpt-4")
        cmd = build_codex_command(req)
        assert "-m" in cmd
        assert "gpt-4" in cmd

    def test_codex_with_custom_cwd(self):
        req = RunRequest(agent=AgentType.codex, prompt="test", cwd="/tmp")
        cmd = build_codex_command(req)
        assert "-C" in cmd
        assert "/tmp" in cmd

    def test_codex_default_cwd_no_flag(self):
        req = RunRequest(agent=AgentType.codex, prompt="test", cwd="/workspace")
        cmd = build_codex_command(req)
        assert "-C" not in cmd

    def test_codex_full_permissions(self):
        req = RunRequest(agent=AgentType.codex, prompt="test", permissions=PermissionLevel.full)
        cmd = build_codex_command(req)
        assert "--dangerously-bypass-approvals-and-sandbox" in cmd

    def test_build_command_dispatches_claude(self):
        req = RunRequest(agent=AgentType.claude, prompt="test")
        cmd = build_command(req)
        assert cmd[0] == "claude"

    def test_build_command_dispatches_codex(self):
        req = RunRequest(agent=AgentType.codex, prompt="test")
        cmd = build_command(req)
        assert cmd[0] == "codex"


# --- Job lifecycle with mocked subprocess ---


class TestJobLifecycle:
    @patch("app.main.subprocess.Popen")
    def test_job_completes_successfully(self, mock_popen, client):
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ('{"output": "done"}', "")
        mock_proc.returncode = 0
        mock_popen.return_value = mock_proc

        resp = client.post("/agent/run", json={"agent": "claude", "prompt": "hello"})
        job_id = resp.json()["job_id"]

        # Wait for worker to process
        for _ in range(50):
            job = job_queue.get(job_id)
            if job and job.status in (JobStatus.done, JobStatus.failed):
                break
            time.sleep(0.05)

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

        for _ in range(50):
            job = job_queue.get(job_id)
            if job and job.status in (JobStatus.done, JobStatus.failed):
                break
            time.sleep(0.05)

        resp = client.get(f"/agent/jobs/{job_id}")
        data = resp.json()
        assert data["status"] == "failed"
        assert data["exit_code"] == 1
        assert "error" in data

    @patch("app.main.subprocess.Popen", side_effect=FileNotFoundError("not found"))
    def test_job_fails_on_missing_cli(self, mock_popen, client):
        resp = client.post("/agent/run", json={"agent": "claude", "prompt": "hello"})
        job_id = resp.json()["job_id"]

        for _ in range(50):
            job = job_queue.get(job_id)
            if job and job.status in (JobStatus.done, JobStatus.failed):
                break
            time.sleep(0.05)

        resp = client.get(f"/agent/jobs/{job_id}")
        data = resp.json()
        assert data["status"] == "failed"
        assert "CLI not found" in data["error"]
