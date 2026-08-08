"""evidence-evaluator: does a zero-context agent find and correctly cite the
right sources, in a corpus you provide, driven by a CLI agent you provide.

Modules load with plain `sys.path`-relative imports (`from contract import
...`), not package-relative ones, because `evaluator.py` re-executes itself
as a subprocess with `python3 -I` (isolated mode) to verify its own source has
not been patched before scoring anything -- see `evaluator.py`'s module
docstring. That subprocess needs to find `contract.py` sitting next to it on
disk, which package-relative imports would not survive.

Import the submodules directly:

    import sys
    sys.path.insert(0, "/path/to/evidence_evaluator")
    import contract, evaluator, runner, providers

or run `evaluator.py` as a script for the CLI (`--payload`, `--emit-pins`).
See README.md for the full API and how to point this at your own corpus.
"""

__version__ = "0.1.0"
