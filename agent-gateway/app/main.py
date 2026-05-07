"""Agent Gateway - HTTP API for invoking Claude Code and Codex CLI agents."""

import os
import subprocess
import threading
import time
import uuid
from collections import deque
from enum import Enum
from typing import Any

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field

MAX_CONCURRENT_JOBS = int(os.environ.get("MAX_CONCURRENT_JOBS", "4"))

app = FastAPI(title="Agent Gateway", version="0.1.0")


# --- Models ---


class AgentType(str, Enum):
    claude = "claude"
    codex = "codex"


class PermissionLevel(str, Enum):
    readonly = "readonly"
    full = "full"


class JobStatus(str, Enum):
    queued = "queued"
    running = "running"
    done = "done"
    failed = "failed"
    cancelled = "cancelled"


class RunRequest(BaseModel):
    agent: AgentType
    prompt: str
    cwd: str = "/workspace"
    model: str | None = None
    system_prompt: str | None = None
    timeout: int = Field(default=1800, ge=1, le=7200)
    permissions: PermissionLevel = PermissionLevel.readonly


class JobInfo(BaseModel):
    job_id: str
    status: JobStatus
    position: int | None = None
    elapsed: float | None = None
    result: Any | None = None
    error: str | None = None
    exit_code: int | None = None


# --- Job Store ---


class Job:
    def __init__(self, job_id: str, request: RunRequest) -> None:
        self.job_id = job_id
        self.request = request
        self.status = JobStatus.queued
        self.result: Any | None = None
        self.error: str | None = None
        self.exit_code: int | None = None
        self.start_time: float | None = None
        self.end_time: float | None = None
        self.process: subprocess.Popen | None = None

    @property
    def elapsed(self) -> float | None:
        if self.start_time is None:
            return None
        end = self.end_time if self.end_time is not None else time.time()
        return round(end - self.start_time, 2)

    def to_info(self, position: int | None = None) -> JobInfo:
        return JobInfo(
            job_id=self.job_id,
            status=self.status,
            position=position if self.status == JobStatus.queued else None,
            elapsed=self.elapsed,
            result=self.result if self.status == JobStatus.done else None,
            error=self.error if self.status == JobStatus.failed else None,
            exit_code=self.exit_code,
        )


# --- CLI Command Builder ---


def build_claude_command(req: RunRequest) -> tuple[list[str], str]:
    """Build Claude CLI command. Returns (args, stdin_input).

    Prompt is passed via stdin to avoid OS ARG_MAX limits on large inputs.
    """
    cmd = ["claude", "-p", "--output-format", "json"]
    if req.system_prompt:
        cmd.extend(["--system-prompt", req.system_prompt])
    if req.model:
        cmd.extend(["--model", req.model])
    if req.permissions == PermissionLevel.full:
        cmd.append("--dangerously-skip-permissions")
    return cmd, req.prompt


def build_codex_command(req: RunRequest) -> tuple[list[str], str]:
    """Build Codex CLI command. Returns (args, stdin_input).

    Prompt is passed via stdin to avoid OS ARG_MAX limits on large inputs.
    """
    prompt = req.prompt
    if req.system_prompt:
        prompt = f"{req.system_prompt}\n\n{prompt}"
    cmd = ["codex", "exec", "-", "--json"]
    if req.model:
        cmd.extend(["-m", req.model])
    if req.cwd and req.cwd != "/workspace":
        cmd.extend(["-C", req.cwd])
    if req.permissions == PermissionLevel.full:
        cmd.append("--dangerously-bypass-approvals-and-sandbox")
    return cmd, prompt


def build_command(req: RunRequest) -> tuple[list[str], str]:
    if req.agent == AgentType.claude:
        return build_claude_command(req)
    return build_codex_command(req)


# --- Job Queue / Worker ---


class JobQueue:
    def __init__(self, max_workers: int = MAX_CONCURRENT_JOBS) -> None:
        self.jobs: dict[str, Job] = {}
        self.queue: deque[str] = deque()
        self.running_job_ids: set[str] = set()
        self.lock = threading.Lock()
        self.semaphore = threading.Semaphore(max_workers)
        self.max_workers = max_workers
        self.worker_thread = threading.Thread(target=self._dispatcher, daemon=True)
        self.worker_thread.start()

    def submit(self, request: RunRequest) -> Job:
        job_id = str(uuid.uuid4())
        job = Job(job_id, request)
        with self.lock:
            self.jobs[job_id] = job
            self.queue.append(job_id)
        return job

    def get(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)

    def list_jobs(self) -> list[Job]:
        return list(self.jobs.values())

    def cancel(self, job_id: str) -> bool:
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None:
                return False
            if job.status == JobStatus.queued:
                job.status = JobStatus.cancelled
                if job_id in self.queue:
                    self.queue.remove(job_id)
                return True
            if job.status == JobStatus.running and job.process is not None:
                job.process.kill()
                job.status = JobStatus.cancelled
                job.end_time = time.time()
                self.running_job_ids.discard(job_id)
                return True
        return False

    def queue_position(self, job_id: str) -> int | None:
        with self.lock:
            try:
                return list(self.queue).index(job_id)
            except ValueError:
                return None

    @property
    def queue_length(self) -> int:
        return len(self.queue)

    @property
    def current_job_id(self) -> str | None:
        with self.lock:
            ids = list(self.running_job_ids)
            return ids[0] if len(ids) == 1 else None

    def _dispatcher(self) -> None:
        while True:
            self.semaphore.acquire()
            job_id = None
            while job_id is None:
                with self.lock:
                    if self.queue:
                        job_id = self.queue.popleft()
                if job_id is None:
                    time.sleep(0.1)

            job = self.jobs[job_id]
            if job.status == JobStatus.cancelled:
                self.semaphore.release()
                continue

            with self.lock:
                self.running_job_ids.add(job_id)

            thread = threading.Thread(target=self._run_and_release, args=(job,), daemon=True)
            thread.start()

    def _run_and_release(self, job: Job) -> None:
        try:
            self._execute(job)
        finally:
            with self.lock:
                self.running_job_ids.discard(job.job_id)
            self.semaphore.release()

    def _execute(self, job: Job) -> None:
        job.status = JobStatus.running
        job.start_time = time.time()
        cmd, stdin_input = build_command(job.request)
        cwd = job.request.cwd if job.request.agent == AgentType.claude else None
        try:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=cwd,
                text=True,
            )
            job.process = proc
            try:
                stdout, stderr = proc.communicate(input=stdin_input, timeout=job.request.timeout)
                job.exit_code = proc.returncode
                if proc.returncode == 0:
                    job.status = JobStatus.done
                    job.result = stdout
                else:
                    job.status = JobStatus.failed
                    job.error = stderr or stdout
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
                job.status = JobStatus.failed
                job.error = f"Timeout after {job.request.timeout}s"
                job.exit_code = -9
        except FileNotFoundError:
            job.status = JobStatus.failed
            job.error = f"CLI not found: {cmd[0]}"
            job.exit_code = -1
        except Exception as e:
            job.status = JobStatus.failed
            job.error = str(e)
            job.exit_code = -1
        finally:
            job.end_time = time.time()


# --- Global queue instance ---

job_queue = JobQueue()


# --- API Endpoints ---


@app.post("/agent/run", status_code=status.HTTP_202_ACCEPTED)
def run_agent(request: RunRequest) -> dict:
    job = job_queue.submit(request)
    return {"job_id": job.job_id, "status": "queued"}


@app.get("/agent/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    job = job_queue.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    position = job_queue.queue_position(job_id)
    info = job.to_info(position=position)
    return info.model_dump(exclude_none=True)


@app.get("/agent/jobs")
def list_jobs() -> list[dict]:
    jobs = job_queue.list_jobs()
    result = []
    for job in jobs:
        position = job_queue.queue_position(job.job_id)
        result.append(job.to_info(position=position).model_dump(exclude_none=True))
    return result


@app.delete("/agent/jobs/{job_id}")
def cancel_job(job_id: str) -> dict:
    job = job_queue.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    success = job_queue.cancel(job_id)
    if not success:
        raise HTTPException(status_code=409, detail="Job cannot be cancelled")
    return {"job_id": job_id, "status": "cancelled"}


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "queue_length": job_queue.queue_length,
        "running_jobs": sorted(job_queue.running_job_ids),
        "max_concurrent": job_queue.max_workers,
    }
