"""Diarization error rate (DER) of predicted speakers against a ground truth, with :mod:`audmetric`.

    DER = (speaker confusion + false alarm + missed speech) / ground-truth speech

Files are given as RTTM, audformat CSV (``file, start, end`` index and a
speaker column) or an annotation folder (predictions against ground truth)::

    diarist-der annotations/speech
    diarist-der ground_truth.rttm predictions.rttm
    diarist-der truth.csv my_system.rttm --pyannote --audio-root /data/audio   # pyannote for comparison
"""

import argparse
import logging
import os
import pathlib

import audformat
import audmetric
import pandas as pd
import soundfile as sf

from diarist.controller.annotation import Annotation, Speaker, Store, Turn


def file_id(path: str) -> str:
    """Name of an audio file without folder and extension, as in RTTM."""
    return os.path.splitext(os.path.basename(path))[0]


def read_turns(path: str | os.PathLike, column: str = "speaker") -> dict[str, list[Turn]]:
    """Segments per file of an RTTM or audformat CSV file.

    Files as named in the file: paths for CSV, file ids for RTTM.
    """
    path = pathlib.Path(path)
    turns: dict[str, list[Turn]] = {}
    if path.suffix.lower() == ".rttm":
        for line in path.read_text().splitlines():
            fields = line.split()
            if not fields or fields[0] != "SPEAKER":
                continue
            start, duration = float(fields[3]), float(fields[4])
            turns.setdefault(fields[1], []).append(Turn(start=start, end=start + duration, speaker=fields[7]))
    else:
        df = audformat.utils.read_csv(path, as_dataframe=True)
        if column not in df.columns:
            raise ValueError(f"no column {column!r} in {path}, available: {list(df.columns)}")
        for (file, start, end), speaker in df[column].dropna().items():
            turns.setdefault(str(file), []).append(
                Turn(start=start.total_seconds(), end=end.total_seconds(), speaker=str(speaker))
            )
    return turns


def read_labels(path: str | os.PathLike, column: str = "speaker") -> pd.Series:
    """Speaker labels of an RTTM or audformat CSV file.

    Returns a series with a segmented index whose files are file ids
    (see :func:`file_id`), so RTTM and CSV files can be compared.
    """
    series = [to_labels(turns, file_id(file)) for file, turns in read_turns(path, column).items()]
    return pd.concat(series) if series else to_labels([])


def to_labels(turns: list[Turn], file: str = "audio") -> pd.Series:
    """Speaker labels of segments, as series with a segmented index."""
    index = audformat.segmented_index([file] * len(turns), [t.start for t in turns], [t.end for t in turns])
    return pd.Series([t.speaker for t in turns], index=index, dtype="object")


def score_annotation(annotation: Annotation, predictions: list[Turn]) -> dict | None:
    """DER of the predictions on the part labelled so far, for the view.

    Only the time up to the end of the last ground-truth segment is scored,
    predictions are clipped to it, so a partly labelled file is not dominated
    by false alarms. Returns the rates of :func:`evaluate` plus ``until``
    (seconds), or ``None`` without ground truth or predictions.
    """
    truth = annotation.named_turns()
    if not truth or not predictions:
        return None
    until = max(t.end for t in truth)
    clipped = [
        Turn(start=p.start, end=min(p.end, until), speaker=p.speaker) for p in predictions if p.start < until
    ]
    return {**_rates(to_labels(truth), to_labels(clipped)), "until": until}


def evaluate(truth: pd.Series, prediction: pd.Series) -> pd.DataFrame:
    """DER and its components per file of ``truth``, and for all files together (row ``total``).

    Columns ``der``, ``confusion``, ``false_alarm``, ``missed`` (rates relative to
    the ground-truth speech) and ``speech`` (seconds).
    The speakers are mapped per file. Files without prediction count as missed speech.
    """
    rows = {}
    files = list(dict.fromkeys(truth.index.get_level_values("file")))
    for file in files:
        rows[file] = _rates(_file(truth, file), _file(prediction, file))
    if len(files) > 1:
        rows["total"] = _rates(truth, prediction, individual_file_mapping=True)
    return pd.DataFrame.from_dict(rows, orient="index")


def _file(labels: pd.Series, file: str) -> pd.Series:
    return labels[labels.index.get_level_values("file") == file]


def _rates(truth: pd.Series, prediction: pd.Series, **kwargs) -> dict:
    speech = float(sum((end - start).total_seconds() for _, start, end in truth.index))
    if prediction.empty:  # audmetric needs at least one predicted segment
        der, conf, fa, miss = 1.0, 0.0, 0.0, 1.0
    else:
        der, details = audmetric.diarization_error_rate_detailed(truth, prediction, **kwargs)
        conf, fa, miss = details.conf_rate, details.fa_rate, details.miss_rate
    return {"der": der, "confusion": conf, "false_alarm": fa, "missed": miss, "speech": speech}


AUDIO_EXTENSIONS = (".wav", ".flac", ".mp3", ".ogg", ".opus", ".m4a")


def find_audio(name: str, roots: list[pathlib.Path]) -> str | None:
    """Audio file ``name`` (a path, a file name, or an RTTM file id without extension) in ``roots``."""
    path = pathlib.Path(name)
    candidates = [path] if path.is_absolute() else []
    for root in roots:
        candidates += [root / name, root / path.name]
        if not path.suffix:
            candidates += [root / (name + ext) for ext in AUDIO_EXTENSIONS]
    return next((str(c.resolve()) for c in candidates if c.is_file()), None)


def load_ground_truth(
    sources: list[str], audio_root: str | None = None, column: str = "speaker"
) -> list[Annotation]:
    """Ground truth of annotation folders, audformat CSV or RTTM files, one annotation per audio file.

    An annotation folder gives its ``annotation.json``, or its ``ground_truth.csv`` without it.
    Audio files are looked for in ``audio_root``, next to the CSV / RTTM file, one folder up
    and in the current folder (and at the path in ``annotation.json``).
    """
    annotations = []
    for source in sources:
        path = pathlib.Path(source)
        roots = [pathlib.Path(r) for r in [audio_root] if r] + [pathlib.Path.cwd()]
        if path.is_dir():
            annotation = Store(path).load_annotation()
            if annotation is not None:
                audio = find_audio(annotation.audio, [pathlib.Path(annotation.audio).parent, *roots])
                if audio is None:
                    raise ValueError(f"audio of {path} not found: {annotation.audio} (--audio-root)")
                if not annotation.segments:
                    raise ValueError(f"no ground truth in {path}")
                annotations.append(annotation.model_copy(update={"audio": audio}))
                continue
            if not (path / "ground_truth.csv").exists():
                raise ValueError(f"no annotation.json or ground_truth.csv in {path}")
            path = path / "ground_truth.csv"
        elif not path.is_file():
            raise ValueError(f"no such file or folder: {path}")
        for file, turns in read_turns(path, column).items():
            # next to the CSV / RTTM, or one folder up (data/<name>/ground_truth.csv, data/<name>.wav)
            audio = find_audio(file, [*roots[:-1], path.parent, path.parent.parent, roots[-1]])
            if audio is None:
                raise ValueError(f"audio {file} of {path} not found (--audio-root)")
            speakers = list(dict.fromkeys(t.speaker for t in turns))
            annotations.append(
                Annotation(
                    audio=audio,
                    duration=sf.info(audio).duration,
                    speakers=[Speaker(id=s, name=s) for s in speakers],
                    segments=turns,
                )
            )
    return annotations


def build_parser() -> argparse.ArgumentParser:
    """Command line of ``diarist-der``."""
    parser = argparse.ArgumentParser(
        prog="diarist-der", description="Diarization error rate of predicted speakers against a ground truth."
    )
    parser.add_argument(
        "truth", help="ground truth: RTTM or audformat CSV, or an annotation folder (then its predictions are scored)"
    )
    parser.add_argument("prediction", nargs="?", help="predictions: RTTM or audformat CSV")
    parser.add_argument("--column", default="speaker", help="speaker column of CSV files")
    parser.add_argument(
        "--pyannote", action="store_true", help="also score pyannote speaker diarization (needs a Hugging Face token)"
    )
    parser.add_argument("--audio-root", help="folder with the audio files (for --pyannote)")
    parser.add_argument("--config", help="YAML file overriding the default configuration (--pyannote)")
    parser.add_argument("-v", "--verbose", action="store_true", help="debug output")
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    truth, prediction = args.truth, args.prediction
    if os.path.isdir(truth):
        if prediction is None and os.path.exists(os.path.join(truth, "predictions.csv")):
            prediction = os.path.join(truth, "predictions.csv")
        truth = os.path.join(truth, "ground_truth.csv")
    if prediction is None and not args.pyannote:
        parser.error("give a prediction file, an annotation folder with predictions as truth, or --pyannote")
    truth_labels = read_labels(truth, args.column)
    if truth_labels.empty:
        parser.error(f"no ground-truth segments in {truth}")
    truth_files = set(truth_labels.index.get_level_values("file"))

    systems: dict[str, pd.Series] = {}
    if prediction is not None:
        systems["predictions" if args.prediction is None else "prediction"] = read_labels(prediction, args.column)
    if args.pyannote:
        from diarist.config import load_config
        from diarist.model.predict import hf_token, predict

        settings = load_config(args.config)["prediction"]
        token = hf_token(settings)
        if token is None:
            parser.error(
                "--pyannote needs a Hugging Face token: prediction.hf_token in the configuration, HF_TOKEN or hf auth login"
            )
        try:
            annotations = load_ground_truth([args.truth], args.audio_root, args.column)
            systems[settings["model"].split("/")[-1]] = pd.concat([
                to_labels(predict(a.audio, settings, token, f"file {i} of {len(annotations)}"), file_id(a.audio))
                for i, a in enumerate(annotations, 1)
            ])
        except (ValueError, RuntimeError) as e:
            parser.error(str(e))
    for name, labels in systems.items():
        for file in sorted(set(labels.index.get_level_values("file")) - truth_files):
            print(f"Not scored ({name}), no ground truth: {file}")

    rows = [(file, name, r) for name, labels in systems.items() for file, r in evaluate(truth_labels, labels).iterrows()]
    rows.sort(key=lambda row: (row[0] == "total", row[0]))  # each file with all systems, total last
    width = max(len(str(f)) for f in [*(row[0] for row in rows), "file"])
    sys_width = max(len(n) for n in [*systems, "system"])
    print(
        f"{'file':<{width}}  {'system':<{sys_width}}  {'DER':>7}  {'confusion':>9}  {'false al.':>9}"
        f"  {'missed':>7}  {'speech':>8}"
    )
    for file, name, r in rows:
        print(
            f"{file:<{width}}  {name:<{sys_width}}  {100 * r.der:6.1f}%  {100 * r.confusion:8.1f}%"
            f"  {100 * r.false_alarm:8.1f}%  {100 * r.missed:6.1f}%  {r.speech:7.1f}s"
        )


if __name__ == "__main__":
    main()
