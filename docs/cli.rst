Command line
============

All tools print this help with ``-h``.
Settings that are not on the command line are in the configuration
(``--config``, see :doc:`configuration`).

diarist
-------

Predicts the speakers of an audio file (with a Hugging Face token)
and opens the view to label the ground truth, see :doc:`usage`.

.. code-block:: bash

    $ diarist speech.wav
    $ diarist speech.wav --speakers 2 --config my.yaml
    $ diarist speech.wav --host 0.0.0.0 --port 8080 --no-browser   # on a server, view from another machine

.. literalinclude:: _generated/diarist.txt
    :language: text

diarist-der
-----------

Diarization error rate of predicted speakers against a ground truth,
optionally with pyannote for comparison, see :doc:`evaluation`.

.. code-block:: bash

    $ diarist-der annotations/speech
    $ diarist-der ground_truth.rttm predictions.rttm
    $ diarist-der truth.csv my_system.csv --pyannote --audio-root /data/audio

.. literalinclude:: _generated/diarist-der.txt
    :language: text
