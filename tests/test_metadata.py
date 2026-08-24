import json
import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    # `tomllib` arrived in 3.11. Nothing in src/ needs 3.11, so the declared
    # floor stays at 3.10 and this one test takes the backport instead; the
    # `dev` extra in pyproject.toml supplies it below 3.11.
    import tomli as tomllib

import ragyourcode


ROOT = Path(__file__).resolve().parents[1]


def test_project_and_plugin_versions_match():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    plugin = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert project["project"]["version"] == ragyourcode.__version__ == plugin["version"]
