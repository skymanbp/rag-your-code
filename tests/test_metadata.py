import json
import tomllib
from pathlib import Path

import ragyourcode


ROOT = Path(__file__).resolve().parents[1]


def test_project_and_plugin_versions_match():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    plugin = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert project["project"]["version"] == ragyourcode.__version__ == plugin["version"]
