"""Ground-truth annotation: data model, storage and exports.

An annotation folder (``annotations/<audio name>/``) holds

* ``predictions.csv``: the predicted speakers
  (audformat, ``file, start, end`` index, ``speaker`` column)
* ``predictions.yaml``: the settings these predictions were made with
* ``annotation.json``: the annotation as edited in the view (speakers with
  their names, segments referring to speaker ids); loaded again on the next start
* ``ground_truth.csv``, ``ground_truth.rttm``, ``ground_truth.TextGrid``:
  exports with speaker names, rewritten on every save

Speaker ids are the predicted labels (``S1``, ``S2``, ...) or ``N1``, ``N2``, ...
for speakers added in the view; names can be changed freely.
"""

import json
import logging
import os
import pathlib

import audformat
import pandas as pd
import yaml
from pydantic import BaseModel, model_validator

log = logging.getLogger(__name__)


class Speaker(BaseModel):
    id: str
    name: str


class Turn(BaseModel):
    start: float
    end: float
    speaker: str
    """Speaker id (annotation) or predicted label (predictions)."""


class Annotation(BaseModel):
    audio: str
    """Path of the annotated audio file."""
    duration: float
    speakers: list[Speaker]
    segments: list[Turn]

    @model_validator(mode="after")
    def check(self):
        ids = [s.id for s in self.speakers]
        if len(set(ids)) != len(ids):
            raise ValueError("speaker ids must be unique")
        for seg in self.segments:
            if not 0 <= seg.start < seg.end:
                raise ValueError(f"invalid segment {seg.start}-{seg.end}")
            if seg.speaker not in ids:
                raise ValueError(f"unknown speaker {seg.speaker!r}")
        self.segments.sort(key=lambda s: (s.start, s.end))
        return self

    @classmethod
    def from_predictions(cls, audio: str, duration: float, predictions: list[Turn]) -> "Annotation":
        """Empty annotation with one speaker per predicted label, in order of appearance."""
        ids = list(dict.fromkeys(p.speaker for p in sorted(predictions, key=lambda p: p.start)))
        return cls(audio=audio, duration=duration, speakers=[Speaker(id=i, name=i) for i in ids], segments=[])

    def add_speakers(self, predictions: list[Turn]):
        """Add predicted speakers that are not in the annotation yet (after predicting again)."""
        known = {s.id for s in self.speakers}
        for p in sorted(predictions, key=lambda p: p.start):
            if p.speaker not in known:
                self.speakers.append(Speaker(id=p.speaker, name=p.speaker))
                known.add(p.speaker)

    def named_turns(self) -> list[Turn]:
        """Segments with speaker names instead of ids."""
        names = {s.id: s.name for s in self.speakers}
        return [Turn(start=s.start, end=s.end, speaker=names[s.speaker]) for s in self.segments]


class Store:
    """The files of one annotation folder."""

    def __init__(self, folder: str | os.PathLike):
        self.dir = pathlib.Path(folder)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.predictions_path = self.dir / "predictions.csv"
        self.settings_path = self.dir / "predictions.yaml"
        self.annotation_path = self.dir / "annotation.json"

    @staticmethod
    def peek(folder: str | os.PathLike) -> "Annotation | None":
        """The annotation stored in ``folder``, without creating the folder."""
        path = pathlib.Path(folder) / "annotation.json"
        return Annotation.model_validate_json(path.read_text()) if path.is_file() else None

    def load_predictions(self) -> list[Turn] | None:
        if not self.predictions_path.exists():
            return None
        df = audformat.utils.read_csv(self.predictions_path, as_dataframe=True)
        return [
            Turn(start=start.total_seconds(), end=end.total_seconds(), speaker=str(speaker))
            for (_, start, end), speaker in df["speaker"].items()
        ]

    def load_prediction_settings(self) -> dict | None:
        """Pipeline settings of the stored predictions, ``None`` if unknown."""
        if not self.settings_path.exists():
            return None
        with open(self.settings_path) as fp:
            return yaml.safe_load(fp)

    def save_predictions(self, audio: str, predictions: list[Turn], settings: dict):
        _turns_frame(audio, predictions).to_csv(self.predictions_path)
        with open(self.settings_path, "w") as fp:
            yaml.safe_dump(settings, fp, sort_keys=False)

    def load_annotation(self) -> Annotation | None:
        if not self.annotation_path.exists():
            return None
        return Annotation.model_validate_json(self.annotation_path.read_text())

    def save(self, annotation: Annotation):
        """Store the annotation and rewrite the exports."""
        tmp = self.annotation_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(annotation.model_dump(), indent=1))
        tmp.replace(self.annotation_path)  # never leave a half written annotation
        turns = annotation.named_turns()
        _turns_frame(annotation.audio, turns).to_csv(self.dir / "ground_truth.csv")
        write_rttm(self.dir / "ground_truth.rttm", annotation.audio, turns)
        write_textgrid(self.dir / "ground_truth.TextGrid", turns, annotation.duration)


def _turns_frame(audio: str, turns: list[Turn]) -> pd.DataFrame:
    """audformat segmented table with a ``speaker`` column."""
    file = os.path.basename(audio)
    index = audformat.segmented_index(
        [file] * len(turns),
        [pd.Timedelta(seconds=round(t.start, 3)) for t in turns],
        [pd.Timedelta(seconds=round(t.end, 3)) for t in turns],
    )
    return pd.DataFrame({"speaker": [t.speaker for t in turns]}, index=index)


def write_rttm(path: str | os.PathLike, audio: str, turns: list[Turn]):
    file_id = os.path.splitext(os.path.basename(audio))[0].replace(" ", "_")
    with open(path, "w", encoding="utf-8") as fp:
        for t in turns:
            name = t.speaker.replace(" ", "_")
            fp.write(f"SPEAKER {file_id} 1 {t.start:.3f} {t.end - t.start:.3f} <NA> <NA> {name} <NA> <NA>\n")


def _intervals(turns: list[Turn], duration: float) -> list[tuple[float, float, str]]:
    """Intervals of one TextGrid tier, gaps as empty intervals; a tier cannot hold
    overlaps, so a segment is clipped to the end of the one before."""
    intervals = []
    pos = 0.0
    for t in sorted(turns, key=lambda t: (t.start, t.end)):
        start, end = max(round(t.start, 3), pos), round(t.end, 3)
        if end <= start + 1e-9:
            continue
        if start > pos + 1e-9:
            intervals.append((pos, start, ""))
        intervals.append((start, end, t.speaker))
        pos = end
    if pos < duration - 1e-9:
        intervals.append((pos, duration, ""))
    return intervals


def write_textgrid(path: str | os.PathLike, turns: list[Turn], duration: float):
    """Praat TextGrid with one interval tier per speaker, so overlapping speech is kept."""
    names = list(dict.fromkeys(t.speaker for t in turns))
    lines = [
        'File type = "ooTextFile"',
        'Object class = "TextGrid"',
        "",
        "xmin = 0",
        f"xmax = {duration}",
        "tiers? <exists>",
        f"size = {len(names)}",
        "item []:",
    ]
    for n, name in enumerate(names, 1):
        intervals = _intervals([t for t in turns if t.speaker == name], duration)
        lines += [
            f"    item [{n}]:",
            '        class = "IntervalTier"',
            f'        name = "{name.replace('"', '""')}"',
            "        xmin = 0",
            f"        xmax = {duration}",
            f"        intervals: size = {len(intervals)}",
        ]
        for i, (s, e, label) in enumerate(intervals, 1):
            lines += [
                f"        intervals [{i}]:",
                f"            xmin = {s}",
                f"            xmax = {e}",
                f'            text = "{label.replace('"', '""')}"',
            ]
    with open(path, "w", encoding="utf-8") as fp:
        fp.write("\n".join(lines) + "\n")
