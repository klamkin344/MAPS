"""
api.py
======

FastAPI wrapper around generate_city_poster.py.

Flow:
    Lovable frontend --> POST /generate --> this API
                                              |
                                              v
                                   generate_city_poster.generate_poster()
                                              |
                                              v
                                   saves PNG to /static/output/...
                                              |
                                              v
                          returns {"status": "ready", "url": "..."}

Run locally:
    pip install fastapi uvicorn python-multipart --break-system-packages
    uvicorn api:app --host 0.0.0.0 --port 8000

n8n then just does an HTTP Request node -> POST http://your-server:8000/generate
with the JSON body below, and passes the returned "url" straight back
to the Lovable frontend (or downloads the file and re-uploads it to
S3/Cloudinary for a permanent link).

For production: put this behind a queue (Celery/RQ) instead of
generating synchronously, since map rendering can take 5-20s per
request and you don't want to block the HTTP connection / risk a
timeout on slow cities. The job-status pattern below shows the shape
of that without wiring up a real queue - swap BackgroundTasks for a
real worker when you scale past a handful of orders/day.
"""

import os
import uuid
from typing import Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from generate_city_poster import STYLE_PRESETS, generate_poster

OUTPUT_DIR = "output"
os.makedirs(OUTPUT_DIR, exist_ok=True)

app = FastAPI(title="City Poster Map API")
app.mount("/files", StaticFiles(directory=OUTPUT_DIR), name="files")

# In-memory job store. Swap for Redis/DB once you have concurrent
# traffic - this resets whenever the process restarts.
JOBS: dict[str, dict] = {}


class GenerateRequest(BaseModel):
    city: str = Field(..., examples=["Tel Aviv, Israel"])
    style: str = Field("minimal_light", examples=list(STYLE_PRESETS.keys()))
    radius_m: int = Field(1500, ge=300, le=5000)
    width_cm: float = Field(30, gt=0)
    height_cm: float = Field(40, gt=0)
    dpi: int = Field(300, ge=72, le=600)
    caption: Optional[str] = None


class GenerateResponse(BaseModel):
    job_id: str
    status: str


class StatusResponse(BaseModel):
    job_id: str
    status: str
    url: Optional[str] = None
    error: Optional[str] = None


def _run_generation(job_id: str, req: GenerateRequest, base_url: str) -> None:
    print(f"[job {job_id}] starting: city={req.city!r} style={req.style} radius={req.radius_m}", flush=True)
    try:
        path = generate_poster(
            city=req.city,
            style=req.style,
            radius_m=req.radius_m,
            size_cm=(req.width_cm, req.height_cm),
            dpi=req.dpi,
            caption=req.caption,
            output_dir=OUTPUT_DIR,
        )
        filename = os.path.basename(path)
        JOBS[job_id] = {
            "status": "ready",
            "url": f"{base_url}/files/{filename}",
            "error": None,
        }
        print(f"[job {job_id}] done: {filename}", flush=True)
    except Exception as exc:  # noqa: BLE001 - surface any failure to the client
        import traceback
        print(f"[job {job_id}] FAILED: {exc}", flush=True)
        traceback.print_exc()
        JOBS[job_id] = {"status": "failed", "url": None, "error": str(exc)}


@app.get("/styles")
def list_styles() -> dict:
    """So the Lovable frontend can populate a style picker dynamically."""
    return {"styles": list(STYLE_PRESETS.keys())}


@app.post("/generate", response_model=GenerateResponse)
def generate(req: GenerateRequest, background_tasks: BackgroundTasks) -> GenerateResponse:
    if req.style not in STYLE_PRESETS:
        raise HTTPException(400, f"Unknown style '{req.style}'. Options: {list(STYLE_PRESETS)}")

    job_id = str(uuid.uuid4())
    JOBS[job_id] = {"status": "processing", "url": None, "error": None}

    # NOTE: base_url is hardcoded for the example - in production read
    # it from an env var (PUBLIC_BASE_URL) that matches your deployed host.
    base_url = os.environ.get("PUBLIC_BASE_URL", "http://localhost:8000")
    background_tasks.add_task(_run_generation, job_id, req, base_url)

    return GenerateResponse(job_id=job_id, status="processing")


@app.get("/status/{job_id}", response_model=StatusResponse)
def status(job_id: str) -> StatusResponse:
    job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, "Unknown job_id")
    return StatusResponse(job_id=job_id, **job)


@app.get("/download/{filename}")
def download(filename: str) -> FileResponse:
    path = os.path.join(OUTPUT_DIR, filename)
    if not os.path.isfile(path):
        raise HTTPException(404, "File not found")
    return FileResponse(path, media_type="image/png", filename=filename)