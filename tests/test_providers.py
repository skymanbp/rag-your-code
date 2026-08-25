"""Guards for vectors computed by a model somebody else runs.

Everything here is offline. The endpoint is a standard-library HTTP server on
loopback, which is also the shape this feature is most meant to serve: a model
server on the same machine keeps the project's original promise, that a
private repository can be indexed with the network switched off.

The first test is the load-bearing one. Every other property in this file
matters only if the default path still opens no socket at all.
"""

from __future__ import annotations

import json
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from ragyourcode import config as config_module
from ragyourcode.cli import main
from ragyourcode.embeddings import LocalEmbedder, RemoteEmbedder, embedder
from ragyourcode.indexer import build_units, read_index
from ragyourcode.providers import ProviderError, check_endpoint, embed_batch
from ragyourcode.search import build_search_index, search

# Above embedding.dimensions' floor of 32, because a width the settings
# refuse would fail the configuration check before any provider ran.
WIDTH = 32

# An obvious fixture value, shaped like a key only so the test can assert it
# never reaches an error message. Nothing authenticates against it.
PLACEHOLDER_KEY = "example-key-not-a-real-credential"


def _repo(root: Path) -> Path:
    (root / "billing.py").write_text(
        'def retry_charge(card):\n    """Charge the card again."""\n    return card\n',
        encoding="utf-8",
    )
    (root / "ledger.py").write_text(
        'def settle(entry):\n    """Write the entry to the book."""\n    return entry\n',
        encoding="utf-8",
    )
    return root


def _configure(root: Path, endpoint: str, **overrides: object) -> None:
    values: dict[str, object] = {
        "provider": "openai-compatible",
        "endpoint": endpoint,
        "model": "stub-embed",
        "dimensions": WIDTH,
        "api_key_env": "",
    }
    values.update(overrides)
    lines = ["[embedding]"]
    lines.extend(f'{name} = "{value}"' if isinstance(value, str) else f"{name} = {value}" for name, value in values.items())
    (root / "rag-your-code.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")


class _Stub:
    """An OpenAI-compatible embeddings endpoint that answers deterministically.

    Vectors are a function of the text, so two runs over unchanged sources
    produce identical output and a test can tell reuse from recomputation.
    """

    def __init__(self, *, status: int = 200, body: object = None, fail_times: int = 0, shuffle: bool = False, width: int = WIDTH) -> None:
        self.requests: list[dict] = []
        self.authorizations: list[str | None] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                return  # the default handler logs every request to stderr, which is pure test noise

            def do_POST(self):  # noqa: N802 -- the method name BaseHTTPRequestHandler dispatches on, not ours to choose
                length = int(self.headers.get("Content-Length", "0"))
                request = json.loads(self.rfile.read(length).decode("utf-8"))
                outer.requests.append(request)
                outer.authorizations.append(self.headers.get("Authorization"))
                if len(outer.requests) <= fail_times:
                    self.send_response(500)
                    self.end_headers()
                    self.wfile.write(b'{"error":"try again"}')
                    return
                if status != 200:
                    self.send_response(status)
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": "refused"}).encode("utf-8"))
                    return
                rows = [
                    {"index": position, "embedding": _Stub.vector(text, width)}
                    for position, text in enumerate(request["input"])
                ]
                if shuffle:
                    rows.reverse()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(body if body is not None else {"data": rows}).encode("utf-8"))

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    @staticmethod
    def vector(text: str, width: int = WIDTH) -> list[float]:
        return [((abs(hash((text, slot))) % 1000) / 1000.0) for slot in range(width)]

    @property
    def url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}/v1/embeddings"

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()


@pytest.fixture
def stub():
    servers: list[_Stub] = []

    def make(**kwargs) -> _Stub:
        server = _Stub(**kwargs)
        servers.append(server)
        return server

    yield make
    for server in servers:
        server.close()


def test_the_default_provider_opens_no_socket(tmp_path: Path, monkeypatch):
    """The property everything else here is allowed to exist on top of.

    A private repository, indexed and searched with the network switched off,
    is what this project is for. Any request at all on the default path is a
    defect, so the transport is made to raise rather than trusted to be idle.
    """
    def refuse(*args, **kwargs):
        raise AssertionError("the default provider must not reach the network")

    monkeypatch.setattr(urllib.request, "urlopen", refuse)
    assert main(["index", str(_repo(tmp_path))]) == 0
    assert main(["search", "charge the card again", "--root", str(tmp_path)]) == 0


def test_vectors_come_from_the_endpoint_and_the_index_records_it(tmp_path: Path, stub):
    server = stub()
    _configure(_repo(tmp_path), server.url)
    assert main(["index", str(tmp_path)]) == 0
    payload, units = read_index(tmp_path / ".rag-your-code" / "index.json")
    assert payload["embedding"] == {"provider": "openai-compatible", "version": 1, "dimensions": WIDTH, "model": "stub-embed"}
    assert all(len(unit.vector) == WIDTH for unit in units)
    # One request for both units, not one each: a round trip per unit is what
    # makes a real repository unusable.
    assert len(server.requests) == 1
    assert len(server.requests[0]["input"]) == len(units)
    assert server.requests[0]["model"] == "stub-embed"


def test_an_unchanged_repository_costs_no_request(tmp_path: Path, stub):
    server = stub()
    _configure(_repo(tmp_path), server.url)
    assert main(["index", str(tmp_path)]) == 0
    before = len(server.requests)
    assert main(["index", str(tmp_path)]) == 0
    assert len(server.requests) == before, "reused vectors must not be re-fetched"


def test_switching_model_discards_the_old_vectors(tmp_path: Path, stub):
    """Two models behind one endpoint are two vector spaces.

    A cosine across them is not a weak signal but a meaningless one, and
    ranking would act on it regardless -- so the model name is part of what an
    index records and a change to it forces the vectors to be rebuilt.
    """
    server = stub()
    _configure(_repo(tmp_path), server.url)
    assert main(["index", str(tmp_path)]) == 0
    first = len(server.requests)
    settings = tmp_path / "rag-your-code.toml"
    settings.write_text(settings.read_text(encoding="utf-8").replace("stub-embed", "stub-embed-v2"), encoding="utf-8")
    assert main(["index", str(tmp_path)]) == 0
    assert len(server.requests) > first
    payload, _ = read_index(tmp_path / ".rag-your-code" / "index.json")
    assert payload["embedding"]["model"] == "stub-embed-v2"


def test_a_width_the_settings_do_not_expect_is_refused_with_both_numbers(tmp_path: Path, stub):
    """A setting silently overridden is a setting that never worked."""
    server = stub(width=WIDTH + 5)
    _configure(_repo(tmp_path), server.url)
    with pytest.raises(ProviderError) as caught:
        build_units(tmp_path, cfg=config_module.load(tmp_path))
    assert str(WIDTH + 5) in str(caught.value) and str(WIDTH) in str(caught.value)


def test_a_rejected_credential_is_not_retried(stub):
    """The endpoint will give the same answer however many times it is asked,
    and on a metered service each attempt costs the caller something.
    """
    server = stub(status=401)
    with pytest.raises(ProviderError) as caught:
        embed_batch(["one"], endpoint=server.url, model="m", api_key="", dimensions=WIDTH, retries=5)
    assert len(server.requests) == 1
    assert "401" in str(caught.value)


def test_a_transient_failure_is_retried_then_succeeds(stub):
    slept: list[float] = []
    server = stub(fail_times=2)
    vectors = embed_batch(
        ["one"], endpoint=server.url, model="m", api_key="", dimensions=WIDTH, retries=3, sleep=slept.append
    )
    assert len(vectors) == 1 and len(server.requests) == 3
    assert slept == [1, 2], "backoff has to grow, or a rate limit is met with a stampede"


def test_the_attempts_run_out_rather_than_falling_back(stub):
    """A build either uses one vector space or does not finish.

    Falling back to the local hash would leave an index whose vectors come
    from two incompatible spaces -- and ranking would act on the meaningless
    cosine between them with full confidence.
    """
    server = stub(fail_times=99)
    with pytest.raises(ProviderError):
        embed_batch(["one"], endpoint=server.url, model="m", api_key="", dimensions=WIDTH, retries=1, sleep=lambda _: None)


def test_a_credential_is_never_sent_in_cleartext_to_a_remote_host():
    """Localhost over plain HTTP is the intended local setup and is allowed."""
    check_endpoint("http://localhost:11434/v1/embeddings", has_key=True)
    check_endpoint("http://127.0.0.1:1234/v1/embeddings", has_key=True)
    check_endpoint("http://api.example.com/v1/embeddings", has_key=False)
    with pytest.raises(ProviderError) as caught:
        check_endpoint("http://api.example.com/v1/embeddings", has_key=True)
    assert "cleartext" in str(caught.value)
    with pytest.raises(ProviderError):
        check_endpoint("ftp://example.com/embeddings", has_key=False)


def test_a_failure_report_never_repeats_the_key(stub):
    server = stub(status=403)
    with pytest.raises(ProviderError) as caught:
        embed_batch(
            ["one"],
            endpoint=server.url.replace("http://127.0.0.1", "http://localhost"),
            model="m",
            api_key=PLACEHOLDER_KEY,
            dimensions=WIDTH,
            retries=0,
        )
    assert PLACEHOLDER_KEY not in str(caught.value)
    assert server.authorizations[0] == f"Bearer {PLACEHOLDER_KEY}", "the key still has to reach the endpoint"


def test_rows_are_ordered_by_the_index_they_report(stub):
    """The response schema promises an index, not a sequence."""
    server = stub(shuffle=True)
    vectors = embed_batch(["alpha", "beta"], endpoint=server.url, model="m", api_key="", dimensions=WIDTH)
    assert vectors == [_Stub.vector("alpha"), _Stub.vector("beta")]


def test_a_response_that_is_not_an_embeddings_reply_is_named_as_such(stub):
    server = stub(body={"choices": []})
    with pytest.raises(ProviderError) as caught:
        embed_batch(["one"], endpoint=server.url, model="m", api_key="", dimensions=WIDTH)
    assert "OpenAI-compatible" in str(caught.value)


def test_an_incomplete_configuration_says_which_setting_is_missing(tmp_path: Path):
    (tmp_path / "rag-your-code.toml").write_text('[embedding]\nprovider = "openai-compatible"\n', encoding="utf-8")
    with pytest.raises(ProviderError) as caught:
        embedder(config_module.load(tmp_path))
    assert "embedding.endpoint" in str(caught.value)


def test_the_key_is_read_from_the_environment_not_the_settings_file(tmp_path: Path, monkeypatch):
    """Every other setting is meant to be committed. This one is the opposite.

    The file names the variable; the variable holds the credential. That is
    why this is not the environment layer the configuration module
    deliberately does not have -- it is one secret kept out of a shared file.
    """
    monkeypatch.setenv("RYC_TEST_KEY", PLACEHOLDER_KEY)
    _configure(tmp_path, "https://example.invalid/v1/embeddings", api_key_env="RYC_TEST_KEY")
    resolved = embedder(config_module.load(tmp_path))
    assert isinstance(resolved, RemoteEmbedder)
    assert PLACEHOLDER_KEY not in (tmp_path / "rag-your-code.toml").read_text(encoding="utf-8")


def test_only_a_semantic_embedder_may_add_candidates(tmp_path: Path):
    """The one thing a vector can do that reordering cannot -- and the one
    thing the feature hash measurably must not be allowed to do.
    """
    units = build_units(_repo(tmp_path))
    index = build_search_index(units, LocalEmbedder(len(units[0].vector)))
    assert index.embedder.semantic is False
    reached = search(units, "settle the entry", limit=5, search_index=index, vector_recall=50)
    assert reached, "the fixture must retrieve something for the comparison to mean anything"
    assert all(result.matched_terms for result in reached), "the hash must not add candidates it only guessed at"


class _Meaning(_Stub):
    """A stub whose vectors carry meaning by hand.

    `quiesce` sits near `settle` and far from `charge`, though it shares no
    character with either. No local scheme can produce that, which is why the
    property it enables cannot be tested with the feature hash.
    """

    WORDS = {"settle": (1.0, 0.0), "quiesce": (0.98, 0.2), "charge": (0.0, 1.0), "card": (0.0, 1.0)}

    @staticmethod
    def vector(text: str, width: int = WIDTH) -> list[float]:
        across = down = 0.0
        for word, (right, up) in _Meaning.WORDS.items():
            if word in text.lower():
                across += right
                down += up
        length = (across * across + down * down) ** 0.5 or 1.0
        return [across / length, down / length] + [0.0] * (width - 2)


def test_semantics_can_make_a_unit_retrievable_that_the_words_never_reach(tmp_path: Path, monkeypatch):
    """The whole reason a semantic provider is allowed to widen the candidate set.

    `settle` shares no token with the query, so no weighting can rank it: it
    is not a candidate at all. `card` gives `charge` a lexical hit, which is
    what keeps the existing no-overlap fallback from firing and makes this the
    case recall actually governs. Six of thirty-five questions on the foreign
    ruler are exactly this shape.
    """
    monkeypatch.setattr(_Stub, "vector", _Meaning.vector)
    server = _Stub()
    try:
        (tmp_path / "a.py").write_text("def settle(entry):\n    return entry\n", encoding="utf-8")
        (tmp_path / "b.py").write_text("def charge(card):\n    return card\n", encoding="utf-8")
        _configure(tmp_path, server.url)
        cfg = config_module.load(tmp_path)
        resolved = embedder(cfg)
        units = build_units(tmp_path, cfg=cfg, embed_with=resolved)
        index = build_search_index(units, resolved)

        without = search(units, "quiesce the card", limit=3, search_index=index, vector_weight=0.9, vector_recall=0)
        assert [result.unit.name for result in without] == ["charge"]

        with_recall = search(units, "quiesce the card", limit=3, search_index=index, vector_weight=0.9, vector_recall=50)
        names = [result.unit.name for result in with_recall]
        assert names == ["charge", "settle"], names
        # Found by similarity alone, and still ranked under the lexical hit:
        # semantics adds a floor, it does not take the ranking over.
        assert with_recall[1].matched_terms == []
        assert with_recall[1].score < with_recall[0].score
    finally:
        server.close()
