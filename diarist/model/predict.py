"""Speaker predictions with a pyannote speaker diarization pipeline, settings in ``prediction``.

The pipelines are gated on Hugging Face, so predictions need a token
(:func:`hf_token`): ``prediction.hf_token`` in the configuration, the
environment variable ``HF_TOKEN`` or the token stored by ``hf auth login``.
Without one, diarist starts without predictions.

pyannote needs torch, so it runs as a script in its own environment
(:mod:`diarist.model.pyannote_run`, by default with ``uv run --script``, which
creates the environment from the script's dependencies on first use).
Results are cached per audio file and settings.
"""

import hashlib
import json
import logging
import os
import pathlib
import subprocess
import sys

from diarist.controller.annotation import Turn

log = logging.getLogger(__name__)

SCRIPT = pathlib.Path(__file__).parent / "pyannote_run.py"
TOKEN_VARIABLE = "HF_TOKEN"
SPEAKER_SETTINGS = ("num_speakers", "min_speakers", "max_speakers")


def hf_token(config: dict) -> str | None:
    """Hugging Face token, ``None`` without.

    In this order: ``hf_token`` of the ``prediction`` section ``config``,
    the environment variable ``HF_TOKEN``, the token stored by ``hf auth login``
    (see :func:`hf_token_path`).
    """
    for token in (config.get("hf_token"), os.environ.get(TOKEN_VARIABLE)):
        if token and str(token).strip():
            return str(token).strip()
    try:
        token = hf_token_path().read_text().strip()
    except OSError:
        return None
    return token or None


def hf_token_path() -> pathlib.Path:
    """File of the token stored by ``hf auth login`` (``huggingface-cli login``), as huggingface_hub finds it:
    ``HF_TOKEN_PATH``, else ``$HF_HOME/token``, else ``~/.cache/huggingface/token``."""
    if os.environ.get("HF_TOKEN_PATH"):
        return pathlib.Path(os.path.expanduser(os.environ["HF_TOKEN_PATH"]))
    cache = os.environ.get("XDG_CACHE_HOME") or os.path.join("~", ".cache")
    home = os.environ.get("HF_HOME") or os.path.join(cache, "huggingface")
    return pathlib.Path(os.path.expanduser(home)) / "token"


def settings(config: dict) -> dict:
    """The settings of the ``prediction`` section ``config`` that change the predictions.

    Stored with the predictions (``predictions.yaml``), so never the token.
    """
    return {"model": config["model"], **{key: config.get(key) for key in SPEAKER_SETTINGS}}


def predict(audio: str, config: dict, token: str, label: str = "") -> list[Turn]:
    """Predicted speaker segments of ``audio``, speakers ``S1``, ``S2``, ... in order of appearance.

    ``config`` is the ``prediction`` section of the configuration, ``token`` the Hugging Face token.
    The script's output (environment setup, progress bars) goes to the terminal;
    ``label`` is shown before, e.g. ``"file 2 of 5"``.
    Raises :class:`RuntimeError` if pyannote fails.
    """
    from diarist.controller.evaluation import read_turns

    audio = os.path.abspath(audio)
    stat = os.stat(audio)
    current = settings(config)
    key = json.dumps([audio, stat.st_size, stat.st_mtime_ns, current], sort_keys=True)
    cache = pathlib.Path(os.path.expanduser(config["cache"]))
    rttm = cache / f"{pathlib.Path(audio).stem}-{hashlib.sha1(key.encode()).hexdigest()[:12]}.rttm"
    if rttm.exists():
        log.info("Using cached pyannote result %s", rttm)
    else:
        cache.mkdir(parents=True, exist_ok=True)
        command = [*config["command"], str(SCRIPT), audio, str(rttm), "--model", current["model"]]
        command += ["--device", config["device"]]
        for name in SPEAKER_SETTINGS:
            if current[name]:
                command += [f"--{name.replace('_', '-')}", str(int(current[name]))]
        log.info("Predicting speakers with %s%s: %s", current["model"], f" ({label})" if label else "", audio)
        sys.stdout.flush()
        env = {**os.environ, TOKEN_VARIABLE: token}  # not on the command line, where other users could see it
        try:
            returncode = subprocess.run(command, env=env).returncode  # output to the terminal, for progress
        except FileNotFoundError as e:
            raise RuntimeError(f"cannot run {command[0]!r} (prediction.command): {e}") from e
        if returncode != 0:
            raise RuntimeError(f"pyannote failed on {audio}, see the output above")
    turns = sorted((t for turns in read_turns(rttm).values() for t in turns), key=lambda t: (t.start, t.end))
    names: dict[str, str] = {}
    for t in turns:
        names.setdefault(t.speaker, f"S{len(names) + 1}")
    return [t.model_copy(update={"speaker": names[t.speaker]}) for t in turns]
