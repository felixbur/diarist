"""FastAPI server: serves the view, the audio and the annotation."""

import logging
import os
import pathlib
import threading

import numpy as np
from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from diarist.controller.annotation import Annotation, Store, Turn
from diarist.controller.evaluation import score_annotation

log = logging.getLogger(__name__)

VIEW_DIR = pathlib.Path(__file__).parent / "view"


class Session(BaseModel):
    """Everything the view needs at start (``GET /api/session``)."""

    name: str
    duration: float
    waveform_rate: int
    merge_gap: float
    """Seconds; copying the predictions joins segments of a speaker closer than this."""
    predictions: list[Turn]
    annotation: Annotation


def create_app(
    annotation: Annotation,
    store: Store,
    predictions: list[Turn],
    playback: str | os.PathLike,
    waveform: np.ndarray,
    waveform_rate: int,
    merge_gap: float = 0.5,
) -> FastAPI:
    """App for annotating one file.

    ``playback`` is the audio file the browser plays, ``waveform`` the
    interleaved int8 min / max envelope with ``waveform_rate`` values per second.
    """
    app = FastAPI(title="Diarist")
    state = {"annotation": annotation}
    lock = threading.Lock()

    @app.middleware("http")
    async def no_cache(request, call_next):
        response = await call_next(request)
        response.headers.setdefault("Cache-Control", "no-cache")
        return response

    @app.get("/")
    async def index():
        return FileResponse(VIEW_DIR / "index.html")

    @app.get("/api/session")
    def session() -> Session:
        return Session(
            name=os.path.basename(annotation.audio),
            duration=annotation.duration,
            waveform_rate=waveform_rate,
            merge_gap=merge_gap,
            predictions=predictions,
            annotation=state["annotation"],
        )

    @app.get("/api/waveform")
    def get_waveform():
        return Response(waveform.tobytes(), media_type="application/octet-stream")

    @app.get("/audio")
    def audio():
        return FileResponse(playback)

    @app.put("/api/annotation")
    def put_annotation(new: Annotation):
        if new.audio != annotation.audio:
            raise HTTPException(409, f"annotation is for {new.audio}, not {annotation.audio}")
        with lock:
            store.save(new)
            state["annotation"] = new
        log.info("Saved %d segments of %d speakers", len(new.segments), len(new.speakers))
        return {"saved": len(new.segments)}

    scores: dict = {}  # last scored annotation -> score; slow for long files (seconds per hour of audio)
    score_lock = threading.Lock()

    @app.get("/api/score")
    def score() -> dict | None:
        """DER of the predictions on the labelled part of the current annotation,
        see :func:`~diarist.controller.evaluation.score_annotation`."""
        with score_lock:
            current = state["annotation"]
            if scores.get("annotation") is not current:
                scores.update(annotation=current, score=score_annotation(current, predictions))
            return scores["score"]

    app.mount("/static", StaticFiles(directory=VIEW_DIR), name="static")
    return app
