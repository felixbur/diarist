import os
import sys
import tomllib
from datetime import date

sys.path.insert(0, os.path.abspath(".."))

with open(os.path.join("..", "pyproject.toml"), "rb") as fp:
    config = tomllib.load(fp)


# Project -----------------------------------------------------------------
project = config["project"]["name"]
copyright = f"2026-{date.today().year} Felix Burkhardt"
author = "Felix Burkhardt"
version = config["project"]["version"]
release = version
title = "Diarist Documentation"


# General -----------------------------------------------------------------
master_doc = "index"
source_suffix = {".rst": "restructuredtext"}
exclude_patterns = ["build", "Thumbs.db", ".DS_Store"]
pygments_style = None
extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",  # Google-style docstrings
    "sphinx.ext.viewcode",
    "sphinx.ext.intersphinx",
    "sphinx_copybutton",
    "myst_parser",  # CHANGELOG.md
]
intersphinx_mapping = {
    "numpy": ("https://numpy.org/doc/stable/", None),
    "python": ("https://docs.python.org/3/", None),
}
# FastAPI fails to build its pydantic models when first imported
# while the mocks are active (in diarist.server), so import it before.
import fastapi  # noqa: E402, F401

autodoc_mock_imports = [
    "audresample",
    "uvicorn",
]

# Help of the command line tools for cli.rst, from their argument parsers.
os.environ["COLUMNS"] = "80"  # line width of argparse, fits the page
os.makedirs("_generated", exist_ok=True)
from sphinx.ext.autodoc.mock import mock  # noqa: E402

with mock(autodoc_mock_imports):
    import diarist.__main__
    import diarist.controller.evaluation

    for module in (diarist.__main__, diarist.controller.evaluation):
        parser = module.build_parser()
        with open(os.path.join("_generated", f"{parser.prog}.txt"), "w") as fp:
            fp.write(parser.format_help())
autodoc_member_order = "bysource"
autodoc_typehints = "description"
copybutton_prompt_text = r"\$ "
copybutton_prompt_is_regexp = True
linkcheck_ignore = ["http://localhost"]


# HTML --------------------------------------------------------------------
html_theme = "furo"
html_title = f"{title} {version}"
