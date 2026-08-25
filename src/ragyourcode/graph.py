"""Explainable symbol graph used by graph-aware retrieval.

The graph is intentionally derived from the parser's stable ``CodeUnit`` IDs.
Edges are conservative: unresolved calls are omitted rather than guessed. This
keeps graph expansion useful for navigation without fabricating relationships.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Iterable

from .models import CodeUnit, SearchResult
from .search import DEFAULT_VECTOR_RECALL, DEFAULT_VECTOR_WEIGHT, SearchIndex, search


@dataclass(frozen=True, slots=True)
class CodeEdge:
    """One directed relationship between two code units, carrying its kind and
    a human-readable label. Kinds are deliberately few and conservative: one
    unit calls another, imports it, or contains it.
    """
    source: str
    target: str
    kind: str
    label: str = ""

    def to_dict(self) -> dict[str, str]:
        """Serialises one relationship for storage inside the index or for an
        agent reply.
        """
        return {"source": self.source, "target": self.target, "kind": self.kind, "label": self.label}


class CodeGraph:
    """Directed code relationship graph with bounded neighborhood traversal."""

    def __init__(self, units: Iterable[CodeUnit], edges: Iterable[CodeEdge] = ()):
        """Builds the forward and backward adjacency tables, keeping only
        relationships whose two endpoints both exist in this index. An edge
        pointing at something that is not indexed is dropped rather than
        kept as a dangling reference.
        """
        self.units = {unit.id: unit for unit in units}
        self.edges = sorted(set(edges), key=lambda edge: (edge.source, edge.kind, edge.target))
        self._out: dict[str, list[CodeEdge]] = defaultdict(list)
        self._in: dict[str, list[CodeEdge]] = defaultdict(list)
        for edge in self.edges:
            if edge.source in self.units and edge.target in self.units:
                self._out[edge.source].append(edge)
                self._in[edge.target].append(edge)

    def neighbors(self, unit_id: str, hops: int = 1, direction: str = "both") -> list[tuple[CodeUnit, list[str]]]:
        """Walks outward from one unit to find related code within a hop limit,
        following relationships forward, backward or both. Each unit is
        visited once, and every result comes back with the full chain of
        edges that reached it so the connection can be checked rather than
        trusted.
        """
        if unit_id not in self.units or hops <= 0:
            return []
        directions = {"out"} if direction == "out" else {"in"} if direction == "in" else {"out", "in"}
        queue: deque[tuple[str, int, list[str]]] = deque([(unit_id, 0, [unit_id])])
        seen = {unit_id}
        found: list[tuple[CodeUnit, list[str]]] = []
        while queue:
            current, distance, path = queue.popleft()
            if distance >= hops:
                continue
            edges: list[CodeEdge] = []
            if "out" in directions:
                edges.extend(self._out.get(current, []))
            if "in" in directions:
                edges.extend(self._in.get(current, []))
            for edge in edges:
                target = edge.target if edge.source == current else edge.source
                if target in seen:
                    continue
                seen.add(target)
                edge_text = f"{edge.kind}:{edge.source}->{edge.target}"
                next_path = path + [edge_text, target]
                found.append((self.units[target], next_path))
                queue.append((target, distance + 1, next_path))
        return found

    def to_dict(self) -> dict[str, object]:
        """Serialises the whole relationship graph for storage inside the
        index.
        """
        return {"edges": [edge.to_dict() for edge in self.edges]}


def _name_indexes(units: Iterable[CodeUnit]):
    """Builds two lookup tables used to resolve references: identifier to the
    units declaring it, and module filename to the units it defines. The
    second is what lets a reference be recognised as belonging to this
    repository rather than to an installed library.
    """
    by_name: dict[str, list[str]] = defaultdict(list)
    by_module: dict[str, list[str]] = defaultdict(list)
    for unit in units:
        by_name[unit.name].append(unit.id)
        if unit.qualified_name != unit.name:
            by_name[unit.qualified_name].append(unit.id)
        module = unit.path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        by_module[module].append(unit.id)
    return by_name, by_module


def _call_targets(call: str, by_name: dict[str, list[str]], local_modules: set[str], unit: CodeUnit, unit_by_id: dict[str, CodeUnit]) -> list[str]:
    """Resolve a recorded call to local unit ids, guessing only where allowed.

    An exact match on the text the parser recorded always wins. Falling back to
    the last dotted segment is a guess, and an unrestricted guess is how
    `os.path.join` acquired a `calls` edge to an unrelated local `join` -- while
    this module's own docstring promises that unresolved calls are omitted
    rather than guessed. The fallback now requires the head of the dotted path
    to be attributable to this repository: `self`/`cls`, or a module some file
    here actually defines. `os`, `json`, `requests` and every other foreign
    prefix resolve to nothing, as documented.
    """
    exact = by_name.get(call)
    if exact:
        return list(exact)
    if "." not in call:
        return []
    head = call.split(".", 1)[0]
    leaf = call.rsplit(".", 1)[-1]
    if head in {"self", "cls"}:
        # A receiver call names a sibling defined alongside this unit.
        return [target for target in by_name.get(leaf, []) if unit_by_id[target].path == unit.path]
    if head in local_modules:
        return list(by_name.get(leaf, []))
    return []


def build_graph(units: Iterable[CodeUnit], max_edges_per_unit: int = 64) -> CodeGraph:
    """Derives the whole relationship graph from parsed units: containment from
    declared parents, calls from recorded references, imports from module
    names. Every edge is capped and conservative. An ambiguous reference
    that could mean several units produces no edge at all, a per-unit budget
    stops one heavily-connected function from flooding the graph, and a
    module reference only becomes an edge when the target has a small
    unambiguous surface. Omitting an uncertain relationship is preferred to
    inventing one.
    """
    units = list(units)
    unit_by_id = {unit.id: unit for unit in units}
    by_name, by_module = _name_indexes(units)
    local_modules = set(by_module)
    edges: set[CodeEdge] = set()
    for unit in units:
        budget = max(1, max_edges_per_unit)
        if unit.parent:
            parent_ids = by_name.get(unit.parent, [])
            same_file_parents = [target for target in parent_ids if unit_by_id[target].path == unit.path]
            resolved_parents = same_file_parents if len(same_file_parents) == 1 else parent_ids if len(parent_ids) == 1 else []
            for parent_id in resolved_parents:
                edges.add(CodeEdge(parent_id, unit.id, "contains", unit.qualified_name))
                budget -= 1
        for call in unit.calls:
            if budget <= 0:
                break
            targets = _call_targets(call, by_name, local_modules, unit, unit_by_id)
            same_file = [target for target in targets if target != unit.id and unit_by_id[target].path == unit.path]
            resolved = same_file if len(same_file) == 1 else targets if len(targets) == 1 else []
            for target in resolved:
                if target != unit.id:
                    edges.add(CodeEdge(unit.id, target, "calls", call))
                    budget -= 1
        for imported in unit.imports:
            if budget <= 0:
                break
            module = imported.rsplit(".", 1)[-1]
            module_targets = by_module.get(module, [])
            # A module import is a coarse relationship. Only materialize it
            # when the target module has a small, unambiguous surface.
            module_paths = {unit_by_id[target].path for target in module_targets}
            resolved_module = module_targets if len(module_targets) <= 3 and len(module_paths) == 1 else []
            for target in resolved_module:
                if target != unit.id:
                    edges.add(CodeEdge(unit.id, target, "imports", imported))
                    budget -= 1
                    if budget <= 0:
                        break
    return CodeGraph(units, edges)


def graph_from_dict(units: Iterable[CodeUnit], data: dict[str, object] | None) -> CodeGraph:
    """Rebuilds the relationship graph from what an index stored, skipping any
    entry whose shape it does not recognise. A scanned repository can ship
    its own index file, so a malformed entry must be ignored rather than
    trusted.
    """
    raw_edges = (data or {}).get("edges", [])
    edges: list[CodeEdge] = []
    for edge in raw_edges if isinstance(raw_edges, list) else []:
        if not isinstance(edge, dict):
            continue
        try:
            edges.append(CodeEdge(**edge))
        except (TypeError, ValueError):
            continue
    return CodeGraph(units, edges)


def graph_search(
    units: list[CodeUnit],
    query: str,
    limit: int = 8,
    hops: int = 1,
    graph: CodeGraph | None = None,
    search_index: SearchIndex | None = None,
    vector_weight: float = DEFAULT_VECTOR_WEIGHT,
    vector_recall: int = DEFAULT_VECTOR_RECALL,
) -> list[SearchResult]:
    """Search seeds and add bounded graph neighbors with explicit evidence."""
    if limit <= 0:
        return []
    hops = min(3, max(0, hops))
    graph = graph or build_graph(units)
    seeds = search(units, query, max(limit * 2, 8), search_index=search_index, vector_weight=vector_weight, vector_recall=vector_recall)
    ranked: dict[str, SearchResult] = {seed.unit.id: seed for seed in seeds}
    if hops <= 0:
        return seeds[:limit]
    for seed in seeds:
        for neighbor, path in graph.neighbors(seed.unit.id, hops=hops, direction="both"):
            weights = {"calls": 0.7, "contains": 0.5, "imports": 0.3}
            propagated = seed.score
            for edge_text in path[1::2]:
                propagated *= weights.get(edge_text.split(":", 1)[0], 0.4)
            current = ranked.get(neighbor.id)
            evidence = ["graph:" + " -> ".join(path)]
            if current is None or propagated > current.score:
                ranked[neighbor.id] = SearchResult(neighbor, propagated, [], evidence)
            elif evidence[0] not in current.evidence:
                current.evidence.extend(evidence)
    return sorted(ranked.values(), key=lambda result: (-result.score, result.unit.id))[:limit]
