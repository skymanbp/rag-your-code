"""Contracts for the configuration layer.

The load-bearing test here is not any single behaviour but
``test_defaults_reproduce_the_constants_they_replaced``: the layer is only
safe if a repository with no configuration file behaves exactly as it did
before the layer existed.
"""

from __future__ import annotations

import json
import sys

import pytest

from ragyourcode import config as config_module
from ragyourcode.cli import main
from ragyourcode.config import BY_PATH, SETTINGS, ConfigError, defaults, from_text, parse_toml_subset
from ragyourcode.indexer import build_units, iter_source_files, read_index
from ragyourcode.parser import EXTENSIONS


def _repo(root):
    (root / "app").mkdir()
    (root / "vendor").mkdir()
    (root / "app" / "billing.py").write_text('def charge(amount):\n    """Charge a card."""\n    return amount\n', encoding="utf-8")
    (root / "vendor" / "lib.py").write_text("def vendored():\n    return 1\n", encoding="utf-8")
    return root


# --- the layer must not change anything on its own -------------------------


def test_defaults_reproduce_the_constants_they_replaced():
    """0.3.0's literals, restated here so a drifting default cannot pass quietly."""
    cfg = defaults()
    assert cfg["index.max_file_bytes"] == 5 * 1024 * 1024
    assert cfg["embedding.dimensions"] == 384
    assert cfg["search.vector_weight"] == 0.15
    assert cfg["search.limit"] == 8
    assert cfg["search.max_chars"] == 12000
    assert cfg["agent.max_open_bytes"] == 5 * 1024 * 1024
    assert cfg["agent.max_open_chars"] == 100_000
    assert set(cfg["index.ignore"]) == {
        ".git", ".hg", ".svn", ".venv", "venv", "node_modules", "dist", "build", "__pycache__", ".rag-your-code",
    }


def test_suffixes_cannot_drift_from_the_parser():
    """The walker and the parser must agree, by construction rather than by luck.

    They agreed by coincidence before 0.4.0. A suffix on only the walker's list
    is walked, read and parsed to nothing, and the run reports a clean index.
    """
    assert set(defaults()["index.suffixes"]) == set(EXTENSIONS)
    assert BY_PATH["index.suffixes"].members == frozenset(EXTENSIONS)


def test_an_absent_file_yields_defaults(tmp_path):
    assert config_module.load(tmp_path).values == defaults().values
    assert config_module.load(tmp_path).source is None


def test_the_generated_template_changes_nothing():
    """`config init` writes a file whose every line is commented out."""
    assert from_text(config_module.render_template()).values == defaults().values


# --- rejection, not silent tolerance ---------------------------------------


@pytest.mark.parametrize(
    "text,fragment",
    [
        ("[index]\nsufixes = ['.py']\n", "unknown setting index.sufixes"),
        ("[indexx]\nignore = []\n", "unknown section [indexx]"),
        ("[embedding]\ndimensions = 8\n", "at least 32"),
        ("[embedding]\ndimensions = 99999\n", "at most 4096"),
        ("[search]\nvector_weight = 2.0\n", "at most 1.0"),
        ("[index]\nmax_file_bytes = true\n", "must be an integer"),
        ("[index]\nignore = 'vendor'\n", "must be a list of strings"),
        ("[index]\nsuffixes = ['.vue']\n", "has no parser rules"),
        ("[search]\nvector_weight = 'high'\n", "must be a number"),
        # nan and inf are valid TOML floats and pass isinstance, so they are
        # rejected on their value rather than on their type.
        ("[search]\nvector_weight = nan\n", "must be finite"),
        ("[search]\nvector_weight = inf\n", "must be finite"),
    ],
)
def test_bad_configuration_is_refused_with_a_reason(text, fragment):
    with pytest.raises(ConfigError) as caught:
        from_text(text)
    assert fragment in str(caught.value)


def test_the_cli_names_the_file_when_the_configuration_is_bad(tmp_path, capsys):
    _repo(tmp_path)
    (tmp_path / "rag-your-code.toml").write_text("[index]\nsufixes = ['.py']\n", encoding="utf-8")
    assert main(["index", str(tmp_path)]) == 2
    assert "rag-your-code.toml" in capsys.readouterr().err


# --- the fingerprint separates "stale" from "a different corpus" ------------


def test_only_build_settings_enter_the_fingerprint():
    base = defaults().build_fingerprint
    assert from_text("[embedding]\ndimensions = 512\n").build_fingerprint != base
    assert from_text("[index]\nignore = ['x']\n").build_fingerprint != base
    assert from_text("[index]\nsuffixes = ['.py']\n").build_fingerprint != base
    assert from_text("[index]\nmax_file_bytes = 2048\n").build_fingerprint != base
    # Retrieval-time settings must not invalidate an index.
    assert from_text("[search]\nlimit = 20\n").build_fingerprint == base
    assert from_text("[search]\nvector_weight = 0.5\n").build_fingerprint == base
    assert from_text("[agent]\nmax_open_chars = 2000\n").build_fingerprint == base


def test_every_build_setting_is_covered_by_the_test_above():
    """Guard against a new affects_build setting arriving without a case."""
    assert {setting.path for setting in SETTINGS if setting.affects_build} == {
        "index.ignore", "index.suffixes", "index.max_file_bytes", "embedding.dimensions",
    }


def test_a_changed_build_setting_forces_a_full_rebuild(tmp_path, capsys):
    _repo(tmp_path)
    assert main(["index", str(tmp_path)]) == 0
    capsys.readouterr()
    assert main(["index", str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out)["incremental"] is True

    (tmp_path / "rag-your-code.toml").write_text("[embedding]\ndimensions = 256\n", encoding="utf-8")
    assert main(["index", str(tmp_path)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["rebuilt_for_inputs"] is True
    # Reporting reuse it did not perform was the defect this pairs with.
    assert report["incremental"] is False

    payload, units = read_index(tmp_path / ".rag-your-code" / "index.json")
    assert payload["dimensions"] == 256
    assert all(len(unit.vector) == 256 for unit in units)


def test_a_configuration_change_alone_makes_the_index_stale(tmp_path, capsys):
    _repo(tmp_path)
    assert main(["index", str(tmp_path)]) == 0
    capsys.readouterr()
    # No source file is touched, so nothing a file fingerprint tracks moves.
    (tmp_path / "rag-your-code.toml").write_text("[index]\nignore = ['vendor']\n", encoding="utf-8")
    assert main(["search", "charge", "--root", str(tmp_path), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["stale"] is True


# --- the settings reach the behaviour they name -----------------------------


def test_ignore_and_suffixes_reach_the_walker(tmp_path):
    _repo(tmp_path)
    assert {path.name for path in iter_source_files(tmp_path)} == {"billing.py", "lib.py"}
    cfg = from_text("[index]\nignore = ['vendor']\n")
    assert {path.name for path in iter_source_files(tmp_path, cfg)} == {"billing.py"}


def test_dimensions_reach_the_vectors(tmp_path):
    _repo(tmp_path)
    units = build_units(tmp_path, cfg=from_text("[embedding]\ndimensions = 64\n"))
    assert units and all(len(unit.vector) == 64 for unit in units)


def test_vector_weight_reaches_the_score(tmp_path):
    from ragyourcode.search import search

    _repo(tmp_path)
    units = build_units(tmp_path)
    zero = search(units, "charge a card", limit=1, vector_weight=0.0)
    heavy = search(units, "charge a card", limit=1, vector_weight=1.0)
    assert zero and heavy and zero[0].unit.id == heavy[0].unit.id
    assert heavy[0].score > zero[0].score


def test_max_file_bytes_reaches_the_walker(tmp_path):
    _repo(tmp_path)
    (tmp_path / "app" / "big.py").write_text("# padding\n" * 400, encoding="utf-8")
    small = from_text("[index]\nmax_file_bytes = 1024\n")
    assert "big.py" not in {path.name for path in iter_source_files(tmp_path, small)}
    assert "big.py" in {path.name for path in iter_source_files(tmp_path)}


# --- the subcommand ---------------------------------------------------------


def test_config_init_then_set_preserves_comments(tmp_path, capsys):
    path = tmp_path / "rag-your-code.toml"
    assert main(["config", "init", "--root", str(tmp_path)]) == 0
    capsys.readouterr()
    before = path.read_text(encoding="utf-8")
    comment_lines = [line for line in before.splitlines() if line.startswith("#")]

    assert main(["config", "set", "search.vector_weight", "0.4", "--root", str(tmp_path)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["value"] == 0.4 and report["rebuild_required"] is False

    after = path.read_text(encoding="utf-8")
    surviving = [line for line in after.splitlines() if line.startswith("#")]
    # Exactly one comment is consumed: the commented-out assignment becomes the
    # real one. Every explanatory line, including this setting's own, stays.
    assert surviving == [line for line in comment_lines if line != "# vector_weight = 0.15"]
    assert "# how much cosine similarity contributes beside lexical overlap" in surviving
    assert "vector_weight = 0.4" in after
    assert config_module.load(tmp_path)["search.vector_weight"] == 0.4
    # Nothing else was disturbed: every other setting still reads as default.
    reloaded = config_module.load(tmp_path).values
    assert {name: value for name, value in reloaded.items() if name != "search.vector_weight"} == {
        name: value for name, value in defaults().values.items() if name != "search.vector_weight"
    }


def test_config_set_creates_a_file_that_did_not_exist(tmp_path, capsys):
    assert main(["config", "set", "search.limit", "20", "--root", str(tmp_path)]) == 0
    capsys.readouterr()
    assert config_module.load(tmp_path)["search.limit"] == 20


def test_config_set_rejects_a_bad_value_without_writing(tmp_path, capsys):
    assert main(["config", "init", "--root", str(tmp_path)]) == 0
    capsys.readouterr()
    before = (tmp_path / "rag-your-code.toml").read_text(encoding="utf-8")
    assert main(["config", "set", "embedding.dimensions", "4", "--root", str(tmp_path)]) == 2
    assert (tmp_path / "rag-your-code.toml").read_text(encoding="utf-8") == before


def test_config_init_refuses_to_clobber(tmp_path, capsys):
    assert main(["config", "init", "--root", str(tmp_path)]) == 0
    (tmp_path / "rag-your-code.toml").write_text("[search]\nlimit = 3\n", encoding="utf-8")
    capsys.readouterr()
    assert main(["config", "init", "--root", str(tmp_path)]) == 2
    assert config_module.load(tmp_path)["search.limit"] == 3
    assert main(["config", "init", "--force", "--root", str(tmp_path)]) == 0


def test_config_list_reports_source_and_customisation(tmp_path, capsys):
    (tmp_path / "rag-your-code.toml").write_text("[search]\nlimit = 20\n", encoding="utf-8")
    assert main(["config", "list", "--root", str(tmp_path)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["source"].endswith("rag-your-code.toml")
    customised = {row["name"] for row in report["settings"] if row["customised"]}
    assert customised == {"search.limit"}
    assert len(report["settings"]) == len(SETTINGS)


def test_config_get_and_path(tmp_path, capsys):
    assert main(["config", "path", "--root", str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out)["exists"] is False
    assert main(["config", "get", "search.limit", "--root", str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out)["value"] == 8
    assert main(["config", "get", "search.limitt", "--root", str(tmp_path)]) == 2


# --- the 3.10 reader must not diverge from the real one ---------------------

TOML_CASES = [
    "[index]\nsuffixes = ['.py', '.ts']\n",
    '[index]\nmax_file_bytes = 1_048_576\n',
    "[search]\nvector_weight = 0.4  # trailing comment\nlimit = 20\n",
    '[index]\nignore = [\n  "vendor",\n  "third_party",\n]\n',
    '[index]\nignore = ["a#b", "c"]\n',
    "[embedding]\ndimensions = 0x100\n",
    "[search]\nvector_weight = 1e-1\n",
    '[describe]\nlanguages = ["caf\\u00e9", "zh"]\n',
    "# only comments\n\n[search]\n\nlimit = 5\n",
    '[a.b]\nx = 1\n',
    "[search]\nlimit = +7\n",
    '[describe]\nlanguages = []\n',
    # TOML's non-finite float literals. Their absence from this corpus is how
    # the two readers came to disagree about the grammar: one refused `nan` as
    # unparseable while the other accepted it and let the range check reject it,
    # so the same file produced two different errors depending on the version.
    "[search]\nvector_weight = nan\n",
    "[search]\nvector_weight = inf\n",
    "[search]\nvector_weight = -inf\n",
    "[search]\nvector_weight = +nan\n",
]


def _same(left, right) -> bool:
    """Structural equality that treats NaN as equal to itself."""
    if isinstance(left, dict) and isinstance(right, dict):
        return set(left) == set(right) and all(_same(left[k], right[k]) for k in left)
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(_same(a, b) for a, b in zip(left, right))
    if isinstance(left, float) and isinstance(right, float):
        return (left != left and right != right) or left == right
    return type(left) is type(right) and left == right


@pytest.mark.skipif(sys.version_info < (3, 11), reason="tomllib is the reference and only exists from 3.11")
@pytest.mark.parametrize("text", TOML_CASES)
def test_the_fallback_reader_agrees_with_tomllib(text):
    """Differential test.

    The 3.10 leg cannot use `tomllib`, and adding `tomli` would falsify the
    package's no-runtime-dependency claim. So the subset reader is checked
    against the real one wherever the real one exists.
    """
    import tomllib

    assert _same(parse_toml_subset(text), tomllib.loads(text))


@pytest.mark.parametrize(
    "text,fragment",
    [
        ("[search]\nlimit = 2026-01-01\n", "not a value this reader supports"),
        ("[search]\nlimit = {a = 1}\n", "inline tables are not supported"),
        ("[search\nlimit = 1\n", "unterminated table header"),
        ("[search]\nlimit\n", "expected key = value"),
        ('[index]\nignore = ["a"\n', "unterminated array"),
        ('[index]\nignore = ["a\n', "unterminated array"),
    ],
)
def test_the_fallback_reader_refuses_what_it_cannot_read(text, fragment):
    with pytest.raises(ConfigError) as caught:
        parse_toml_subset(text)
    assert fragment in str(caught.value)


@pytest.mark.parametrize("literal", ["nan", "inf", "-inf", "+nan"])
def test_non_finite_values_are_refused_the_same_way_on_every_version(literal):
    """The rejection message must not depend on which reader parsed the file.

    Deliberately without the skipif above, so it runs on 3.10 -- which is
    where the divergence was, and where CI found it.
    """
    with pytest.raises(ConfigError) as caught:
        from_text(f"[search]\nvector_weight = {literal}\n")
    assert "must be finite" in str(caught.value)
