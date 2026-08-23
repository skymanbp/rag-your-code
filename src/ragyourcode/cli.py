"""Command line and JSON-lines agent entry point."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .annotate import comment_for
from .agentic import research
from .embeddings import embedding_metadata
from .graph import build_graph, graph_from_dict, graph_search
from .indexer import StaleMonitor, build_units, fingerprint, read_index, write_index
from .search import build_search_index, context, search


def _default_index(root: Path) -> Path:
    return root / ".rag-your-code" / "index.json"


def _refresh_index(root: Path, output: Path, full: bool = False, compact: bool | None = None) -> dict:
    previous_payload: dict = {}
    previous_units = []
    if output.exists() and not full:
        try:
            previous_payload, previous_units = read_index(output)
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            previous_payload, previous_units = {}, []
    if previous_payload.get("embedding") != embedding_metadata():
        for unit in previous_units:
            unit.vector = []
    if compact is None:
        compact = bool(previous_payload.get("vector_store"))
    diagnostics: list[dict] = []
    units = build_units(root, previous_units=previous_units, previous_files=previous_payload.get("files"), diagnostics=diagnostics)
    graph = build_graph(units)
    write_index(output, root, units, graph.to_dict(), compact=compact, diagnostics=diagnostics)
    return {"indexed_units": len(units), "graph_edges": len(graph.edges), "warnings": len(diagnostics), "incremental": bool(previous_units) and not full, "compact": bool(compact), "index": str(output), "root": str(root)}


def _cmd_index(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    output = Path(args.output) if args.output else _default_index(root)
    print(json.dumps(_refresh_index(root, output, args.full, args.compact), ensure_ascii=False))
    return 0


def _load(args: argparse.Namespace):
    root = Path(args.root).resolve()
    path = Path(args.index) if args.index else _default_index(root)
    payload, units = read_index(path)
    try:
        payload["stale"] = payload.get("fingerprint") != fingerprint(root)
    except OSError:
        payload["stale"] = True
    return payload, units, graph_from_dict(units, payload.get("graph"))


def _cmd_search(args: argparse.Namespace) -> int:
    payload, units, graph = _load(args)
    search_index = build_search_index(units)
    results = graph_search(units, args.query, args.limit, args.hops, graph, search_index) if args.graph else search(units, args.query, args.limit, search_index=search_index)
    if args.json:
        print(json.dumps({"query": args.query, "mode": "graph" if args.graph else "hybrid", "stale": payload.get("stale", True), "degraded": payload.get("degraded"), "results": [result.to_dict() for result in results], "context": context(results, args.max_chars)}, ensure_ascii=False))
    else:
        if payload.get("stale"):
            print("Warning: index is stale; run `rag-your-code index` to refresh.", file=sys.stderr)
        print(context(results, args.max_chars) or "No matching code units.")
    return 0


def _cmd_annotate(args: argparse.Namespace) -> int:
    payload, units, _ = _load(args)
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


def _open_source(root: Path, relative_path: str, start_line=None, end_line=None) -> dict:
    """Open only files inside the indexed repository, with bounded output."""
    candidate = (root / relative_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return {"error": "path_outside_root"}
    if not candidate.is_file():
        return {"error": "file_not_found", "path": relative_path}
    try:
        lines = candidate.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return {"error": "file_unreadable", "path": relative_path}
    first = max(1, int(start_line or 1))
    last = min(len(lines), int(end_line or min(len(lines), first + 200)))
    if first > last:
        return {"error": "invalid_line_range"}
    return {"path": relative_path, "start_line": first, "end_line": last, "source": "\n".join(lines[first - 1:last])}


def _request_int(request: dict, key: str, default: int, minimum: int, maximum: int) -> int:
    return min(maximum, max(minimum, int(request.get(key, default))))


def _cmd_agent(args: argparse.Namespace) -> int:
    """Serve one JSON request per line, suitable for a plugin subprocess."""
    payload, units, graph = _load(args)
    search_index = build_search_index(units)
    root = Path(args.root).resolve()
    stale_monitor = StaleMonitor(root, payload, assume_checked=True)
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
                limit = _request_int(request, "limit", 8, 0, 100)
                hops = _request_int(request, "hops", 1, 0, 3)
                use_graph = bool(request.get("graph", False))
                results = graph_search(units, query, limit, hops, graph, search_index) if use_graph else search(units, query, limit, search_index=search_index)
                response = {"stale": payload.get("stale", True), "results": [result.to_dict() for result in results], "context": context(results, _request_int(request, "max_chars", 12000, 0, 100000))}
            elif action == "research":
                response = research(
                    units,
                    str(request.get("query", "")),
                    _request_int(request, "limit", 8, 0, 100),
                    _request_int(request, "hops", 1, 0, 3),
                    _request_int(request, "max_steps", 2, 1, 2),
                    float(request.get("confidence_threshold", 0.8)),
                    graph,
                    search_index,
                )
                response["stale"] = payload.get("stale", True)
            elif action == "neighbors":
                unit_id = str(request.get("id", ""))
                neighbors = graph.neighbors(unit_id, hops=_request_int(request, "hops", 1, 0, 3), direction=str(request.get("direction", "both")))
                response_neighbors = []
                for unit, path in neighbors[: _request_int(request, "limit", 8, 0, 100)]:
                    data = unit.to_dict(include_vector=False)
                    response_neighbors.append({"path": path, "unit": data})
                response = {"stale": payload.get("stale", True), "id": unit_id, "neighbors": response_neighbors}
            elif action == "open":
                response = _open_source(root, str(request.get("path", "")), request.get("start_line"), request.get("end_line"))
            elif action == "refresh":
                output = Path(args.index) if args.index else _default_index(root)
                response = _refresh_index(root, output)
                payload, units, graph = _load(args)
                search_index = build_search_index(units)
                stale_monitor = StaleMonitor(root, payload, assume_checked=True)
            elif action == "stats":
                response = {"units": len(units), "files": len({unit.path for unit in units}), "edges": len(graph.edges), "warnings": len(payload.get("diagnostics", [])), "compact": bool(payload.get("vector_store")), "embedding": payload.get("embedding"), "stale": payload.get("stale", True)}
            else:
                response = {"error": f"unsupported action: {action}"}
        except (TypeError, ValueError) as exc:
            response = {"error": "invalid_request", "message": str(exc)}
        if "degraded" not in response:
            response["degraded"] = payload.get("degraded")
        print(json.dumps(response, ensure_ascii=False), flush=True)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rag-your-code", description="Index and retrieve explainable code units locally.")
    sub = parser.add_subparsers(dest="command", required=True)
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
    search_parser.add_argument("--limit", type=int, default=8)
    search_parser.add_argument("--max-chars", type=int, default=12000)
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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
