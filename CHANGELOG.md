# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
versions follow [Semantic Versioning](https://semver.org/) and every version is a git tag.

## [1.0.0] - 2026-11-11

First open-source release.

### Added
- `diarist`: label speaker diarization ground truth in the browser on a zoomable timeline
  (waveform, predicted speakers, editable ground truth with overlapping speech, undo / redo),
  saved as audformat CSV, RTTM and Praat TextGrid on every change.
- Speaker predictions as reference with a pyannote speaker diarization pipeline
  (default `pyannote/speaker-diarization-community-1`), if a Hugging Face token is given in
  `prediction.hf_token` of the configuration, in `HF_TOKEN` or stored by `hf auth login`; without one, diarist starts without predictions.
  pyannote runs in its own environment (`uv run --script`), results are cached per file and settings.
- `--speakers`, `prediction.num_speakers` / `min_speakers` / `max_speakers`: expected number of speakers.
- `--no-predictions`: annotate without predictions.
- `diarist` stops at the start if its port is in use, naming the file another diarist there shows,
  instead of opening the browser on that other server.
- `diarist-der`: diarization error rate of predictions against a ground truth (RTTM, audformat CSV or
  annotation folder) with audmetric; `--pyannote` adds pyannote for comparison.
- Example: one minute of the AMI Meeting Corpus (CC BY 4.0) with four speakers and a reference annotation,
  in `examples/`.
