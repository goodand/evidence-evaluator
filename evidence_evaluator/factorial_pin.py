"""Git-tracked trust root for the frozen factorial experiment.

This module is intentionally outside ``harness_surface()``. Including the pin
in the content it authenticates would create a self-referential digest. Git
history protects changes to this value; the editable private receipt does not.
"""

from pathlib import Path
import subprocess

TRUSTED_FACTORIAL_FREEZE_DIGEST = (
    "dab2ebf9cbee88daad8578fa789bce49d998f0611c92f6f1e5d96fba25b8d9fa"
)

# Set this to the screen receipt digest and commit it after the 16-cell screen.
# Until then, confirm and public score verification are intentionally blocked.
TRUSTED_SCREEN_RECEIPT_DIGEST: str | None = None


def assert_trusted_pin_provenance(repo_root: Path) -> None:
    """Require the working pin bytes to match the current Git commit."""
    relative = "evidence_evaluator/factorial_pin.py"
    try:
        committed = subprocess.run(
            ["git", "-C", str(repo_root), "show", f"HEAD:{relative}"],
            check=False, capture_output=True,
        )
    except OSError as exc:
        raise ValueError("trusted freeze pin cannot be verified without Git") from exc
    current = (repo_root / relative).read_bytes()
    if committed.returncode != 0:
        raise ValueError("trusted freeze pin is not committed in this Git worktree")
    if committed.stdout != current:
        raise ValueError("trusted freeze pin differs from the current Git commit")
