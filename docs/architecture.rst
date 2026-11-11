Architecture
============

The application follows the model-view-controller pattern:

.. code-block:: text

     Browser                                   Python server
    ┌──────────────────┐  GET /api/session    ┌──────────────────────────────────────┐
    │ VIEW             │◄─────────────────────│ CONTROLLER                           │
    │ timeline canvas  │  GET /api/waveform   │ annotation data model, storage,      │
    │ speakers, undo   │◄─────────────────────│ exports (CSV, RTTM, TextGrid),       │
    │                  │  GET /audio          │ waveform envelope                    │
    │                  │◄─────────────────────│                                      │
    │                  │  PUT /api/annotation │                                      │
    │                  │─────────────────────►│                                      │
    └──────────────────┘                      │ MODEL                                │
                                              │ prediction: pyannote, in its own     │
                                              │ environment (subprocess)             │
                                              └──────────────────────────────────────┘

Model
    :func:`diarist.model.predict.predict` runs a pyannote speaker diarization pipeline
    on the whole file (:mod:`diarist.model.pyannote_run`, in its own environment with torch,
    so diarist itself needs neither) and returns the predicted segments, cached per file and settings.
    :func:`~diarist.model.predict.hf_token` finds the Hugging Face token; without one,
    there are no predictions.

Controller
    :class:`diarist.controller.annotation.Annotation` (speakers and segments,
    validated), :class:`~diarist.controller.annotation.Store` (the files of an
    annotation folder), :mod:`diarist.controller.evaluation` (DER with :mod:`audmetric`)
    and :mod:`diarist.controller.audio` (signal, waveform envelope).

View
    Static HTML/JavaScript in ``diarist/view``, served by :mod:`diarist.server`.
    The view holds the annotation while it is edited (with undo / redo)
    and sends the complete annotation after every change.

Server API
----------

``GET /api/session``
    file name, duration, waveform rate, predictions and the current annotation
    (:class:`diarist.server.Session`)
``GET /api/waveform``
    min / max envelope as int8 bytes, interleaved ``min0, max0, min1, ...``,
    ``view.waveform_rate`` pairs per second, scaled to the loudest sample
``GET /audio``
    the audio file, with HTTP range requests for seeking
``GET /api/score``
    DER of the predictions on the labelled part of the current annotation,
    or ``null`` without ground truth or predictions; requested by the view after each save,
    as it takes a few seconds for an hour of audio
``PUT /api/annotation``
    a complete :class:`~diarist.controller.annotation.Annotation`;
    validated (422 for unknown speakers or invalid segments,
    409 for another audio file), stored and exported
