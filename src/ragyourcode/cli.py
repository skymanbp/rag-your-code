"""Command line and JSON-lines agent entry point."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

from . import config as config_module
from . import descriptions as descriptions_module
from .annotate import comment_for
from .agentic import DEFAULT_DOMINANCE, research
from .config import BY_PATH, SETTINGS, Config, ConfigError
from .descriptions import index_descriptions_fingerprint
from .document import plan as plan_documentation, render_patch, summarise as summarise_documentation
from .embeddings import embedder
from .graph import build_graph, graph_from_dict, graph_search
from .indexer import StaleMonitor, build_fingerprint, build_units, fingerprint, index_build_fingerprint, read_index, snapshot_repository, write_index
from .models import SearchResult
from .providers import ProviderError
from .search import build_search_index, context, search, within_budget
from .workflow import apply_descriptions, bootstrap, describe_batch, store_descriptions

# Derived from the settings table so the default is written down once.
# `tests/test_agent_protocol.py` imports these to assert the bound it enforces.
MAX_OPEN_BYTES = BY_PATH["agent.max_open_bytes"].default
MAX_OPEN_CHARS = BY_PATH["agent.max_open_chars"].default


def _default_index(root: Path) -> Path:
    """Where a repository index file is kept when the caller names no other
    location.
    """
    return root / ".rag-your-code" / "index.json"


def _refresh_index(root: Path, output: Path, full: bool = False, compact: bool | None = None, cfg: Config | None = None) -> dict:
    """Builds or rebuilds a repository index and publishes it, reusing the
    previous one where it can. It works out up front whether the rules that
    decide what a unit is have changed — the indexing settings, the vector
    width, or the parser itself — and when they have it discards the
    previous work rather than reusing it, so the report can honestly say
    whether reuse happened. That report previously claimed reuse on exactly
    the runs that had rebuilt everything, because it was computed from
    whether a previous index existed rather than from whether its units were
    kept. It also applies the written descriptions and reports how many
    units still have none.
    """
    cfg = cfg if cfg is not None else config_module.load(root)
    # Built once and handed to every stage of this run, so the vectors stored,
    # the metadata published and the queries later asked all come from the
    # same scheme by construction rather than by three call sites agreeing.
    embed_with = embedder(cfg)
    previous_payload: dict = {}
    previous_units = []
    if output.exists() and not full:
        try:
            previous_payload, previous_units = read_index(output)
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            previous_payload, previous_units = {}, []
    if previous_payload.get("embedding") != embed_with.metadata:
        for unit in previous_units:
            unit.vector = []
    if compact is None:
        compact = bool(previous_payload.get("vector_store"))
    # Settings that decide what an index contains make the previous one an
    # index of something else, not a stale index of this one. Deciding it here
    # rather than only inside build_units is what lets the reported
    # `incremental` describe what the run actually did: it claimed reuse on
    # exactly the runs where the configuration change had forbidden it.
    previous_build = index_build_fingerprint(previous_payload) if previous_payload else None
    inputs_changed = previous_build is not None and previous_build != build_fingerprint(cfg)
    if inputs_changed:
        previous_payload, previous_units = {}, []
    diagnostics: list[dict] = []
    # One snapshot for both halves: parsing from one walk and publishing hashes
    # from another let a save landing between them poison incremental reuse.
    snapshot = snapshot_repository(root, cfg)
    store = descriptions_module.load(root)
    units = build_units(
        root,
        previous_units=previous_units,
        previous_files=previous_payload.get("files"),
        diagnostics=diagnostics,
        snapshot=snapshot,
        cfg=cfg,
        previous_build=None if inputs_changed else previous_build,
        descriptions=store,
        embed_with=embed_with,
    )
    graph = build_graph(units)
    write_index(output, root, units, graph.to_dict(), compact=compact, diagnostics=diagnostics, snapshot=snapshot, cfg=cfg, descriptions_fingerprint=store.fingerprint, embed_with=embed_with)
    groups = store.classify(units)
    return {
        "indexed_units": len(units),
        "graph_edges": len(graph.edges),
        "warnings": len(diagnostics),
        "incremental": bool(previous_units) and not full,
        "rebuilt_for_inputs": inputs_changed,
        "compact": bool(compact),
        "described": len(groups["described"]),
        "pending_descriptions": len(groups["missing"]) + len(groups["superseded"]),
        "index": str(output),
        "root": str(root),
        "config": str(cfg.source) if cfg.source else None,
    }


def _cmd_bootstrap(args: argparse.Namespace) -> int:
    """The bootstrap command: index, say how far this repository is from being
    searchable, and hand over the next step's work packet.
    """
    root = Path(args.root).resolve()
    cfg = config_module.load(root)
    output = Path(args.output) if args.output else _default_index(root)
    index_report = _refresh_index(root, output, args.full, None, cfg)
    _, units = read_index(output)
    report = bootstrap(units, descriptions_module.load(root), cfg, root, index_report, args.limit)
    if args.json:
        print(json.dumps(report, ensure_ascii=False))
        return 0
    step = report["next"]
    print(f"indexed   {report['index']['indexed_units']} units, {report['index']['graph_edges']} edges")
    print(f"described {report['described']} written, {report['superseded']} outgrown by the code, {report['missing']} never written")
    print(f"in source {report['already_documented']} declarations carry the author's own documentation")
    print(f"\nnext: {step['action']}\n  {step['why']}")
    for line in step["how"]:
        print(f"  - {line}")
    return 0


def _cmd_index(args: argparse.Namespace) -> int:
    """The index command: scans a repository and writes its index, reporting
    how many units and relationships were found and how many descriptions
    are still pending.
    """
    root = Path(args.root).resolve()
    cfg = config_module.load(root)
    output = Path(args.output) if args.output else _default_index(root)
    print(json.dumps(_refresh_index(root, output, args.full, args.compact, cfg), ensure_ascii=False))
    return 0


def _load(args: argparse.Namespace):
    """Opens a published index for a read-only command and settles whether it
    is still current. Three things can make it out of date and only one of
    them is a file edit: the repository content can have moved, the rules
    that decide what a unit is can have changed, or the written descriptions
    can have changed. Neither authored input nor the parser is an indexed
    file, so each has to report itself.
    """
    root = Path(args.root).resolve()
    cfg = config_module.load(root)
    store = descriptions_module.load(root)
    path = Path(args.index) if args.index else _default_index(root)
    payload, units = read_index(path)
    try:
        # Both authored inputs are invisible to a file fingerprint. A changed
        # configuration means the index describes a different corpus; changed
        # descriptions mean it serves text nobody wrote any more. Neither moves
        # a tracked file, so each has to report itself.
        stale = payload.get("fingerprint") != fingerprint(root, cfg)
        stale = stale or index_build_fingerprint(payload) != build_fingerprint(cfg)
        payload["stale"] = stale or index_descriptions_fingerprint(payload) != store.fingerprint
    except OSError:
        payload["stale"] = True
    return payload, units, graph_from_dict(units, payload.get("graph")), cfg, store


def _cmd_search(args: argparse.Namespace) -> int:
    """The search command: retrieves the code units most relevant to a
    question, optionally following relationships outward, and prints either
    a readable context block or machine-readable output for an agent. Result
    count, context budget and the balance between word overlap and vector
    similarity all fall back to the repository settings when no flag
    overrides them. Warns when the index no longer describes the repository.
    """
    payload, units, graph, cfg, _ = _load(args)
    limit = args.limit if args.limit is not None else cfg["search.limit"]
    max_chars = args.max_chars if args.max_chars is not None else cfg["search.max_chars"]
    weight = cfg["search.vector_weight"]
    search_index = build_search_index(units, embedder(cfg))
    recall = cfg["search.vector_recall"]
    results = (
        graph_search(units, args.query, limit, args.hops, graph, search_index, vector_weight=weight, vector_recall=recall)
        if args.graph
        else search(units, args.query, limit, search_index=search_index, vector_weight=weight, vector_recall=recall)
    )
    if args.json:
        # Results are navigation and cost almost nothing, so every one that was
        # found is reported. The budget decides how many of them arrive with
        # their code attached, and says how many did not.
        shown = within_budget(results, max_chars)
        print(json.dumps({"query": args.query, "mode": "graph" if args.graph else "hybrid", "stale": payload.get("stale", True), "degraded": payload.get("degraded"), "results": [result.to_dict() for result in results], "omitted_for_budget": len(results) - len(shown), "context": context(shown, max_chars)}, ensure_ascii=False))
    else:
        if payload.get("stale"):
            print("Warning: index is stale; run `rag-your-code index` to refresh.", file=sys.stderr)
        print(context(results, max_chars) or "No matching code units.")
    return 0


def _cmd_annotate(args: argparse.Namespace) -> int:
    """The annotate command: writes a numbered inventory of every indexed unit
    to a separate document, with its location, kind and description. Source
    files are never touched. Refuses to run against an index that no longer
    describes the repository, since a numbered inventory of stale code is
    worse than none.
    """
    payload, units, _, _, _ = _load(args)
    if payload.get("stale"):
        print("Index is stale; run `rag-your-code index` before annotating.", file=sys.stderr)
        return 2
    output = Path(args.output) if args.output else Path(args.root) / ".rag-your-code" / "annotations.md"
    output.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# RAG Your Code annotations", "", "Generated sidecar comments; source files are unchanged.", ""]
    for unit in units:
        lines.extend([f"## [{unit.serial:05d}] {unit.id}", "", f"- Location: `{unit.path}:{unit.start_line}-{unit.end_line}`", f"- Kind: `{unit.kind}`", f"- Comment: {comment_for(unit.description, unit.serial, unit.id)}", "", unit.description, ""])
    output.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"annotations": len(units), "output": str(output)}, ensure_ascii=False))
    return 0


def _cmd_config(args: argparse.Namespace) -> int:
    """The config command: creates a commented settings file, lists every
    setting with its effective value and whether it was customised, reads
    one value, changes one value in place, or reports where the file lives.
    Changing a value refuses anything out of range before writing, so a
    rejected change leaves the file exactly as it was, and the reply says
    whether the change forces a full rebuild. Creating refuses to overwrite
    an existing file unless told to.
    """
    root = Path(args.root).resolve()
    path = config_module.config_path(root)
    if args.action == "path":
        print(json.dumps({"path": str(path), "exists": path.is_file()}, ensure_ascii=False))
        return 0
    if args.action == "init":
        if path.is_file() and not args.force:
            print(f"error: {path.name} already exists; pass --force to overwrite", file=sys.stderr)
            return 2
        path.write_text(config_module.render_template(), encoding="utf-8", newline="\n")
        print(json.dumps({"created": str(path), "settings": len(SETTINGS)}, ensure_ascii=False))
        return 0
    cfg = config_module.load(root)
    if args.action == "get":
        if args.name not in BY_PATH:
            print(f"error: unknown setting {args.name}", file=sys.stderr)
            return 2
        print(json.dumps({"name": args.name, "value": cfg[args.name]}, ensure_ascii=False, default=list))
        return 0
    if args.action == "set":
        setting = BY_PATH.get(args.name)
        if setting is None:
            print(f"error: unknown setting {args.name}", file=sys.stderr)
            return 2
        value = config_module.parse_literal(setting, args.value)
        config_module.update_file(path, args.name, value)
        print(json.dumps({"name": args.name, "value": value, "path": str(path), "rebuild_required": setting.affects_build}, ensure_ascii=False, default=list))
        return 0
    listing = [
        {
            "name": setting.path,
            "value": cfg[setting.path],
            "default": setting.default,
            "customised": cfg[setting.path] != setting.default,
            "affects_build": setting.affects_build,
            "help": setting.help,
        }
        for setting in SETTINGS
    ]
    print(json.dumps({"source": str(cfg.source) if cfg.source else None, "build_fingerprint": cfg.build_fingerprint, "settings": listing}, ensure_ascii=False, indent=2, default=list))
    return 0


def _cmd_describe(args: argparse.Namespace) -> int:
    """The describe command: reports how many units have a usable description,
    how many have one the code has since outgrown and how many have none;
    exports a batch of pending work with source and brief; imports written
    descriptions back; or emits a patch that moves a description into the
    source as a doc comment. Importing says explicitly that a rebuild is
    needed, because the published index still holds the previous wording and
    no source file moved to signal it. The patch owns standard output so it
    can be piped straight into git apply.
    """
    payload, units, _, cfg, store = _load(args)
    if args.action == "promote":
        # A stored description exists so text about a unit can be written
        # without touching the file, and that independence costs a digest, a
        # relocation lookup, a fingerprint and a pruning rule -- all of them
        # simulating a property a docstring has for free. This offers the
        # promotion as a patch rather than performing it: the tool still never
        # writes source, and a person stays between an agent's prose and the
        # repository.
        root = Path(args.root).resolve()
        insertions = plan_documentation(units, store, root)
        report = summarise_documentation(units, store, insertions, root)
        patch = render_patch(root, insertions)
        if args.output:
            Path(args.output).write_text(patch, encoding="utf-8", newline="")
            report["output"] = args.output
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            # The patch owns stdout so it can be piped straight into `git
            # apply`; the summary goes to stderr.
            sys.stdout.write(patch)
            print(json.dumps(report, ensure_ascii=False), file=sys.stderr)
        return 0
    if args.action == "status":
        groups = store.classify(units)
        print(json.dumps({
            "units": len(units),
            "described": len(groups["described"]),
            "superseded": len(groups["superseded"]),
            "missing": len(groups["missing"]),
            "coverage": round(len(groups["described"]) / len(units), 4) if units else 0.0,
            "path": str(store.path),
            "exists": store.path.is_file(),
            "stale_index": bool(payload.get("stale")),
        }, ensure_ascii=False, indent=2))
        return 0
    if args.action == "export":
        limit = args.limit if args.limit is not None else cfg["describe.batch"]
        batch = describe_batch(units, store, cfg, limit)
        text = json.dumps(batch, ensure_ascii=False, indent=2)
        if args.output:
            Path(args.output).write_text(text + "\n", encoding="utf-8", newline="\n")
            print(json.dumps({"exported": len(batch["units"]), "remaining": batch["remaining"], "output": args.output}, ensure_ascii=False))
        else:
            print(text)
        return 0
    incoming = json.loads(Path(args.file).read_text(encoding="utf-8"))
    if isinstance(incoming, dict):
        incoming = incoming.get("descriptions", [])
    report = store_descriptions(units, store, cfg, incoming)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not report["rejected"] else 1


def _open_source(root: Path, relative_path: str, start_line=None, end_line=None, cfg: Config | None = None) -> dict:
    """Open only files inside the indexed repository, with bounded output.

    Two bounds, because a line count is not a size. The indexer skips sources
    over `index.max_file_bytes`, but `open` accepts any in-tree path, and a
    three-line file holding one two-megabyte line satisfied the old 200-line
    bound while returning two megabytes on a single JSON line.
    """
    max_bytes = cfg["agent.max_open_bytes"] if cfg is not None else MAX_OPEN_BYTES
    max_chars = cfg["agent.max_open_chars"] if cfg is not None else MAX_OPEN_CHARS
    candidate = (root / relative_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return {"error": "path_outside_root"}
    if not candidate.is_file():
        return {"error": "file_not_found", "path": relative_path}
    try:
        if candidate.stat().st_size > max_bytes:
            return {"error": "file_too_large", "path": relative_path, "limit_bytes": max_bytes}
        lines = candidate.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return {"error": "file_unreadable", "path": relative_path}
    first = max(1, int(start_line or 1))
    last = min(len(lines), int(end_line or min(len(lines), first + 200)))
    if first > last:
        return {"error": "invalid_line_range"}
    source = chr(10).join(lines[first - 1:last])
    response = {"path": relative_path, "start_line": first, "end_line": last}
    if len(source) > max_chars:
        source = source[:max_chars]
        response["truncated"] = True
        response["truncated_at_chars"] = max_chars
    response["source"] = source
    return response


def _request_int(request: dict, key: str, default: int, minimum: int, maximum: int) -> int:
    """Clamp a numeric request field into [minimum, maximum].

    The clamp must survive non-finite floats. A host sending `1e400` produces
    `inf`, and `int(inf)` raises OverflowError, which is neither TypeError nor
    ValueError; it escaped the request loop and killed the daemon. Saturating at
    the bound is the reading the caller intended anyway.
    """
    raw = request.get(key, default)
    if isinstance(raw, float):
        if raw != raw:
            return default
        if raw == math.inf:
            return maximum
        if raw == -math.inf:
            return minimum
    return min(maximum, max(minimum, int(raw)))


def _cmd_agent(args: argparse.Namespace) -> int:
    """Serve one JSON request per line, suitable for a plugin subprocess."""
    payload, units, graph, cfg, store = _load(args)
    search_index = build_search_index(units, embedder(cfg))
    root = Path(args.root).resolve()
    weight = cfg["search.vector_weight"]
    default_limit = cfg["search.limit"]
    default_chars = cfg["search.max_chars"]
    recall = cfg["search.vector_recall"]
    stale_monitor = StaleMonitor(root, payload, assume_checked=True, cfg=cfg, descriptions_fingerprint=store.fingerprint)
    # Descriptions stored this session reach the live units immediately but not
    # the published index, which is a different thing from the index being
    # stale against the repository.
    index_behind = False
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError as exc:
            print(json.dumps({"error": "invalid_json", "message": str(exc)}, ensure_ascii=False), flush=True)
            continue
        if not isinstance(request, dict):
            print(json.dumps({"error": "invalid_request", "message": "request must be a JSON object"}), flush=True)
            continue
        stale_monitor.check(force=request.get("action") == "stats")
        try:
            action = request.get("action", "search")
            if action == "search":
                query = str(request.get("query", ""))
                limit = _request_int(request, "limit", default_limit, 0, 100)
                hops = _request_int(request, "hops", 1, 0, 3)
                use_graph = bool(request.get("graph", False))
                results = (
                    graph_search(units, query, limit, hops, graph, search_index, vector_weight=weight, vector_recall=recall)
                    if use_graph
                    else search(units, query, limit, search_index=search_index, vector_weight=weight, vector_recall=recall)
                )
                budget = _request_int(request, "max_chars", default_chars, 0, 100000)
                shown = within_budget(results, budget)
                response = {"stale": payload.get("stale", True), "results": [result.to_dict() for result in results], "omitted_for_budget": len(results) - len(shown), "context": context(shown, budget)}
            elif action == "research":
                response = research(
                    units,
                    str(request.get("query", "")),
                    _request_int(request, "limit", default_limit, 0, 100),
                    _request_int(request, "hops", 1, 0, 3),
                    _request_int(request, "max_steps", 2, 1, 2),
                    float(request.get("dominance_threshold", DEFAULT_DOMINANCE)),
                    graph,
                    search_index,
                    vector_weight=weight,
                    vector_recall=recall,
                    max_chars=_request_int(request, "max_chars", default_chars, 0, 100000),
                )
                response["stale"] = payload.get("stale", True)
            elif action == "neighbors":
                unit_id = str(request.get("id", ""))
                neighbors = graph.neighbors(unit_id, hops=_request_int(request, "hops", 1, 0, 3), direction=str(request.get("direction", "both")))
                reached = neighbors[: _request_int(request, "limit", default_limit, 0, 100)]
                # Same rule as every other reply: the entries say where to look
                # and how they were reached, and the code arrives once, under
                # the budget. Carrying a full source per neighbour made walking
                # a graph the most expensive thing an agent could ask for.
                neighbor_budget = _request_int(request, "max_chars", default_chars, 0, 100000)
                # `path` is already the chain of unit ids that reached this
                # neighbour, which is exactly what a context block renders as
                # evidence.
                as_results = [SearchResult(unit, 0.0, [], path) for unit, path in reached]
                response = {
                    "stale": payload.get("stale", True),
                    "id": unit_id,
                    "neighbors": [{"path": path, "unit": unit.to_dict(include_vector=False, include_source=False)} for unit, path in reached],
                    "context": context(within_budget(as_results, neighbor_budget), neighbor_budget),
                }
            elif action == "open":
                response = _open_source(root, str(request.get("path", "")), request.get("start_line"), request.get("end_line"), cfg)
            elif action == "bootstrap":
                # The same rung report the command line prints, so an agent
                # meeting a repository for the first time learns what it is
                # missing in one request instead of from the documentation.
                # No index is written here: this session already holds the
                # units, and a serving process should not rewrite the file
                # underneath itself.
                response = bootstrap(units, store, cfg, root, {"indexed_units": len(units), "graph_edges": len(graph.edges)}, _request_int(request, "limit", cfg["describe.batch"], 0, 200))
            elif action == "describe_pending":
                response = describe_batch(units, store, cfg, _request_int(request, "limit", cfg["describe.batch"], 0, 200))
            elif action == "describe_put":
                response = store_descriptions(units, store, cfg, request.get("descriptions", []))
                # Applied to the live units immediately, so the next search in
                # this session already retrieves on the new words rather than
                # waiting for a refresh the agent has no reason to expect.
                response["applied"] = apply_descriptions(units, store, cfg)
                if response["applied"]:
                    search_index = build_search_index(units, embedder(cfg))
                index_behind = index_behind or response["reindex_required"]
            elif action == "refresh":
                output = Path(args.index) if args.index else _default_index(root)
                response = _refresh_index(root, output, cfg=cfg)
                payload, units, graph, cfg, store = _load(args)
                search_index = build_search_index(units, embedder(cfg))
                stale_monitor = StaleMonitor(root, payload, assume_checked=True, cfg=cfg, descriptions_fingerprint=store.fingerprint)
                index_behind = False
            elif action == "stats":
                response = {"units": len(units), "files": len({unit.path for unit in units}), "edges": len(graph.edges), "warnings": len(payload.get("diagnostics", [])), "compact": bool(payload.get("vector_store")), "embedding": payload.get("embedding"), "config": str(cfg.source) if cfg.source else None, "described": len(store.applicable(units)), "index_behind": index_behind, "stale": payload.get("stale", True)}
            else:
                response = {"error": f"unsupported action: {action}"}
        except (TypeError, ValueError) as exc:
            response = {"error": "invalid_request", "message": str(exc)}
        except Exception as exc:
            # A daemon serving untrusted request lines must not be able to die
            # because one of them was malformed. Enumerating the expected
            # exception types WAS the defect: int(1e400) raises OverflowError,
            # which is neither TypeError nor ValueError, so a single request
            # terminated the process and every later request went unanswered.
            # This reports the failure in-band rather than swallowing it -- the
            # exception type is returned so a genuine defect stays diagnosable --
            # and KeyboardInterrupt/SystemExit still stop the loop, being
            # BaseException rather than Exception.
            response = {"error": "request_failed", "type": type(exc).__name__, "message": str(exc)}
        if "degraded" not in response:
            response["degraded"] = payload.get("degraded")
        print(json.dumps(response, ensure_ascii=False), flush=True)
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Declares the whole command-line surface: indexing, retrieval,
    annotation, the long-running agent, settings, and descriptions including
    the promotion patch, with their options and help text. Options that have
    a configurable counterpart default to nothing rather than to a literal,
    so an unset flag means whatever the repository configured instead of a
    number frozen into the program.
    """
    parser = argparse.ArgumentParser(prog="rag-your-code", description="Index and retrieve explainable code units locally.")
    sub = parser.add_subparsers(dest="command", required=True)
    boot = sub.add_parser("bootstrap", help="index, then say what this repository still needs to be searchable")
    boot.add_argument("root", nargs="?", default=".")
    boot.add_argument("--output")
    boot.add_argument("--full", action="store_true", help="ignore an existing index and rebuild every file")
    boot.add_argument("--limit", type=int, default=None, help=f"units per batch (config describe.batch, default {BY_PATH['describe.batch'].default})")
    boot.add_argument("--json", action="store_true")
    boot.set_defaults(func=_cmd_bootstrap)
    index = sub.add_parser("index", help="scan a repository and build its local index")
    index.add_argument("root", nargs="?", default=".")
    index.add_argument("--output")
    index.add_argument("--full", action="store_true", help="ignore an existing index and rebuild every file")
    index.add_argument("--compact", action="store_true", default=None, help="store vectors in a float32 sidecar to reduce JSON size")
    index.set_defaults(func=_cmd_index)
    search_parser = sub.add_parser("search", help="retrieve code units")
    search_parser.add_argument("query")
    search_parser.add_argument("--root", default=".")
    search_parser.add_argument("--index")
    # These default to None rather than to a literal so that an unset flag means
    # "whatever the repository configured", not "8". The effective value is
    # reported by `rag-your-code config list`.
    search_parser.add_argument("--limit", type=int, default=None, help=f"results to return (config search.limit, default {BY_PATH['search.limit'].default})")
    search_parser.add_argument("--max-chars", type=int, default=None, help=f"context budget (config search.max_chars, default {BY_PATH['search.max_chars'].default})")
    search_parser.add_argument("--json", action="store_true")
    search_parser.add_argument("--graph", action="store_true", help="expand results through calls/imports/contains edges")
    search_parser.add_argument("--hops", type=int, default=1)
    search_parser.set_defaults(func=_cmd_search)
    annotate = sub.add_parser("annotate", help="write numbered descriptive sidecar comments")
    annotate.add_argument("--root", default=".")
    annotate.add_argument("--index")
    annotate.add_argument("--output")
    annotate.set_defaults(func=_cmd_annotate)
    agent = sub.add_parser("agent", help="serve JSON-lines requests for a coding agent")
    agent.add_argument("--root", default=".")
    agent.add_argument("--index")
    agent.set_defaults(func=_cmd_agent)
    config_parser = sub.add_parser("config", help="inspect or change rag-your-code.toml")
    config_parser.add_argument("action", choices=("list", "get", "set", "init", "path"))
    config_parser.add_argument("name", nargs="?", help="dotted setting name, e.g. search.vector_weight")
    config_parser.add_argument("value", nargs="?", help="TOML literal, e.g. 0.25 or '[\".py\", \".vue\"]'")
    config_parser.add_argument("--root", default=".")
    config_parser.add_argument("--force", action="store_true", help="with init, overwrite an existing file")
    config_parser.set_defaults(func=_cmd_config)
    describe = sub.add_parser("describe", help="inspect or supply agent-authored unit descriptions")
    describe.add_argument("action", choices=("status", "export", "import", "promote"))
    describe.add_argument("file", nargs="?", help="with import, a JSON file of {id, text} objects")
    describe.add_argument("--root", default=".")
    describe.add_argument("--index")
    describe.add_argument("--limit", type=int, default=None, help=f"with export, units per batch (config describe.batch, default {BY_PATH['describe.batch'].default})")
    describe.add_argument("--output", help="with export or promote, write here instead of stdout")
    describe.set_defaults(func=_cmd_describe)
    return parser


def _use_utf8_streams() -> None:
    """Pin the process streams to UTF-8, which is what the protocol promises.

    The index and the JSON-lines agent protocol are UTF-8 by contract, but
    Python decodes stdio with the OS locale codepage. On a non-UTF-8 console
    (cp936, cp1252) that costs correctness twice: printing a response whose
    source or docstring holds a character outside the codepage raises
    UnicodeEncodeError and kills a long-lived ``agent`` subprocess, and a
    request line written as UTF-8 by the host is mis-decoded into mojibake
    that matches nothing and returns an empty, exit-0 result.
    """
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:  # pytest capture and other wrappers are not TextIOWrapper
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError, ValueError):
            # A stream that refuses reconfiguration (already detached, or a
            # binary substitute) keeps its own encoding. Failing the whole
            # command over stream setup would be worse than the mojibake.
            continue


def main(argv: list[str] | None = None) -> int:
    """The program entry point: pins the streams, parses the command line, runs
    the chosen command, and turns an expected failure into a message and a
    non-zero exit code instead of a stack trace. A settings problem is
    reported separately and names the file, because that fix is always in
    one known place.
    """
    _use_utf8_streams()
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except ProviderError as exc:
        # A provider that cannot be reached or cannot be trusted stops the run
        # rather than falling back: an index whose vectors come from two
        # spaces would rank confidently on a number that means nothing.
        print(f"error: embedding provider: {exc}", file=sys.stderr)
        return 2
    except ConfigError as exc:
        # Surfaced separately from the generic handler because the fix is
        # always in one named file: say which, so the message is actionable.
        print(f"error: {config_module.CONFIG_FILENAME}: {exc}", file=sys.stderr)
        return 2
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
