import argparse
import json
import re
import sys
from pathlib import Path

import pytest

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
    """Every place a version is written down, including the marketplace entry.

    The marketplace file states it twice and was outside this check until
    0.4.0, which is exactly the shape of thing that goes stale: nothing reads
    it during development, so a drift only surfaces to someone installing the
    plugin.
    """
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    plugin = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    market = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
    version = ragyourcode.__version__
    assert project["project"]["version"] == version
    assert plugin["version"] == version
    assert market["metadata"]["version"] == version
    assert [entry["version"] for entry in market["plugins"]] == [version]


def test_the_manifests_point_at_a_repository_that_exists():
    """Both manifests declare a home, and they declare the same one."""
    plugin = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    market = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
    urls = {plugin["homepage"], plugin["repository"], market["homepage"], market["repository"]}
    urls.update(market["plugins"][0][key] for key in ("homepage", "repository"))
    assert urls == {"https://github.com/skymanbp/rag-your-code"}


# --- the documentation an agent is told to follow must be executable --------

DOCS = ("skills/rag-your-code/SKILL.md", "README.md")


def _subcommands() -> set[str]:
    from ragyourcode.cli import build_parser

    for action in build_parser()._actions:
        if isinstance(action, argparse._SubParsersAction):
            return set(action.choices)
    raise AssertionError("the CLI has no subparsers")


def _protocol_actions() -> set[str]:
    """Actions the agent loop actually dispatches on.

    `args.action` is a subcommand's own verb -- `config set`, `describe
    export` -- and matching it here quietly folded eight of those into the
    protocol's roster. Nothing noticed while the only assertion ran one way.
    """
    source = (ROOT / "src" / "ragyourcode" / "cli.py").read_text(encoding="utf-8")
    return set(re.findall(r'(?<!args\.)action == "([a-z_]+)"', source)) | {"search"}


def test_every_documented_subcommand_exists():
    known = _subcommands()
    for name in DOCS:
        text = (ROOT / name).read_text(encoding="utf-8")
        used = set(re.findall(r"(?:python -m ragyourcode\.cli|rag-your-code) ([a-z-]+)", text))
        unknown = used - known
        assert not unknown, f"{name} documents subcommands that do not exist: {sorted(unknown)}"


def test_every_documented_protocol_action_is_handled():
    known = _protocol_actions()
    for name in DOCS:
        text = (ROOT / name).read_text(encoding="utf-8")
        used = set(re.findall(r'"action"\s*:\s*"([a-z_]+)"', text))
        unknown = used - known
        assert not unknown, f"{name} documents actions the agent loop ignores: {sorted(unknown)}"
        assert used, f"{name} should show at least one protocol action"


def test_the_documented_list_of_actions_is_the_real_list():
    """The prose roster, not just the JSON examples.

    Only actions written as `{"action":"..."}` were checked, so the sentence
    that enumerates them could name one the loop had never heard of and
    nothing would notice -- the same defect as an install line nobody ran.
    Both directions are asserted: a documented action must exist, and an
    implemented one must be documented, because an action nobody is told about
    is not a feature.
    """
    known = _protocol_actions()
    text = (ROOT / "skills" / "rag-your-code" / "SKILL.md").read_text(encoding="utf-8")
    roster = re.search(r"Supported actions are(.+?)\.", text, re.S)
    assert roster, "SKILL.md must enumerate the protocol actions"
    listed = set(re.findall(r"`([a-z_]+)`", roster.group(1)))
    assert listed - known == set(), f"SKILL.md lists actions the agent loop ignores: {sorted(listed - known)}"
    assert known - listed == set(), f"the agent loop handles actions SKILL.md never mentions: {sorted(known - listed)}"


def _publishes_to_pypi() -> bool:
    """Whether this repository actually uploads its distributions to PyPI.

    Read from the workflow rather than asserted as a constant, so the guard
    below cannot be satisfied by editing a boolean.
    """
    workflow = ROOT / ".github" / "workflows" / "release.yml"
    return workflow.is_file() and "gh-action-pypi-publish" in workflow.read_text(encoding="utf-8")


def test_no_document_claims_this_package_is_on_an_index_it_is_not_on():
    """The audit found SKILL.md naming a module nothing installs.

    0.3.0 replaced that with `pip install rag-your-code`, a package index this
    project did not publish to, so the instruction was still unrunnable and
    nothing checked it. An install line must name a source that resolves: a
    URL, a path, an editable checkout -- or this project's own distribution
    name, and that one only while a workflow in this repository actually
    uploads to PyPI. The condition is read from the workflow, so removing
    publishing without fixing the docs fails here rather than silently
    restoring the original defect.
    """
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["name"]
    allowed_names = {project, project.replace("-", "_")} if _publishes_to_pypi() else set()
    # Flags first, then an optionally quoted target -- `--user "git+https://..."`
    # is the documented form, and a target class that excluded the quote made
    # the flag itself look like the target.
    pattern = re.compile(r"""pip install\s+(?:(?:--user|-q|--upgrade|--no-deps)\s+)*["']?(?P<target>[^\s`"']+)""")
    declared_extras = set(tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"].get("optional-dependencies", {}))
    seen = 0
    for name in DOCS:
        for target in pattern.findall((ROOT / name).read_text(encoding="utf-8")):
            seen += 1
            # `rag-your-code[sentence-transformers]` is an installable source and
            # the bracket is part of what makes it one, so the extras are split
            # off and checked against the extras pyproject actually declares --
            # a documented extra that does not exist is the same defect as a
            # documented index this project does not publish to.
            base, _, extras = target.partition("[")
            named = {piece.strip() for piece in extras.rstrip("]").split(",") if piece.strip()}
            assert named <= declared_extras, f"{name}: `pip install {target}` names undeclared extras: {sorted(named - declared_extras)}"
            assert (
                base.startswith(("git+", "http", ".", "/", "-e"))
                or base.endswith((".whl", ".tar.gz"))
                or base in allowed_names
            ), f"{name}: `pip install {target}` names no installable source"
    assert seen, "the install instructions vanished; this guard would then pass vacuously"


def test_the_documented_fixture_counts_are_the_real_ones():
    """Numbers stated in prose, checked against the data they describe.

    `docs/TESTING.md` claimed 96 deliberately-excluded constructs where the
    fixtures hold 89 -- the count of expected units, copied one line up. It
    survived because a number in a sentence is exactly the kind of claim no
    gate looks at. Each label below is checked only where a document states
    it, so wording stays free while the figures cannot drift.
    """
    fixtures = json.loads((ROOT / "tests" / "fixtures" / "languages" / "expected.json").read_text(encoding="utf-8"))
    units = [unit for spec in fixtures.values() for unit in spec["expected"]]
    truth = {
        r"(\d+) (?:realistic )?fixture files": len(fixtures),
        r"(\d+) expected units": len(units),
        r"\((\d+) core": sum(1 for unit in units if unit.get("tier", "core") == "core"),
        r"(\d+) stretch": sum(1 for unit in units if unit.get("tier", "core") != "core"),
        r"(\d+) negative cases": sum(len(spec["negatives"]) for spec in fixtures.values()),
        r"(\d+) constructs": sum(len(spec["spec_exclusions"]) for spec in fixtures.values()),
    }
    stated = 0
    for name in ("docs/TESTING.md", "README.md"):
        text = (ROOT / name).read_text(encoding="utf-8")
        for pattern, expected in truth.items():
            for groups in re.findall(pattern, text):
                found = next(value for value in (groups if isinstance(groups, tuple) else (groups,)) if value)
                stated += 1
                assert int(found) == expected, f"{name}: {pattern!r} says {found}, the fixtures hold {expected}"
    assert stated >= len(truth), "the documented counts vanished; this guard would then pass vacuously"


def test_the_release_workflow_publishes_under_the_name_the_project_declares():
    """A tag, a package name and a trusted-publisher claim that disagree.

    Publishing is irreversible, so the two things that decide *what* gets
    published are checked here rather than discovered on PyPI: the workflow
    filename, which the trusted-publisher claim is bound to, and the version
    guard that refuses a tag disagreeing with pyproject.
    """
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "gh-action-pypi-publish" in workflow
    assert "id-token: write" in workflow, "trusted publishing needs an OIDC token"
    assert "does not match pyproject version" in workflow, "a tag must not be able to disagree with the package"


def test_the_documented_settings_are_the_settings_that_exist():
    """The README's configuration table, against the settings table itself.

    It shipped 0.8.0 listing twelve of twenty-one, missing every provider
    setting that release existed to add. Nothing noticed, because a table is
    read as complete whether or not it is, and a reader has no way to tell a
    section that omits nine things from one that omits none. Both directions
    are asserted: a documented setting must exist, and an existing one must be
    documented, since a setting nobody is told about is not configurable.
    """
    from ragyourcode.config import SETTINGS

    text = (ROOT / "README.md").read_text(encoding="utf-8")
    documented: set[str] = set()
    for section, names in re.findall(r"^\| `\[(\w+)\]` \| (.+?) \|$", text, re.M):
        documented.update(f"{section}.{name}" for name in re.findall(r"`(\w+)`", names))
    real = {setting.path for setting in SETTINGS}
    assert documented - real == set(), f"README documents settings that do not exist: {sorted(documented - real)}"
    assert real - documented == set(), f"settings nobody is told about: {sorted(real - documented)}"
    stated = re.search(r"(\d+) settings in `rag-your-code\.toml`", text)
    assert stated, "the README must say how many settings there are"
    assert int(stated.group(1)) == len(real), f"README says {stated.group(1)} settings, there are {len(real)}"


def test_every_documented_provider_block_actually_configures_that_provider(tmp_path: Path):
    """The README's configuration blocks, executed rather than trusted.

    An install line naming an index this project did not publish to, and a
    count copied from the line above it, both shipped because nothing ran
    them. A settings example is the same kind of claim: it looks right until
    somebody pastes it.

    Every documented block is run, not the first one found. The README grew a
    second provider and the old single-block form went on passing against the
    block that happened to match first, which would have let the new one ship
    untested -- the same shape of gap as a roster checked in one direction.
    """
    from ragyourcode import config as config_module
    from ragyourcode.embeddings import embedder
    from ragyourcode.providers import ProviderError

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    blocks = re.findall(r"```toml\n(.*?)```", readme, re.S)
    configured = [block for block in blocks if "provider" in block]
    assert configured, "the README must show how to configure a provider"
    assert 'api_key_env = "' in readme, "the README must show that the key is named, not pasted"

    seen: set[str] = set()
    for block in configured:
        settings = "\n".join(line for line in block.splitlines() if not line.startswith("#"))
        if "[embedding]" not in settings:
            settings = "[embedding]\n" + settings
        (tmp_path / "rag-your-code.toml").write_text(settings + "\n", encoding="utf-8")
        cfg = config_module.load(tmp_path)
        name = cfg["embedding.provider"]
        seen.add(name)
        try:
            resolved = embedder(cfg)
        except ProviderError as exc:
            # The optional extra may legitimately be absent here; anything else
            # means the documented settings do not describe a usable provider.
            assert "pip install" in str(exc), f"documented block for {name} is not configurable: {exc}"
            continue
        except OSError as exc:
            # Installed but the weights are neither cached nor reachable. That
            # is the environment failing, not the documentation, and asserting
            # on it would make this test depend on a network it does not need.
            pytest.skip(f"{name}: model weights unavailable here ({exc})")
        assert resolved.provider == name
        assert resolved.semantic is (name != "signed-feature-hash")
        # A key pasted into a documented block would be the defect this whole
        # arrangement exists to prevent.
        assert "sk-" not in settings
    assert {"sentence-transformers", "openai-compatible"} <= seen, f"undocumented providers; README shows {sorted(seen)}"
