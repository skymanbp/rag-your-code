# RAG Your Code

`rag-your-code` is a local, explainable retrieval-augmented generation (RAG) index for codebases and coding agents. It scans functions, methods, and classes; assigns stable serial numbers; generates descriptive sidecar comments; and embeds the combined description/source into a deterministic local vector index.

The first version has no network or model dependency. Its feature-hashing embedder is intentionally reproducible and can be replaced later with an OpenAI, Ollama, or sentence-transformer provider while keeping the same `CodeUnit` and JSON index contracts.

## Quick start

```powershell
python -m pip install -e .
rag-your-code index .
rag-your-code search "where are HTTP retries handled" --json
rag-your-code search "what calls the retry handler" --graph --hops 1 --json
rag-your-code annotate
```

The index and annotations are written under `.rag-your-code/`; source files are not modified. Search results include file/line locations, generated descriptions, matched terms, and source snippets. Use `--json` when feeding results to an agent.

For a large repository, prefer `rag-your-code index . --compact`. Subsequent
`index`/agent `refresh` operations reuse unchanged files and preserve global
serials; use `--full` only to discard the cache.

## Agent protocol

`rag-your-code agent --root PATH` reads JSON lines from stdin and writes JSON lines to stdout:

```json
{"action":"search","query":"database transaction rollback","limit":5}
{"action":"research","query":"trace payment retry behavior","max_steps":2}
{"action":"neighbors","id":"payments.py:4:retry_charge","hops":1}
{"action":"open","path":"payments.py","start_line":1,"end_line":80}
{"action":"refresh"}
{"action":"stats"}
```

This small protocol makes the index usable as a subprocess tool from Claude Code, Codex, or a custom agent. The bundled Claude plugin skill documents the recommended workflow: index at session start, retrieve narrowly, inspect returned source, and re-index after substantial changes.

## Design notes

- Python uses the standard-library AST, so nested functions, methods, calls, imports, signatures, and source line ranges are precise.
- JavaScript/TypeScript/Go/Rust/Java/C/C++ use a conservative declaration parser and remain searchable without third-party parsers.
- Retrieval combines lexical overlap and cosine similarity. Every result is explainable; no opaque model output is required to understand why it matched.
- Schema 2 supports incremental per-file reuse, repository-global serials, graph edges, and optional compact float32 vector storage (`index --compact`).
- GRAG expands bounded `calls`/`imports`/`contains` neighbors with edge-path evidence. ARAG exposes bounded, observable `research`, `neighbors`, `open`, and `refresh` actions.
- The generated `RAG[00001] ...` comments live in a sidecar Markdown file. This avoids silently rewriting a user's code while preserving the serialised semantic layer that gets embedded.

## Development

```powershell
pytest
```
