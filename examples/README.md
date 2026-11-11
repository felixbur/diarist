# Example

A one-minute excerpt of a meeting with four speakers, with a reference speaker annotation:

```bash
diarist examples/ami_ES2004a_excerpt.flac                         # label it (predictions with a Hugging Face token)
diarist-der examples/ami_ES2004a_excerpt.rttm --pyannote          # DER of pyannote against the reference
diarist-der examples/ami_ES2004a_excerpt.rttm annotations/ami_ES2004a_excerpt/ground_truth.rttm   # ... or of your labels
```

## Files

`ami_ES2004a_excerpt.flac`
: 60 s of meeting ES2004a of the [AMI Meeting Corpus](https://groups.inf.ed.ac.uk/ami/corpus/), headset mix
  (`ES2004a.Mix-Headset.wav`), from 11:25 to 12:25 (685 s to 745 s), 16 kHz mono.

`ami_ES2004a_excerpt.rttm`
: who speaks when in the excerpt, speakers by their AMI participant ids. From the `only_words` reference of
  [BUT's AMI diarization setup](https://github.com/BUTSpeechFIT/AMI-diarization-setup) (`rttms/test/ES2004a.rttm`),
  which is derived from the AMI manual annotations 1.6.2.

## License and changes

The AMI Meeting Corpus is licensed under the
[Creative Commons Attribution 4.0 International License (CC BY 4.0)](https://creativecommons.org/licenses/by/4.0/),
copyright the AMI Consortium. The files here are modified: the audio was cut to the excerpt and converted to FLAC;
the annotation was clipped to the excerpt, its times shifted to start at 0 and its file id renamed.
They are licensed under CC BY 4.0 as well.

Carletta, J. et al. (2005). The AMI Meeting Corpus: A Pre-announcement.
In: Machine Learning for Multimodal Interaction (MLMI 2005), LNCS 3869, Springer.
