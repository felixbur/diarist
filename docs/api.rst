API
===

Model
-----

.. automodule:: diarist.model.predict
    :members: hf_token, hf_token_path, settings, predict

Controller
----------

.. automodule:: diarist.controller.annotation
    :members: Speaker, Turn, Annotation, Store, write_rttm, write_textgrid

.. automodule:: diarist.controller.evaluation
    :members: evaluate, read_labels, read_turns, to_labels, score_annotation, load_ground_truth, find_audio, file_id

.. automodule:: diarist.controller.audio
    :members:

Server and configuration
------------------------

.. automodule:: diarist.server
    :members: Session, create_app

.. automodule:: diarist.config
    :members:
