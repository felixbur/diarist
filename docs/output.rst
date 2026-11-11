Output
======

Each audio file gets an annotation folder, by default
``annotations/<audio name>/``:

``predictions.csv``
    the predicted segments, audformat table with a segmented index
    (``file, start, end``) and a ``speaker`` column (``S1``, ``S2``, ...);
    reused on the next start if the prediction settings are the same;
    only written if there are predictions
``predictions.yaml``
    the settings the predictions were made with (pyannote pipeline and number of speakers,
    never the token); when they differ on the next start, the speakers are predicted again
``annotation.json``
    the annotation as edited: audio path, duration, speakers with ids and names,
    segments referring to speaker ids; loaded again on the next start
``ground_truth.csv``
    the ground truth as audformat table, speaker names in the ``speaker`` column
``ground_truth.rttm``
    the ground truth in RTTM, e.g. for ``pyannote.metrics`` or ``dscore``;
    spaces in file and speaker names are replaced by ``_``
``ground_truth.TextGrid``
    Praat TextGrid with one interval tier per speaker, so overlapping speech is kept
``playback.wav``
    only for audio formats browsers cannot play

The ground-truth files are rewritten on every save.
Read the table with:

.. code-block:: python

    import audformat

    df = audformat.utils.read_csv("annotations/speech/ground_truth.csv")
