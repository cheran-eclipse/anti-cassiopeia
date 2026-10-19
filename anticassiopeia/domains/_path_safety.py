"""
Shared path-containment check for domain adapters that read a caller-
supplied file path (ml_data.py's `dataset_path`, fpga_embedded.py's
`report_path`).

FOUND BUG (external security review, verified against the real code):
both adapters previously did `Path(ctx["dataset_path"]).open()` /
`Path(ctx["report_path"])` directly on fully caller-supplied input, with
no containment check at all — since `Claim.context` arrives verbatim
from a POST /verify body, this was an arbitrary local file read via the
public API (read any file the server process can read: `/etc/passwd`,
`.env`, application source, etc. — not just a "wrong CSV" bug).

FIX: every path is resolved (`Path.resolve()`, which normalizes `..`
segments AND follows symlinks to their real target — both named attack
vectors) and must land inside one of the adapter's configured allowed
base directories. A path that LOOKS like it's inside an allowed
directory by string prefix alone, but escapes via `../../` or via a
symlink whose target is elsewhere, is rejected — the containment check
runs on the fully-resolved real path, not the literal string.

FOUND BUG (follow-up security review): a path containing an embedded
null byte (e.g. `"evals/fixtures/x\x00/../../../etc/passwd"`) makes
`Path.resolve()` raise `ValueError` ("embedded null character"), not
`OSError` — only `OSError` was caught, so this crashed with a 500
instead of a clean rejection. `ValueError` is now caught too.
"""

from __future__ import annotations

from pathlib import Path


def is_path_within_allowed_dirs(path: Path, allowed_base_dirs: list[Path]) -> bool:
    try:
        resolved = path.resolve()
    except (OSError, ValueError):
        return False
    for base in allowed_base_dirs:
        try:
            resolved_base = base.resolve()
        except (OSError, ValueError):
            continue
        if resolved == resolved_base or resolved.is_relative_to(resolved_base):
            return True
    return False
