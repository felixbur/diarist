Development
===========

Tests
-----

.. code-block:: bash

    $ python -m pytest

The tests replace pyannote with a stand-in script,
so they need neither a Hugging Face token nor torch.

To work on the view, any audio file without predictions will do:

.. code-block:: bash

    $ diarist speech.wav --no-predictions --out /tmp/annotation

Screenshot
----------

.. code-block:: bash

    $ diarist examples/ami_ES2004a_excerpt.flac --no-browser --port 8012 &
    $ google-chrome --headless=new --hide-scrollbars --window-size=1500,820 \
      --virtual-time-budget=4000 --screenshot=docs/pictures/screenshot.png http://localhost:8012/

Documentation
-------------

.. code-block:: bash

    $ uv pip install -e ".[docs]"
    $ python -m sphinx -W docs/ build/html

and open ``build/html/index.html``.

Versions
--------

Every change set gets a version (semantic versioning):

1. bump ``version`` in ``pyproject.toml``
   (patch: fixes and docs, minor: features)
2. add a section to ``CHANGELOG.md``
3. commit, tag ``vX.Y.Z`` (annotated), push branch and tag
