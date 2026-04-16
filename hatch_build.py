"""Hatch build hook: bake the git commit count into the wheel.

The relay's runtime version is meant to bump on every commit, but a wheel
install doesn't ship `.git`, so a runtime `git rev-list` from inside the
package always fails and the hardcoded fallback "wins". Solving it from the
source side instead: at build time (where `.git` is still present in the
checkout uvx clones) we compute the commit count and write it to
`branch_monkey_mcp/_version.py`. The runtime imports that file first and
only falls back to the runtime git lookup when the file is absent (e.g. a
pip install -e from a working tree without going through the build).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class VersionWriter(BuildHookInterface):
    PLUGIN_NAME = "version-writer"

    def initialize(self, version, build_data):
        root = Path(self.root)
        try:
            result = subprocess.run(
                ["git", "rev-list", "--count", "HEAD"],
                cwd=str(root),
                capture_output=True,
                text=True,
                check=True,
                timeout=5,
            )
            count = result.stdout.strip() or "0"
        except Exception:
            count = "0"

        out_path = root / "branch_monkey_mcp" / "_version.py"
        out_path.write_text(
            "# Auto-generated at build time by hatch_build.VersionWriter — do not edit.\n"
            f'COMMIT_COUNT = "{count}"\n'
        )
