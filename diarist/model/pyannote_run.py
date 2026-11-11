# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "pyannote.audio==4.0.1",
#     "torch==2.9.1",
#     "torchaudio==2.9.1",
#     "torchcodec==0.8.*",
#     "onnxruntime",  # speaker embeddings of pyannote/speaker-diarization-3.0
# ]
# ///
# torch from PyPI: on Linux built with CUDA, so it uses a GPU if there is one, else the CPU
"""Speaker diarization of one audio file with a pyannote pipeline, as RTTM.

Runs in its own environment (torch), separate from diarist's,
see :mod:`diarist.model.predict`::

    HF_TOKEN=hf_... uv run --script pyannote_run.py speech.wav speech.rttm

The Hugging Face token for the (gated) pipelines comes from ``HF_TOKEN``.
"""

import argparse
import os
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("audio")
    parser.add_argument("rttm", help="output file")
    parser.add_argument("--model", default="pyannote/speaker-diarization-community-1")
    parser.add_argument("--device", default="auto", help="auto (cuda if available, else cpu), cuda or cpu")
    parser.add_argument("--num-speakers", type=int, help="fixed number of speakers")
    parser.add_argument("--min-speakers", type=int, help="at least this many speakers")
    parser.add_argument("--max-speakers", type=int, help="at most this many speakers")
    args = parser.parse_args()

    print(f"Loading {args.model} ...", flush=True)
    import torch
    from pyannote.audio import Pipeline
    from pyannote.audio.core.task import Problem, Resolution, Specifications
    from pyannote.audio.pipelines.utils.hook import ProgressHook

    # the (trusted) pyannote 3.x checkpoints contain these classes, torch >= 2.6 loads only allowed ones
    torch.serialization.add_safe_globals([torch.torch_version.TorchVersion, Specifications, Problem, Resolution])
    hint = (
        f"the pipeline needs a Hugging Face token of an account that accepted the conditions of {args.model}"
        " on huggingface.co: prediction.hf_token in the configuration, export HF_TOKEN=hf_... or hf auth login"
    )
    try:
        pipeline = Pipeline.from_pretrained(args.model, token=os.environ.get("HF_TOKEN"))
    except Exception as e:
        raise SystemExit(f"Could not load {args.model}: {e}\n{hint}")
    if pipeline is None:
        raise SystemExit(f"Could not load {args.model}: {hint}")
    device = args.device
    if device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"
    elif device == "cuda" and not torch.cuda.is_available():
        raise SystemExit("--device cuda, but torch finds no GPU (CPU-only torch or no driver?)")
    pipeline.to(torch.device(device))

    print(f"Diarizing {os.path.basename(args.audio)} on {device} ...", flush=True)
    t = time.time()
    with ProgressHook(transient=True) as hook:  # a progress bar per step (segmentation, embeddings, ...)
        speakers = {
            name: value
            for name, value in [
                ("num_speakers", args.num_speakers),
                ("min_speakers", args.min_speakers),
                ("max_speakers", args.max_speakers),
            ]
            if value
        }
        result = pipeline(args.audio, hook=hook, **speakers)
    annotation = getattr(result, "speaker_diarization", result)  # pyannote 4: DiarizeOutput
    file_id = os.path.splitext(os.path.basename(args.audio))[0].replace(" ", "_")
    tmp = args.rttm + ".tmp"
    with open(tmp, "w") as fp:
        for turn, _, speaker in annotation.itertracks(yield_label=True):
            fp.write(f"SPEAKER {file_id} 1 {turn.start:.3f} {turn.duration:.3f} <NA> <NA> {speaker} <NA> <NA>\n")
    os.replace(tmp, args.rttm)
    print(f"{args.model} on {device}: {len(annotation.labels())} speakers in {time.time() - t:.1f} s")


if __name__ == "__main__":
    main()
