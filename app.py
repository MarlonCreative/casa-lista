"""Casa Lista web app.

Upload (or record) a home walkthrough video -> survey -> offline-first design -> safety routing
-> validated Home Assistant config. The page polls for progress, so each stage shows up as it lands.

Run:   uvicorn app:app --host 0.0.0.0 --port 8000
Then open http://localhost:8000 on the Mac, or http://<your-mac-ip>:8000 on a phone on the same Wi-Fi.
"""
from __future__ import annotations

import json
import threading
import time
import traceback
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import pipeline
import validator

ROOT = Path(__file__).parent
RUNS = ROOT / "runs"
RUNS.mkdir(exist_ok=True)

app = FastAPI(title="Casa Lista")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")

JOBS: dict[str, dict] = {}
LOCK = threading.Lock()


def _set(job_id: str, **updates) -> None:
    """Update a job's state and save it to runs/<id>/result.json (so eval and the README can use it)."""
    with LOCK:
        JOBS[job_id].update(updates)
        data = json.dumps(JOBS[job_id], ensure_ascii=False, indent=2, default=str)
    (RUNS / job_id / "result.json").write_text(data)


def _timed(timings: dict, key: str, fn, *args):
    t = time.time()
    out = fn(*args)
    timings[key] = round(time.time() - t, 2)
    return out


def _run(job_id: str, video_path: Path, place: str, grid: str, household: str, language: str, validate: bool) -> None:
    job = pipeline.Job(video_path=str(video_path), place=place or "a rural home", grid=grid,
                       household=household, language=language)
    timings: dict = {}
    start = time.time()
    try:
        _set(job_id, stage="uploading")
        video = _timed(timings, "upload_s", pipeline.upload_video, job.video_path)

        _set(job_id, stage="surveying", timings=timings)
        inventory = _timed(timings, "surveyor_s", pipeline.survey, job, video)

        _set(job_id, stage="designing", inventory=inventory, timings=timings)
        design = _timed(timings, "architect_s", pipeline.design, job, inventory)

        _set(job_id, stage="safety", design=design, timings=timings)
        safety = _timed(timings, "safety_s", pipeline.safety_gate, design)

        timings["plan_total_s"] = round(time.time() - start, 1)
        _set(job_id, stage="building" if validate else "done", safety=safety, timings=timings)

        if validate:
            # A builder failure should not throw away the plan, so it gets its own try.
            try:
                build = _timed(timings, "builder_s", validator.build_and_validate, design)
            except Exception as e:  # noqa: BLE001
                build = {"passed": False, "first_pass_valid": False, "error": f"{type(e).__name__}: {e}"}
            timings["total_s"] = round(time.time() - start, 1)
            _set(job_id, stage="done", build=build, timings=timings)
    except Exception as e:  # noqa: BLE001
        _set(job_id, stage="error", error=f"{type(e).__name__}: {e}",
             trace=traceback.format_exc()[-2000:], timings=timings)


@app.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html")


@app.post("/api/jobs")
async def create_job(
    video: UploadFile = File(...),
    place: str = Form(""),
    grid: str = Form("semi-grid: grid power that cuts out often"),
    household: str = Form(""),
    language: str = Form("Spanish"),
    validate: bool = Form(True),
):
    job_id = time.strftime("%H%M%S-") + uuid.uuid4().hex[:6]
    folder = RUNS / job_id
    folder.mkdir(parents=True)
    suffix = Path(video.filename or "walkthrough.mp4").suffix.lower() or ".mp4"
    video_path = folder / f"walkthrough{suffix}"
    with video_path.open("wb") as f:
        while chunk := await video.read(1024 * 1024):
            f.write(chunk)

    with LOCK:
        JOBS[job_id] = {"id": job_id, "stage": "queued", "created": time.time(), "place": place, "grid": grid,
                        "household": household, "language": language, "video_file": video_path.name}
    threading.Thread(target=_run, args=(job_id, video_path, place, grid, household, language, validate),
                     daemon=True).start()
    return {"id": job_id}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    with LOCK:
        if job_id in JOBS:
            return JOBS[job_id]
    saved = RUNS / job_id / "result.json"
    if saved.exists():
        return json.loads(saved.read_text())
    raise HTTPException(404, "No such job")


@app.get("/api/jobs")
def list_jobs():
    with LOCK:
        return sorted(({"id": j["id"], "stage": j["stage"]} for j in JOBS.values()),
                      key=lambda j: j["id"], reverse=True)
