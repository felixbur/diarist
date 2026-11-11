Configuration
=============

The defaults are in ``diarist/default_config.yaml``;
``diarist --config my.yaml`` (and ``diarist-der --config my.yaml``) overrides any part of them,
e.g. another pyannote pipeline and the Hugging Face token::

    prediction:
      hf_token: hf_...                              # or HF_TOKEN, or the hf auth login token
      model: pyannote/speaker-diarization-3.1
      max_speakers: 4

``model``, ``num_speakers``, ``min_speakers`` and ``max_speakers`` are stored with
the predictions (``predictions.yaml``, see :doc:`output`); when they differ from those
of the stored predictions, the next start predicts again. The token is never stored there.

.. literalinclude:: ../diarist/default_config.yaml
    :language: yaml
