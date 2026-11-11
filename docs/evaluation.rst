Evaluation
==========

``diarist-der`` computes the diarization error rate (DER) of predicted
speakers against a ground truth with :func:`audmetric.diarization_error_rate_detailed`:

.. math::

    \text{DER} = \frac{\text{confusion} + \text{false alarm} + \text{missed speech}}
        {\text{ground-truth speech}}

Predicted speakers are mapped one-to-one to the ground-truth speakers
(greedy, per file), so their labels need not match.

.. code-block:: bash

    $ diarist-der annotations/speech                  # predictions against ground truth of an annotation folder
    $ diarist-der ground_truth.rttm predictions.rttm  # any RTTM or audformat CSV files
    $ diarist-der truth.csv other.csv --column label  # another speaker column in CSV files

::

    file      DER  confusion  false al.   missed    speech
    speech  13.2%      13.2%       0.0%     0.0%      7.9s

Files are matched by name without folder and extension, as in RTTM,
so RTTM and CSV files can be compared. With several files, a ``total`` row
follows; files without prediction count as missed speech.

Comparison with pyannote
------------------------

``--pyannote`` also scores the pyannote pipeline of ``prediction.model``
on the files of the ground truth, e.g. to compare your own system with it:

.. code-block:: bash

    $ diarist-der truth.csv my_system.rttm --pyannote --audio-root /data/audio
    $ diarist-der annotations/speech/ground_truth.csv --pyannote   # pyannote only

On the example of the repository, with its reference annotation::

    $ diarist-der examples/ami_ES2004a_excerpt.rttm --pyannote
    file                 system                               DER  confusion  false al.   missed    speech
    ami_ES2004a_excerpt  speaker-diarization-community-1    19.3%       8.5%       1.7%     9.1%     68.9s

(pyannote finds two of the four speakers, on the CPU in about 40 s.)

It needs a Hugging Face token, as the predictions of ``diarist`` (see :doc:`installation`),
and the settings of the ``prediction`` section of the configuration (``--config``).
The audio files are looked for in ``--audio-root``, next to the ground truth, one folder up
and in the current folder. Results are cached per audio file and settings,
shared with ``diarist``, so pyannote runs only once per file.

In Python:

.. code-block:: python

    from diarist.controller.evaluation import evaluate, read_labels

    results = evaluate(read_labels("ground_truth.csv"), read_labels("predictions.rttm"))
