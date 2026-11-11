"""Label ground-truth speakers of an audio file.

    diarist speech.wav                    # predict speakers (with a Hugging Face token), then annotate
    diarist speech.wav --speakers 2       # fixed number of predicted speakers
    diarist speech.wav --no-predictions   # annotate without predictions
"""

import argparse
import logging
import os
import pathlib
import webbrowser

import soundfile as sf
import uvicorn

from diarist.config import load_config
from diarist.controller.annotation import Annotation, Store, Turn
from diarist.controller.audio import SAMPLING_RATE, envelope, load_signal
from diarist.server import create_app

log = logging.getLogger("diarist")

# formats browsers play; others are converted for playback
PLAYABLE = {".wav", ".mp3", ".ogg", ".flac", ".opus", ".m4a", ".webm"}


def build_parser() -> argparse.ArgumentParser:
    """Command line of ``diarist``."""
    parser = argparse.ArgumentParser(prog="diarist", description=__doc__.split("\n")[0])
    parser.add_argument("audio", help="audio file to annotate")
    parser.add_argument(
        "--out",
        help="annotation folder (default: the one next to the audio, else <storage.root>/<audio name>)",
    )
    parser.add_argument("--config", help="YAML file overriding the default configuration")
    parser.add_argument("--speakers", type=int, help="fixed number of predicted speakers, 0 = detect")
    parser.add_argument(
        "--repredict", action="store_true", help="predict again, even if stored predictions have the same settings"
    )
    parser.add_argument(
        "--restart", action="store_true", help="discard the stored annotation and start again with an empty one"
    )
    parser.add_argument(
        "--no-predictions", action="store_true", help="annotate without predictions (none are computed or shown)"
    )
    parser.add_argument("--no-browser", action="store_true", help="do not open the view in the browser")
    parser.add_argument("--host", help="address to serve the view on, overrides config (0.0.0.0: all interfaces)")
    parser.add_argument("--port", type=int, help="port of the view, overrides config")
    parser.add_argument("-v", "--verbose", action="store_true", help="debug output")
    return parser


def find_annotation(audio: str) -> pathlib.Path | None:
    """Annotation folder of ``audio`` next to it: its own folder (``data/<name>/<name>.wav``)
    or a folder of its name beside it (``data/<name>.wav``, ``data/<name>/``)."""
    path = pathlib.Path(audio)
    for folder in (path.parent, path.parent / path.stem):
        annotation = Store.peek(folder)
        if annotation is not None and os.path.basename(annotation.audio) == path.name:
            return folder
    return None


def load_predictions(store: Store, audio: str, config: dict, repredict: bool = False) -> list[Turn]:
    """Predictions of ``audio``: the stored ones if made with the current settings, else new ones
    if there is a Hugging Face token, else the stored ones or none.

    ``config`` is the ``prediction`` section of the configuration.
    """
    from diarist.model import predict

    settings = predict.settings(config)
    token = predict.hf_token(config)
    stored = store.load_predictions()
    if stored is not None and not repredict and store.load_prediction_settings() == settings:
        log.info("Using stored predictions (--repredict to compute them again)")
        return stored
    if token is None:
        if stored is not None:
            log.warning("No Hugging Face token to predict again: using the stored predictions")
            return stored
        log.warning(
            "No Hugging Face token (prediction.hf_token in the configuration, HF_TOKEN or hf auth login): starting without "
            "predictions. With a token, %s predicts the speakers as reference.",
            config["model"],
        )
        return []
    if stored is not None and not repredict:
        log.info("Prediction settings changed since the stored predictions, predicting again")
    predictions = predict.predict(audio, config, token)
    store.save_predictions(audio, predictions, settings)
    return predictions


def main():
    parser = build_parser()
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    for noisy in ["urllib3", "httpx", "httpcore", "asyncio", "multipart"]:
        logging.getLogger(noisy).setLevel(logging.WARNING)

    config = load_config(args.config)
    if args.speakers is not None:
        config["prediction"]["num_speakers"] = args.speakers or None
    audio = os.path.abspath(args.audio)
    if not os.path.isfile(audio):
        parser.error(f"no such file: {args.audio}")
    name = os.path.splitext(os.path.basename(audio))[0]
    store = Store(args.out or find_annotation(audio) or pathlib.Path(config["storage"]["root"]) / name)
    log.info("Annotation folder: %s", store.dir)

    signal = load_signal(audio)
    duration = len(signal) / SAMPLING_RATE

    if args.no_predictions:
        predictions = []
    else:
        try:
            predictions = load_predictions(store, audio, config["prediction"], args.repredict)
        except RuntimeError as e:
            parser.exit(1, f"Error: {e}\n(--no-predictions to annotate without them)\n")

    annotation = None if args.restart else store.load_annotation()
    if annotation is not None:
        if os.path.basename(annotation.audio) != os.path.basename(audio):
            parser.error(f"{store.annotation_path} belongs to {annotation.audio}, use --out or --restart")
        moved = annotation.audio != audio
        annotation.audio = audio  # the file may have moved
        annotation.add_speakers(predictions)
        if moved:
            store.save(annotation)
    if annotation is None:
        annotation = Annotation.from_predictions(audio, duration, predictions)
        store.save(annotation)
    else:
        log.info("Continuing the stored annotation (--restart to start again with an empty one)")

    playback = audio
    if os.path.splitext(audio)[1].lower() not in PLAYABLE:
        playback = store.dir / "playback.wav"
        sf.write(playback, signal, SAMPLING_RATE, subtype="PCM_16")
    rate = config["view"]["waveform_rate"]
    app = create_app(
        annotation, store, predictions, playback, envelope(signal, SAMPLING_RATE, rate), rate, config["view"]["merge_gap"]
    )

    host = args.host or config["server"]["host"]
    port = args.port or config["server"]["port"]
    url = f"http://{'localhost' if host in ('0.0.0.0', '127.0.0.1') else host}:{port}"
    print(f"\n  Annotate {os.path.basename(audio)} at {url}\n  Ground truth in {store.dir}\n", flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
