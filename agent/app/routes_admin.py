from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import re
import uuid
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from typing import Dict

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from ..core.artifacts import reload_all
from ..core.config import LOADED_DOTENV_FILES, SETTINGS
from ..core.curation import CurationState, load_curation_state, save_curation_state
from ..core.storage import chat_log_path, feedback_log_path
from ..dspy_modules.intent import ensure_dspy_configured
from ..train.build_dataset import build_datasets
from ..train.compile import (
    compile_fusion_decision,
    compile_product_ranker,
    compile_relaxed_constraints,
)


router = APIRouter()


def _require_admin(x_admin_key: Optional[str]) -> None:
    if SETTINGS.admin_api_key:
        if not x_admin_key or x_admin_key != SETTINGS.admin_api_key:
            raise HTTPException(status_code=401, detail="invalid admin key")


def _read_jsonl_tail(path: Path, limit: int) -> list[dict]:
    if limit <= 0:
        return []
    if not path.exists():
        return []
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    rows.append(obj)
            except Exception:
                continue
    return rows[-limit:]


@dataclass
class _Job:
    status: str  # queued|running|done|error
    result: Optional[dict] = None
    error: Optional[str] = None
    logs: list[str] = field(default_factory=list)
    progress: dict = field(default_factory=dict)
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


def _job_append(job_id: str, line: str) -> None:
    job = _JOBS.get(job_id)
    if not job:
        return
    if not isinstance(line, str) or not line:
        return
    # keep only recent logs (avoid unbounded growth)
    job.logs.append(line.rstrip("\n"))
    if len(job.logs) > 400:
        job.logs = job.logs[-400:]
    job.updated_at = datetime.now(timezone.utc).isoformat()


_TRIAL_RE = re.compile(r"Trial\s+(\d+)\s*/\s*(\d+)")
_STEP_RE = re.compile(r"==>\s*STEP\s*(\d+)")


def _job_parse_progress(job_id: str, line: str) -> None:
    job = _JOBS.get(job_id)
    if not job:
        return
    m = _TRIAL_RE.search(line)
    if m:
        job.progress["trial"] = int(m.group(1))
        job.progress["trial_total"] = int(m.group(2))
    m2 = _STEP_RE.search(line)
    if m2:
        job.progress["step"] = int(m2.group(1))
    job.updated_at = datetime.now(timezone.utc).isoformat()


class _JobLogWriter(io.TextIOBase):
    def __init__(self, job_id: str):
        self.job_id = job_id
        self._buf = ""

    def write(self, s: str) -> int:
        if not isinstance(s, str):
            s = str(s)
        self._buf += s
        # flush per line
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            _job_append(self.job_id, line)
            _job_parse_progress(self.job_id, line)
        return len(s)

    def flush(self) -> None:
        if self._buf:
            _job_append(self.job_id, self._buf)
            _job_parse_progress(self.job_id, self._buf)
            self._buf = ""


_JOBS: Dict[str, _Job] = {}


def _new_job_id() -> str:
    return str(uuid.uuid4())


@router.get("/health")
async def health() -> dict:
    return {"ok": True}


@router.get("/debug/env")
async def debug_env() -> dict:
    def mask(v: Optional[str]) -> Optional[str]:
        if not v:
            return None
        vv = str(v)
        if len(vv) <= 8:
            return "*" * len(vv)
        return vv[:4] + "*" * (len(vv) - 8) + vv[-4:]

    return {
        "loaded_dotenv_files": LOADED_DOTENV_FILES,
        "settings": {
            "dspy_model": SETTINGS.dspy_model,
            "mcp_snowflake_url": SETTINGS.mcp_snowflake_url,
            "mcp_cortex_analyst_url": SETTINGS.mcp_cortex_analyst_url,
            "mcp_cortex_search_service_name": SETTINGS.mcp_cortex_search_service_name,
            "memory_max_turns": SETTINGS.memory_max_turns,
            "stream_chunk_chars": SETTINGS.stream_chunk_chars,
            "dspy_artifacts_dir": SETTINGS.dspy_artifacts_dir,
        },
        "aws_env_present": {
            "AWS_REGION": os.getenv("AWS_REGION"),
            "AWS_ACCESS_KEY_ID": mask(os.getenv("AWS_ACCESS_KEY_ID")),
            "AWS_SECRET_ACCESS_KEY": bool(os.getenv("AWS_SECRET_ACCESS_KEY")),
            "AWS_SESSION_TOKEN": bool(os.getenv("AWS_SESSION_TOKEN")),
        },
    }


@router.post("/admin/reload_artifacts")
async def admin_reload_artifacts(x_admin_key: Optional[str] = Header(default=None)) -> dict:
    _require_admin(x_admin_key)
    return {"ok": True, "result": reload_all()}


@router.get("/admin/logs/chat")
async def admin_logs_chat(limit: int = 200, x_admin_key: Optional[str] = Header(default=None)) -> dict:
    _require_admin(x_admin_key)
    limit = max(1, min(int(limit), 2000))
    rows = _read_jsonl_tail(chat_log_path(), limit=limit)
    return {"ok": True, "path": str(chat_log_path()), "rows": rows}


@router.get("/admin/logs/feedback")
async def admin_logs_feedback(
    limit: int = 200, x_admin_key: Optional[str] = Header(default=None)
) -> dict:
    _require_admin(x_admin_key)
    limit = max(1, min(int(limit), 2000))
    rows = _read_jsonl_tail(feedback_log_path(), limit=limit)
    return {"ok": True, "path": str(feedback_log_path()), "rows": rows}


class BuildDatasetsRequest(BaseModel):
    chat_log: str = Field(default=str(chat_log_path()))
    feedback_log: str = Field(default=str(feedback_log_path()))
    out_ranker: str = Field(default="agent/data/datasets/ranker.jsonl")
    out_relax: str = Field(default="agent/data/datasets/relaxed_constraints.jsonl")
    out_fusion: str = Field(default="agent/data/datasets/fusion.jsonl")
    async_run: bool = Field(default=True)


@router.post("/admin/datasets/build")
async def admin_build_datasets(
    req: BuildDatasetsRequest, x_admin_key: Optional[str] = Header(default=None)
) -> dict:
    _require_admin(x_admin_key)

    def run() -> dict:
        return build_datasets(
            chat_log=Path(req.chat_log),
            feedback_log=Path(req.feedback_log),
            out_ranker=Path(req.out_ranker),
            out_relax=Path(req.out_relax),
            out_fusion=Path(req.out_fusion),
        )

    if not req.async_run:
        return {"ok": True, "result": await asyncio.to_thread(run)}

    job_id = _new_job_id()
    _JOBS[job_id] = _Job(status="queued")

    async def task() -> None:
        _JOBS[job_id].status = "running"
        try:
            result = await asyncio.to_thread(run)
            _JOBS[job_id].status = "done"
            _JOBS[job_id].result = result
        except Exception as e:
            _JOBS[job_id].status = "error"
            _JOBS[job_id].error = str(e)

    asyncio.create_task(task())
    return {"ok": True, "job_id": job_id}


class CompileRequest(BaseModel):
    module: str = Field(..., description="relaxed_constraints|product_ranker|fusion_decision")
    dataset: str = Field(..., description="jsonl dataset path")
    out: str = Field(..., description="artifact output path (.json)")
    reload_artifacts: bool = Field(default=True)
    async_run: bool = Field(default=True)


@router.post("/admin/compile")
async def admin_compile(req: CompileRequest, x_admin_key: Optional[str] = Header(default=None)) -> dict:
    _require_admin(x_admin_key)

    def run(job_id: Optional[str] = None) -> dict:
        ensure_dspy_configured(model=SETTINGS.dspy_model)
        ds = Path(req.dataset)
        out = Path(req.out)
        if job_id:
            _job_append(job_id, f"[compile] module={req.module} dataset={ds} out={out}")
        if req.module == "relaxed_constraints":
            compile_relaxed_constraints(ds, out)
        elif req.module == "product_ranker":
            compile_product_ranker(ds, out)
        elif req.module == "fusion_decision":
            compile_fusion_decision(ds, out)
        else:
            raise ValueError("invalid module")
        reload_result = reload_all() if req.reload_artifacts else None
        return {"module": req.module, "dataset": str(ds), "out": str(out), "reload": reload_result}

    if not req.async_run:
        return {"ok": True, "result": await asyncio.to_thread(run)}

    job_id = _new_job_id()
    _JOBS[job_id] = _Job(status="queued")

    async def task() -> None:
        _JOBS[job_id].status = "running"
        _JOBS[job_id].updated_at = datetime.now(timezone.utc).isoformat()
        try:
            # Capture both print() and logging output during compile
            writer = _JobLogWriter(job_id)
            handler = logging.StreamHandler(writer)
            handler.setLevel(logging.INFO)
            root = logging.getLogger()
            root.addHandler(handler)
            try:
                with redirect_stdout(writer), redirect_stderr(writer):
                    result = await asyncio.to_thread(run, job_id)
            finally:
                root.removeHandler(handler)
                writer.flush()
            _JOBS[job_id].status = "done"
            _JOBS[job_id].result = result
        except Exception as e:
            _JOBS[job_id].status = "error"
            _JOBS[job_id].error = str(e)
        finally:
            _JOBS[job_id].updated_at = datetime.now(timezone.utc).isoformat()

    asyncio.create_task(task())
    return {"ok": True, "job_id": job_id}


@router.get("/admin/jobs/{job_id}")
async def admin_job_status(job_id: str, x_admin_key: Optional[str] = Header(default=None)) -> dict:
    _require_admin(x_admin_key)
    job = _JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return {
        "ok": True,
        "job_id": job_id,
        "status": job.status,
        "result": job.result,
        "error": job.error,
        "progress": job.progress,
        "logs_tail": job.logs[-120:],  # keep response small
        "updated_at": job.updated_at,
    }


@router.get("/admin/curation/state")
async def admin_curation_state(x_admin_key: Optional[str] = Header(default=None)) -> dict:
    _require_admin(x_admin_key)
    s = load_curation_state()
    return {
        "ok": True,
        "excluded_message_ids": s.excluded_message_ids,
        "quality_labels": s.quality_labels,
        "updated_at": s.updated_at,
    }


class CurationStateRequest(BaseModel):
    excluded_message_ids: list[str] = Field(default_factory=list)
    quality_labels: dict[str, str] = Field(default_factory=dict)  # good|bad|unknown


@router.post("/admin/curation/state")
async def admin_curation_state_upsert(
    req: CurationStateRequest, x_admin_key: Optional[str] = Header(default=None)
) -> dict:
    _require_admin(x_admin_key)
    excluded = [x for x in req.excluded_message_ids if isinstance(x, str) and x]
    quality: dict[str, str] = {}
    for k, v in (req.quality_labels or {}).items():
        if not isinstance(k, str) or not k:
            continue
        if v not in {"good", "bad", "unknown"}:
            continue
        quality[k] = v
    path = save_curation_state(
        CurationState(excluded_message_ids=excluded, quality_labels=quality, updated_at="")
    )
    return {
        "ok": True,
        "path": str(path),
        "excluded_message_ids": excluded,
        "quality_labels": quality,
    }

