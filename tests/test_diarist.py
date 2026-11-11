"""Tests of the annotation storage, the server, the evaluation and the predictions."""

import pathlib
import sys

import audformat
import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from diarist.config import load_config
from diarist.controller.annotation import Annotation, Speaker, Store, Turn
from diarist.controller.audio import envelope
from diarist.server import create_app

PREDICTIONS = [
    Turn(start=0.0, end=3.0, speaker="S1"),
    Turn(start=3.0, end=5.0, speaker="S1"),
    Turn(start=6.0, end=8.0, speaker="S2"),
    Turn(start=9.0, end=10.0, speaker="S1"),
]


def annotation(audio="/data/a.wav"):
    a = Annotation.from_predictions(audio, 12.0, PREDICTIONS)
    a.segments = [Turn(start=0, end=5, speaker="S1"), Turn(start=6, end=8, speaker="S2"), Turn(start=9, end=10, speaker="S1")]
    return a


def test_from_predictions_is_empty_with_predicted_speakers():
    a = Annotation.from_predictions("a.wav", 12.0, PREDICTIONS)
    assert [s.id for s in a.speakers] == ["S1", "S2"]
    assert a.segments == []


def test_add_speakers():
    a = Annotation.from_predictions("a.wav", 12.0, PREDICTIONS)
    a.speakers[0].name = "Alice"
    a.add_speakers([*PREDICTIONS, Turn(start=11, end=12, speaker="S7")])
    assert [(s.id, s.name) for s in a.speakers] == [("S1", "Alice"), ("S2", "S2"), ("S7", "S7")]


def test_validation():
    with pytest.raises(ValueError, match="unknown speaker"):
        Annotation(audio="a.wav", duration=1, speakers=[], segments=[Turn(start=0, end=1, speaker="X")])
    with pytest.raises(ValueError, match="invalid segment"):
        Annotation(
            audio="a.wav", duration=1, speakers=[Speaker(id="X", name="x")], segments=[Turn(start=1, end=1, speaker="X")]
        )


def test_store_roundtrip_and_exports(tmp_path):
    store = Store(tmp_path)
    assert store.load_prediction_settings() is None
    store.save_predictions("/data/a.wav", PREDICTIONS, {"model": "pyannote/x", "num_speakers": 2})
    assert store.load_predictions() == PREDICTIONS
    assert store.load_prediction_settings() == {"model": "pyannote/x", "num_speakers": 2}
    a = annotation()
    a.speakers[0].name = "Alice Smith"
    a.segments.append(Turn(start=7.0, end=9.5, speaker="S1"))  # overlaps S2
    store.save(a)
    assert store.load_annotation() == Annotation.model_validate(a.model_dump())

    df = audformat.utils.read_csv(tmp_path / "ground_truth.csv", as_dataframe=True)
    assert list(df["speaker"]) == ["Alice Smith", "S2", "Alice Smith", "Alice Smith"]
    rttm = (tmp_path / "ground_truth.rttm").read_text().splitlines()
    assert rttm[0] == "SPEAKER a 1 0.000 5.000 <NA> <NA> Alice_Smith <NA> <NA>"
    textgrid = (tmp_path / "ground_truth.TextGrid").read_text()
    assert "size = 2" in textgrid and 'name = "Alice Smith"' in textgrid


def test_envelope():
    signal = np.concatenate([np.full(80, 0.5), np.full(80, -0.25)]).astype(np.float32)
    assert envelope(signal, 16000, 200).tolist() == [127, 127, -64, -64]


def test_server(tmp_path):
    audio = tmp_path / "a.wav"
    sf.write(audio, np.zeros(16000, dtype=np.float32), 16000)
    a = annotation(str(audio))
    store = Store(tmp_path / "out")
    client = TestClient(create_app(a, store, PREDICTIONS, audio, np.zeros(400, dtype=np.int8), 200))

    assert "Diarist" in client.get("/").text
    session = client.get("/api/session").json()
    assert session["name"] == "a.wav" and len(session["predictions"]) == 4
    assert client.get("/api/score").json()["der"] == pytest.approx(0)
    assert len(client.get("/api/waveform").content) == 400
    assert client.get("/audio").status_code == 200

    new = a.model_dump()
    new["speakers"].append({"id": "N1", "name": "Bob"})
    new["segments"][2]["speaker"] = "N1"  # predicted as S1, which maps to S1: confusion
    response = client.put("/api/annotation", json=new)
    assert response.status_code == 200
    assert client.get("/api/score").json()["confusion"] > 0
    assert store.load_annotation().segments[2].speaker == "N1"
    assert client.get("/api/session").json()["annotation"]["speakers"][-1]["name"] == "Bob"

    new["segments"][1]["speaker"] = "nobody"
    assert client.put("/api/annotation", json=new).status_code == 422
    assert client.put("/api/annotation", json={**a.model_dump(), "audio": "other.wav"}).status_code == 409


def test_der_files(tmp_path):
    from diarist.controller.evaluation import evaluate, read_labels

    a = annotation()
    store = Store(tmp_path)
    store.save(a)
    store.save_predictions("/data/a.wav", PREDICTIONS, {})
    truth = read_labels(tmp_path / "ground_truth.csv")
    assert truth.equals(read_labels(tmp_path / "ground_truth.rttm"))  # same file ids and labels

    perfect = evaluate(truth, truth)
    assert perfect.loc["a", "der"] == 0 and perfect.loc["a", "speech"] == pytest.approx(8.0)
    # predictions: 0-5 S1, 6-8 S2, 9-10 S1 as in the truth, labels differ but map one-to-one
    assert evaluate(truth, read_labels(tmp_path / "predictions.csv")).loc["a", "der"] == pytest.approx(0)


def test_der_components():
    from diarist.controller.evaluation import evaluate, to_labels

    truth = to_labels([Turn(start=0, end=4, speaker="A"), Turn(start=4, end=8, speaker="B")])
    prediction = to_labels([Turn(start=0, end=6, speaker="x"), Turn(start=6, end=7, speaker="y")])
    r = evaluate(truth, prediction).loc["audio"]
    # x -> A, y -> B: 4-6 confused, 7-8 missed
    assert (r.confusion, r.false_alarm, r.missed) == pytest.approx((2 / 8, 0, 1 / 8))
    assert r.der == pytest.approx(3 / 8)
    assert evaluate(truth, to_labels([])).loc["audio", "der"] == 1


def test_score_annotation_only_labelled_part():
    from diarist.controller.evaluation import score_annotation

    a = Annotation.from_predictions("a.wav", 12.0, PREDICTIONS)
    assert score_annotation(a, PREDICTIONS) is None
    a.segments = [Turn(start=0, end=5, speaker="S2")]  # predictions after 5 s are not scored
    score = score_annotation(a, PREDICTIONS)
    assert score["until"] == 5 and score["der"] == pytest.approx(0)
    assert score_annotation(a, []) is None  # no predictions, nothing to score


def test_load_ground_truth(tmp_path, monkeypatch):
    from diarist.controller.evaluation import load_ground_truth

    audio = tmp_path / "audio"
    audio.mkdir()
    sf.write(audio / "a.wav", np.zeros(16000 * 12, dtype=np.float32), 16000)
    folder = tmp_path / "annotations" / "a"
    store = Store(folder)
    store.save(annotation(audio="/laptop/a.wav"))  # path of another machine
    monkeypatch.chdir(audio)  # the current folder is searched last

    assert load_ground_truth([str(folder)])[0].audio == str(audio / "a.wav")
    (folder / "annotation.json").unlink()  # ground_truth.csv only
    csv_only = load_ground_truth([str(folder)])[0]
    assert (csv_only.duration, len(csv_only.segments)) == (12.0, 3)
    monkeypatch.chdir(tmp_path)
    rttm = load_ground_truth([str(folder / "ground_truth.rttm")], audio_root=str(audio))[0]
    assert rttm.audio == str(audio / "a.wav") and [s.name for s in rttm.speakers] == ["S1", "S2"]
    with pytest.raises(ValueError, match="not found"):
        load_ground_truth([str(folder / "ground_truth.rttm")])


def test_find_annotation_next_to_audio(tmp_path):
    from diarist.__main__ import find_annotation

    for audio, folder in [
        (tmp_path / "a" / "a.wav", tmp_path / "a"),  # data/<name>/<name>.wav
        (tmp_path / "b.wav", tmp_path / "b"),  # data/<name>.wav beside data/<name>/
    ]:
        audio.parent.mkdir(exist_ok=True)
        sf.write(audio, np.zeros(16000, dtype=np.float32), 16000)
        assert find_annotation(str(audio)) is None
        Store(folder).save(Annotation.from_predictions(f"/elsewhere/{audio.name}", 1.0, PREDICTIONS))
        assert find_annotation(str(audio)) == folder
    other = tmp_path / "a" / "c.wav"  # an annotation of another recording does not count
    sf.write(other, np.zeros(16000, dtype=np.float32), 16000)
    assert find_annotation(str(other)) is None


# stands in for pyannote_run.py: arguments are the script, audio, rttm, --model ..., --device ..., [--num-speakers ...];
# records its arguments and HF_TOKEN in a file
FAKE_PYANNOTE = (
    "import os, sys; open(sys.argv[3], 'w').write("
    "'SPEAKER a 1 2.000 1.000 <NA> <NA> SPEAKER_00 <NA> <NA>\\n'"
    "'SPEAKER a 1 0.100 0.500 <NA> <NA> SPEAKER_01 <NA> <NA>\\n');"
    "open({calls!r}, 'a').write(' '.join(sys.argv[4:]) + ' token=' + os.environ['HF_TOKEN'] + '\\n')"
)


def prediction_config(tmp_path, **settings):
    calls = tmp_path / "calls"
    command = [sys.executable, "-c", FAKE_PYANNOTE.format(calls=str(calls))]
    config = {**load_config()["prediction"], "command": command, "cache": str(tmp_path / "cache"), **settings}
    return config, calls


@pytest.fixture(autouse=True)
def no_hf_token(tmp_path, monkeypatch):
    """No Hugging Face token of the machine running the tests: neither HF_TOKEN nor a stored login."""
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.setenv("HF_TOKEN_PATH", str(tmp_path / "hf_login_token"))


def test_hf_token(tmp_path, monkeypatch):
    from diarist.model.predict import hf_token, hf_token_path, settings

    config = load_config()["prediction"]
    assert hf_token(config) is None
    (tmp_path / "hf_login_token").write_text("hf_login\n")  # hf auth login
    assert hf_token(config) == "hf_login"
    monkeypatch.setenv("HF_TOKEN", "hf_env")
    assert hf_token(config) == "hf_env"  # before the login
    assert hf_token({**config, "hf_token": " hf_config "}) == "hf_config"  # the configuration first
    assert "hf_token" not in settings({**config, "hf_token": "hf_config"})  # never stored

    monkeypatch.delenv("HF_TOKEN_PATH")
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
    assert hf_token_path() == tmp_path / "hf" / "token"
    monkeypatch.delenv("HF_HOME")
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    assert hf_token_path() == pathlib.Path.home() / ".cache" / "huggingface" / "token"


def test_predict_runs_once_with_token_and_renames_speakers(tmp_path):
    from diarist.model.predict import predict

    audio = tmp_path / "a.wav"
    sf.write(audio, np.zeros(16000 * 4, dtype=np.float32), 16000)
    config, calls = prediction_config(tmp_path, num_speakers=2)
    for _ in range(2):
        assert predict(str(audio), config, "hf_secret") == [
            Turn(start=0.1, end=0.6, speaker="S1"),  # in order of appearance
            Turn(start=2.0, end=3.0, speaker="S2"),
        ]
    call = calls.read_text().splitlines()
    assert len(call) == 1  # cached the second time
    assert "--num-speakers 2" in call[0] and "hf_secret" not in call[0].split(" token=")[0]
    assert call[0].endswith("token=hf_secret")  # in the environment, not on the command line
    predict(str(audio), {**config, "num_speakers": 3}, "hf_secret")
    assert len(calls.read_text().splitlines()) == 2  # other settings, predicted again


def test_predict_failure(tmp_path):
    from diarist.model.predict import predict

    audio = tmp_path / "a.wav"
    sf.write(audio, np.zeros(16000, dtype=np.float32), 16000)
    config, _ = prediction_config(tmp_path, command=[sys.executable, "-c", "raise SystemExit(1)"])
    with pytest.raises(RuntimeError, match="pyannote failed"):
        predict(str(audio), config, "hf_x")
    with pytest.raises(RuntimeError, match="cannot run"):
        predict(str(audio), {**config, "command": [str(tmp_path / "missing")]}, "hf_x")


def test_load_predictions_with_and_without_token(tmp_path, monkeypatch):
    from diarist.__main__ import load_predictions

    audio = tmp_path / "a.wav"
    sf.write(audio, np.zeros(16000 * 4, dtype=np.float32), 16000)
    store = Store(tmp_path / "out")
    config, calls = prediction_config(tmp_path)

    assert load_predictions(store, str(audio), config) == []  # no token: no predictions ...
    assert store.load_predictions() is None  # ... and none stored, so a token later predicts
    assert not calls.exists()

    monkeypatch.setenv("HF_TOKEN", "hf_env")
    assert len(load_predictions(store, str(audio), config)) == 2
    assert store.load_prediction_settings()["model"] == config["model"]
    assert "hf_env" not in (store.dir / "predictions.yaml").read_text()
    assert len(load_predictions(store, str(audio), config)) == 2
    assert len(calls.read_text().splitlines()) == 1  # stored predictions reused

    monkeypatch.delenv("HF_TOKEN")
    other = {**config, "num_speakers": 5}
    assert len(load_predictions(store, str(audio), other)) == 2  # other settings, no token: the stored ones
    assert len(calls.read_text().splitlines()) == 1
