"""Tests for Agent Gateway API endpoints."""

import time
from unittest.mock import MagicMock, patch

from app.main import (
    AgentType,
    Job,
    JobStatus,
    PermissionLevel,
    RunRequest,
    _extract_result_text,
    _is_auth_error,
    build_claude_command,
    build_codex_command,
    build_command,
    check_token_expiry,
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

    def test_claude_image_path_enables_permissions(self):
        req = RunRequest(agent=AgentType.claude, prompt="analyze", image_path="/shared-data/img.jpg")
        cmd, stdin = build_claude_command(req)
        assert "--dangerously-skip-permissions" in cmd
        assert "Read the image file at /shared-data/img.jpg" in stdin
        assert stdin.endswith("analyze")

    def test_claude_image_path_without_explicit_full(self):
        req = RunRequest(
            agent=AgentType.claude,
            prompt="test",
            permissions=PermissionLevel.readonly,
            image_path="/data/frame.jpg",
        )
        cmd, _stdin = build_claude_command(req)
        assert "--dangerously-skip-permissions" in cmd

    def test_claude_image_paths_multiple(self):
        req = RunRequest(
            agent=AgentType.claude,
            prompt="analyze these",
            image_paths=["/data/a.jpg", "/data/b.png", "/data/c.jpg"],
        )
        cmd, stdin = build_claude_command(req)
        assert "--dangerously-skip-permissions" in cmd
        assert "Read the image files at /data/a.jpg, /data/b.png, /data/c.jpg" in stdin
        assert "and analyze them" in stdin
        assert stdin.endswith("analyze these")

    def test_claude_image_paths_single_element(self):
        req = RunRequest(
            agent=AgentType.claude,
            prompt="analyze this",
            image_paths=["/data/only.jpg"],
        )
        cmd, stdin = build_claude_command(req)
        assert "--dangerously-skip-permissions" in cmd
        assert "Read the image files at /data/only.jpg" in stdin
        assert stdin.endswith("analyze this")

    def test_claude_image_path_singular_backward_compat(self):
        req = RunRequest(
            agent=AgentType.claude,
            prompt="analyze",
            image_path="/shared-data/img.jpg",
        )
        cmd, stdin = build_claude_command(req)
        assert "--dangerously-skip-permissions" in cmd
        assert "Read the image file at /shared-data/img.jpg" in stdin
        assert "and analyze it" in stdin
        assert stdin.endswith("analyze")

    def test_claude_image_paths_takes_precedence_over_image_path(self):
        req = RunRequest(
            agent=AgentType.claude,
            prompt="analyze",
            image_path="/old/single.jpg",
            image_paths=["/new/a.jpg", "/new/b.jpg"],
        )
        cmd, stdin = build_claude_command(req)
        assert "Read the image files at /new/a.jpg, /new/b.jpg" in stdin
        assert "/old/single.jpg" not in stdin

    def test_build_command_dispatches_claude(self):
        req = RunRequest(agent=AgentType.claude, prompt="test")
        cmd, _stdin = build_command(req)
        assert cmd[0] == "claude"

    def test_build_command_dispatches_codex(self):
        req = RunRequest(agent=AgentType.codex, prompt="test")
        cmd, _stdin = build_command(req)
        assert cmd[0] == "codex"

    # --- agent_options tests ---

    def test_claude_allowed_tools_string(self):
        req = RunRequest(
            agent=AgentType.claude,
            prompt="test",
            agent_options={"allowed_tools": "Bash,Read"},
        )
        cmd, _stdin = build_claude_command(req)
        assert "--allowedTools" in cmd
        idx = cmd.index("--allowedTools")
        assert cmd[idx + 1] == "Bash,Read"

    def test_claude_allowed_tools_list(self):
        req = RunRequest(
            agent=AgentType.claude,
            prompt="test",
            agent_options={"allowed_tools": ["Bash", "Read", "Write"]},
        )
        cmd, _stdin = build_claude_command(req)
        assert "--allowedTools" in cmd
        idx = cmd.index("--allowedTools")
        assert cmd[idx + 1] == "Bash,Read,Write"

    def test_claude_disallowed_tools(self):
        req = RunRequest(
            agent=AgentType.claude,
            prompt="test",
            agent_options={"disallowed_tools": "Edit"},
        )
        cmd, _stdin = build_claude_command(req)
        assert "--disallowedTools" in cmd
        idx = cmd.index("--disallowedTools")
        assert cmd[idx + 1] == "Edit"

    def test_claude_append_system_prompt(self):
        req = RunRequest(
            agent=AgentType.claude,
            prompt="test",
            agent_options={"append_system_prompt": "Always respond in JSON"},
        )
        cmd, _stdin = build_claude_command(req)
        assert "--append-system-prompt" in cmd
        idx = cmd.index("--append-system-prompt")
        assert cmd[idx + 1] == "Always respond in JSON"

    def test_codex_ignores_unknown_agent_options(self):
        req = RunRequest(
            agent=AgentType.codex,
            prompt="test",
            agent_options={"unknown_key": "value", "another": 42},
        )
        cmd, stdin = build_codex_command(req)
        assert cmd == ["codex", "exec", "-", "--json"]
        assert stdin == "test"

    def test_agent_options_defaults_to_none(self):
        req = RunRequest(agent=AgentType.claude, prompt="test")
        assert req.agent_options is None
        cmd, _stdin = build_claude_command(req)
        assert "--allowedTools" not in cmd
        assert "--disallowedTools" not in cmd
        assert "--append-system-prompt" not in cmd


# --- _extract_result_text ---


class TestExtractResultText:
    def test_unwraps_claude_json_output(self):
        stdout = '{"type":"result","subtype":"success","result":"hello world","stop_reason":"end_turn"}'
        assert _extract_result_text(stdout) == "hello world"

    def test_passes_through_plain_text(self):
        assert _extract_result_text("just plain text") == "just plain text"

    def test_passes_through_non_result_json(self):
        stdout = '{"output": "done"}'
        assert _extract_result_text(stdout) == '{"output": "done"}'

    def test_passes_through_empty_string(self):
        assert _extract_result_text("") == ""


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


# --- Token Expiry Check ---


class TestCheckTokenExpiry:
    def test_no_env_var(self):
        with patch.dict("os.environ", {}, clear=True):
            days, warning = check_token_expiry()
            assert days is None
            assert warning is None

    def test_empty_env_var(self):
        with patch.dict("os.environ", {"CLAUDE_TOKEN_EXPIRES_AT": ""}):
            days, warning = check_token_expiry()
            assert days is None
            assert warning is None

    def test_invalid_format(self):
        with patch.dict("os.environ", {"CLAUDE_TOKEN_EXPIRES_AT": "not-a-date"}):
            days, warning = check_token_expiry()
            assert days is None
            assert warning is None

    @patch("app.main.date")
    def test_token_not_expiring_soon(self, mock_date):
        from datetime import date as real_date

        mock_date.today.return_value = real_date(2026, 1, 1)
        mock_date.side_effect = lambda *a, **kw: real_date(*a, **kw)
        with patch.dict("os.environ", {"CLAUDE_TOKEN_EXPIRES_AT": "2026-12-31"}):
            days, warning = check_token_expiry()
            assert days == 364
            assert warning is None

    @patch("app.main.date")
    def test_token_expiring_soon(self, mock_date):
        from datetime import date as real_date

        mock_date.today.return_value = real_date(2026, 6, 10)
        mock_date.side_effect = lambda *a, **kw: real_date(*a, **kw)
        with patch.dict("os.environ", {"CLAUDE_TOKEN_EXPIRES_AT": "2026-06-25"}):
            days, warning = check_token_expiry()
            assert days == 15
            assert warning is not None
            assert "15 day(s)" in warning

    @patch("app.main.date")
    def test_token_expired(self, mock_date):
        from datetime import date as real_date

        mock_date.today.return_value = real_date(2026, 7, 5)
        mock_date.side_effect = lambda *a, **kw: real_date(*a, **kw)
        with patch.dict("os.environ", {"CLAUDE_TOKEN_EXPIRES_AT": "2026-07-01"}):
            days, warning = check_token_expiry()
            assert days == -4
            assert warning is not None
            assert "expired" in warning


# --- Health endpoint with token info ---


class TestHealthTokenInfo:
    @patch("app.main.date")
    def test_health_includes_token_info_when_set(self, mock_date, client):
        from datetime import date as real_date

        mock_date.today.return_value = real_date(2026, 1, 1)
        mock_date.side_effect = lambda *a, **kw: real_date(*a, **kw)
        with patch.dict("os.environ", {"CLAUDE_TOKEN_EXPIRES_AT": "2026-12-31"}):
            resp = client.get("/health")
            data = resp.json()
            assert data["status"] == "ok"
            assert data["token_expires_at"] == "2026-12-31"
            assert data["token_days_remaining"] == 364
            assert "token_warning" not in data

    def test_health_no_token_info_when_unset(self, client):
        with patch.dict("os.environ", {}, clear=False):
            env = dict(**__import__("os").environ)
            env.pop("CLAUDE_TOKEN_EXPIRES_AT", None)
            with patch.dict("os.environ", env, clear=True):
                resp = client.get("/health")
                data = resp.json()
                assert "token_expires_at" not in data
                assert "token_days_remaining" not in data

    @patch("app.main.date")
    def test_health_includes_warning_when_expiring(self, mock_date, client):
        from datetime import date as real_date

        mock_date.today.return_value = real_date(2026, 6, 20)
        mock_date.side_effect = lambda *a, **kw: real_date(*a, **kw)
        with patch.dict("os.environ", {"CLAUDE_TOKEN_EXPIRES_AT": "2026-06-25"}):
            resp = client.get("/health")
            data = resp.json()
            assert "token_warning" in data
            assert "5 day(s)" in data["token_warning"]


# --- Job warnings ---


class TestJobWarnings:
    @patch("app.main.subprocess.Popen")
    @patch("app.main.date")
    def test_claude_job_includes_token_warning(self, mock_date, mock_popen, client):
        from datetime import date as real_date

        mock_date.today.return_value = real_date(2026, 6, 20)
        mock_date.side_effect = lambda *a, **kw: real_date(*a, **kw)

        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ('{"type":"result","result":"ok"}', "")
        mock_proc.returncode = 0
        mock_popen.return_value = mock_proc

        with patch.dict("os.environ", {"CLAUDE_TOKEN_EXPIRES_AT": "2026-06-25"}):
            resp = client.post("/agent/run", json={"agent": "claude", "prompt": "hello"})
            job_id = resp.json()["job_id"]
            _wait_for_job(job_id)

            resp = client.get(f"/agent/jobs/{job_id}")
            data = resp.json()
            assert data["status"] == "done"
            assert "warnings" in data
            assert any("5 day(s)" in w for w in data["warnings"])

    @patch("app.main.subprocess.Popen")
    def test_codex_job_no_token_warning(self, mock_popen, client):
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ('{"ok": true}', "")
        mock_proc.returncode = 0
        mock_popen.return_value = mock_proc

        with patch.dict("os.environ", {"CLAUDE_TOKEN_EXPIRES_AT": "2026-06-25"}):
            resp = client.post("/agent/run", json={"agent": "codex", "prompt": "hello"})
            job_id = resp.json()["job_id"]
            _wait_for_job(job_id)

            resp = client.get(f"/agent/jobs/{job_id}")
            data = resp.json()
            assert data["status"] == "done"
            assert "warnings" not in data

    @patch("app.main.subprocess.Popen")
    def test_no_warnings_when_token_not_expiring(self, mock_popen, client):
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ('{"type":"result","result":"ok"}', "")
        mock_proc.returncode = 0
        mock_popen.return_value = mock_proc

        with patch.dict("os.environ", {}, clear=False):
            env = dict(**__import__("os").environ)
            env.pop("CLAUDE_TOKEN_EXPIRES_AT", None)
            with patch.dict("os.environ", env, clear=True):
                resp = client.post("/agent/run", json={"agent": "claude", "prompt": "hello"})
                job_id = resp.json()["job_id"]
                _wait_for_job(job_id)

                resp = client.get(f"/agent/jobs/{job_id}")
                data = resp.json()
                assert data["status"] == "done"
                assert "warnings" not in data


# --- Auth error detection ---


class TestIsAuthError:
    def test_detects_unauthorized(self):
        assert _is_auth_error("Error: Unauthorized access") is True

    def test_detects_401(self):
        assert _is_auth_error("HTTP 401 response") is True

    def test_detects_token(self):
        assert _is_auth_error("Invalid token") is True

    def test_ignores_normal_error(self):
        assert _is_auth_error("Syntax error in file.py") is False


class TestAuthErrorInJob:
    @patch("app.main.subprocess.Popen")
    @patch("app.main.date")
    def test_expired_token_appends_to_error(self, mock_date, mock_popen, client):
        from datetime import date as real_date

        mock_date.today.return_value = real_date(2026, 8, 1)
        mock_date.side_effect = lambda *a, **kw: real_date(*a, **kw)

        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("", "some error")
        mock_proc.returncode = 1
        mock_popen.return_value = mock_proc

        with patch.dict("os.environ", {"CLAUDE_TOKEN_EXPIRES_AT": "2026-07-01"}):
            resp = client.post("/agent/run", json={"agent": "claude", "prompt": "hello"})
            job_id = resp.json()["job_id"]
            _wait_for_job(job_id)

            resp = client.get(f"/agent/jobs/{job_id}")
            data = resp.json()
            assert data["status"] == "failed"
            assert "[token-expired]" in data["error"]

    @patch("app.main.subprocess.Popen")
    def test_auth_error_hint_appended(self, mock_popen, client):
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("", "Error: Unauthorized")
        mock_proc.returncode = 1
        mock_popen.return_value = mock_proc

        with patch.dict("os.environ", {}, clear=False):
            env = dict(**__import__("os").environ)
            env.pop("CLAUDE_TOKEN_EXPIRES_AT", None)
            with patch.dict("os.environ", env, clear=True):
                resp = client.post("/agent/run", json={"agent": "claude", "prompt": "hello"})
                job_id = resp.json()["job_id"]
                _wait_for_job(job_id)

                resp = client.get(f"/agent/jobs/{job_id}")
                data = resp.json()
                assert data["status"] == "failed"
                assert "[auth-hint]" in data["error"]

    @patch("app.main.subprocess.Popen")
    def test_non_auth_error_no_hint(self, mock_popen, client):
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("", "Syntax error")
        mock_proc.returncode = 1
        mock_popen.return_value = mock_proc

        with patch.dict("os.environ", {}, clear=False):
            env = dict(**__import__("os").environ)
            env.pop("CLAUDE_TOKEN_EXPIRES_AT", None)
            with patch.dict("os.environ", env, clear=True):
                resp = client.post("/agent/run", json={"agent": "claude", "prompt": "hello"})
                job_id = resp.json()["job_id"]
                _wait_for_job(job_id)

                resp = client.get(f"/agent/jobs/{job_id}")
                data = resp.json()
                assert data["status"] == "failed"
                assert "[auth-hint]" not in data["error"]
                assert "[token-expired]" not in data["error"]
