Installation
============

Requirements:

* Python 3.12 or newer
* a browser, Chrome or Firefox
* for predictions: a Hugging Face account and `uv <https://docs.astral.sh/uv/>`_ (see below)

Clone the repository and install the package into a virtual environment:

.. code-block:: bash

    $ git clone https://github.com/felixbur/diarist.git
    $ cd diarist
    $ uv venv --python 3.12 .venv && source .venv/bin/activate
    $ uv pip install -e .

(or ``python -m venv .venv`` and ``pip install -e .``).

Predictions with pyannote
-------------------------

Diarist can show the speakers predicted by a
`pyannote <https://github.com/pyannote/pyannote-audio>`_ speaker diarization pipeline
as reference while labelling. Without a Hugging Face token it starts without predictions
and the ground truth is labelled from scratch.

The pyannote pipelines are gated on Hugging Face:

1. Log in on `huggingface.co <https://huggingface.co>`_ and accept the conditions of
   `pyannote/speaker-diarization-community-1 <https://huggingface.co/pyannote/speaker-diarization-community-1>`_,
   or of the pipeline set in ``prediction.model`` (see :doc:`configuration`).
2. Create an access token: Settings > Access Tokens, read access.
3. Give the token to diarist, in this order of precedence: in a configuration file
   used with ``--config``

   .. code-block:: yaml

       # my.local.yaml (*.local.yaml is ignored by git)
       prediction:
         hf_token: hf_...

   as environment variable

   .. code-block:: bash

       $ export HF_TOKEN=hf_...      # e.g. in ~/.bashrc

   or stored by the Hugging Face command line tool
   (in ``~/.cache/huggingface/token``, or where ``HF_TOKEN_PATH`` or ``HF_HOME`` point to):

   .. code-block:: bash

       $ uvx --from huggingface_hub hf auth login

   Keep a file with a token private (``chmod 600 my.local.yaml``), never commit it.

pyannote needs torch, so it runs as a script in its own environment,
separate from diarist's (``diarist/model/pyannote_run.py``):
by default ``uv run --script``, which creates the environment from the script's
dependencies on first use (torch, several GB). Alternatively, give the Python
of an existing environment with ``pyannote.audio`` 4:

.. code-block:: yaml

    prediction:
      command: [/path/to/venv/bin/python]

The token reaches the script in the ``HF_TOKEN`` variable of its environment,
not on the command line. pyannote uses the GPU if there is one, else the CPU
(``prediction.device``); the pipeline is downloaded into the Hugging Face cache on first use.
