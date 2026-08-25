"""Dependency-free deterministic embeddings.

The default hasher is deliberately local and reproducible. It is useful for
small/medium repositories and can later be replaced by an API or sentence
transformer without changing the index schema.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
from collections.abc import Sequence

from .providers import ProviderError, check_endpoint, embed_batch

TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|[\u4e00-\u9fff]+|\d+")
CJK_RE = re.compile(r"^[\u4e00-\u9fff]+$")
DEFAULT_DIMENSIONS = 384
EMBEDDING_PROVIDER = "signed-feature-hash"
EMBEDDING_VERSION = 1


def embedding_metadata(dimensions: int = DEFAULT_DIMENSIONS, provider: str = EMBEDDING_PROVIDER, model: str = "") -> dict[str, object]:
    """Reports which embedding scheme, which model and which version produced
    an index, and how wide its vectors are. Stored inside the index so vectors
    built by an incompatible scheme are detected and discarded instead of
    being silently mixed in.

    The model name is part of this for the same reason the provider is: two
    models behind one endpoint occupy different vector spaces, and a cosine
    across them would be a number with no meaning that ranking would act on
    anyway.
    """
    return {"provider": provider, "version": EMBEDDING_VERSION, "dimensions": dimensions, "model": model}


def tokenize(text: str) -> list[str]:
    """Splits text into the lowercase terms that both indexing and querying
    match on: identifiers, numbers, and runs of Chinese characters. Chinese
    is additionally broken into overlapping two-character pieces, because
    whole-phrase matching would almost never hit; this is why a Chinese
    query can reach a unit whose indexed text contains Chinese.
    """
    tokens: list[str] = []
    for raw in TOKEN_RE.findall(text):
        token = raw.lower()
        tokens.append(token)
        if CJK_RE.fullmatch(token) and len(token) > 1:
            tokens.extend(token[index : index + 2] for index in range(len(token) - 1))
    return tokens


def _bucket(token: str, dimensions: int) -> int:
    """Hashes one term into a stable slot number using BLAKE2b, so the same
    word always lands in the same position on any machine and any run.
    Determinism is the point: it is what makes an index reproducible without
    a network or a model.
    """
    digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") % dimensions


def embed(text: str, dimensions: int = DEFAULT_DIMENSIONS) -> list[float]:
    """Return a normalized signed feature-hash vector."""
    if dimensions < 32:
        raise ValueError("dimensions must be at least 32")
    tokens = tokenize(text)
    vector = [0.0] * dimensions
    for token in tokens:
        index = _bucket(token, dimensions)
        sign = 1.0 if _bucket("sign:" + token, dimensions) % 2 else -1.0
        vector[index] += sign
    norm = math.sqrt(sum(value * value for value in vector))
    if norm:
        vector = [value / norm for value in vector]
    return vector


def cosine(left: Sequence[float], right: Sequence[float]) -> float:
    """Similarity between two already-normalised vectors, as a plain dot
    product. Returns zero rather than raising when either side is empty or
    the widths disagree, which is how an index whose vectors were built at a
    different width degrades quietly to word-overlap-only ranking instead of
    failing loudly.
    """
    if not left or not right or len(left) != len(right):
        return 0.0
    return sum(a * b for a, b in zip(left, right))


class LocalEmbedder:
    """The default: a signed feature hash, computed here, offline.

    `semantic` is False and that is the load-bearing fact about it. Cosine
    over these vectors measures shared tokens, so `sum two numbers` and `add a
    pair of integers` score exactly 0.0000 -- identical to `sum two numbers`
    against `delete the user database table`. Retrieval treats it as a
    tie-breaker among units the words already found, and nothing more.
    """

    semantic = False

    def __init__(self, dimensions: int = DEFAULT_DIMENSIONS) -> None:
        self.dimensions = dimensions
        self.provider = EMBEDDING_PROVIDER
        self.model = ""

    def one(self, text: str) -> list[float]:
        return embed(text, self.dimensions)

    def many(self, texts: list[str]) -> list[list[float]]:
        return [embed(text, self.dimensions) for text in texts]

    @property
    def metadata(self) -> dict[str, object]:
        return embedding_metadata(self.dimensions, self.provider, self.model)


class RemoteEmbedder:
    """Vectors from a model somebody else runs, over an OpenAI-compatible API.

    `semantic` is True, and that is what earns it the right to add candidates
    rather than only reorder them. Under the feature hash a cosine shortlist
    is noise and letting it widen the candidate set measurably hurt; with a
    trained model it is the only mechanism that can reach a unit sharing no
    word with the question -- six of thirty-five questions on the foreign
    ruler have no acceptable answer that shares a single token with the query.

    A request is made only when there is something to embed, so a repository
    whose vectors were all reused costs nothing.
    """

    semantic = True

    def __init__(self, *, endpoint: str, model: str, api_key: str, dimensions: int, batch: int = 64, timeout: int = 60, retries: int = 3) -> None:
        if not endpoint:
            raise ProviderError("embedding.provider is openai-compatible but embedding.endpoint is empty")
        if not model:
            raise ProviderError("embedding.provider is openai-compatible but embedding.model is empty")
        check_endpoint(endpoint, bool(api_key))
        self.endpoint, self.model, self.dimensions = endpoint, model, dimensions
        self.provider = "openai-compatible"
        self._key, self._batch, self._timeout, self._retries = api_key, batch, timeout, retries

    def one(self, text: str) -> list[float]:
        return self.many([text])[0]

    def many(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for start in range(0, len(texts), self._batch):
            out.extend(
                embed_batch(
                    texts[start : start + self._batch],
                    endpoint=self.endpoint,
                    model=self.model,
                    api_key=self._key,
                    dimensions=self.dimensions,
                    timeout=self._timeout,
                    retries=self._retries,
                )
            )
        return out

    @property
    def metadata(self) -> dict[str, object]:
        return embedding_metadata(self.dimensions, self.provider, self.model)


class LocalModelEmbedder:
    """A trained model, run here, over `sentence-transformers`.

    `semantic` is True and it is the only embedder for which that is true
    without a network. What it buys is exactly what the feature hash cannot
    have, and the reason is not a defect in the hash: a signed hash of a unit's
    tokens is a term-frequency cosine over the same words the lexical half
    already ranks with rarity weighting, field weights and saturation applied.
    Measured on this repository and one other, its cosine correlates +0.45 with
    the BM25F score, so it does carry variance of its own -- drawn from words
    counted equally, which is precisely the part rarity weighting throws away.
    Independent noise, not independent signal, and ablating it moves a single
    question in either direction across three rulers.

    The same four pairs 0.4.0 used to show the hash carries no semantics, under
    this model: `retry a failed card charge` against `resend a payment after a
    transient error` scores 0.583 where the hash scores 0.298 and against an
    unrelated sentence 0.073; `计算两个数的和` against `sum two numbers` scores
    0.822 and `刷新索引` against `rebuild the index` 0.684, both of which the
    hash scores exactly 0.0000 -- identical to unrelated text, because zero
    shared tokens is zero either way.

    Optional by construction. The import happens here rather than at module
    level so that a repository that never selects it pays nothing, and
    `dependencies = []` stays true of the package a default install gets.
    """

    semantic = True

    def __init__(self, *, model: str, dimensions: int, batch: int = 64) -> None:
        if not model:
            raise ProviderError(
                "embedding.provider is sentence-transformers but embedding.model is empty; "
                "set it to a model name such as sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
            )
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise ProviderError(
                "embedding.provider is sentence-transformers but the package is not installed; "
                "run `pip install rag-your-code[sentence-transformers]`, or set "
                "`embedding.provider` back to signed-feature-hash"
            ) from exc
        self._model = SentenceTransformer(model)
        # Renamed between releases of the library, so both spellings are tried
        # rather than pinning a floor that would make the extra harder to
        # satisfy than the feature is worth.
        measure = getattr(self._model, "get_embedding_dimension", None) or self._model.get_sentence_embedding_dimension
        width = int(measure())
        if width != dimensions:
            # The alternative is an index whose recorded width disagrees with
            # its vectors, which `cosine` degrades quietly to zero rather than
            # reporting -- a silent loss of the whole vector half.
            raise ProviderError(
                f"{model} produces {width}-dimensional vectors but embedding.dimensions is "
                f"{dimensions}; run `rag-your-code config set embedding.dimensions {width}` and reindex"
            )
        self.model, self.dimensions, self._batch = model, dimensions, batch
        self.provider = "sentence-transformers"

    def one(self, text: str) -> list[float]:
        return self.many([text])[0]

    def many(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for start in range(0, len(texts), self._batch):
            encoded = self._model.encode(texts[start : start + self._batch], normalize_embeddings=True)
            out.extend([float(value) for value in row] for row in encoded)
        return out

    @property
    def metadata(self) -> dict[str, object]:
        return embedding_metadata(self.dimensions, self.provider, self.model)


def embedder(cfg) -> LocalEmbedder | LocalModelEmbedder | RemoteEmbedder:
    """The embedder a repository's settings ask for.

    The credential is read from the environment rather than from the settings
    file, and the file holds only the variable's name. Every other setting is
    meant to be committed so that everyone who clones can see what shaped the
    index; a credential is the one value with exactly the opposite
    requirement. That is why this is not the environment-variable layer the
    configuration module deliberately does not have -- it is one secret, kept
    out of a file that is meant to be shared.
    """
    provider = cfg["embedding.provider"]
    if provider == "sentence-transformers":
        return LocalModelEmbedder(
            model=cfg["embedding.model"],
            dimensions=cfg["embedding.dimensions"],
            batch=cfg["embedding.batch"],
        )
    if provider != "openai-compatible":
        return LocalEmbedder(cfg["embedding.dimensions"])
    variable = cfg["embedding.api_key_env"]
    key = os.environ.get(variable, "") if variable else ""
    return RemoteEmbedder(
        endpoint=cfg["embedding.endpoint"],
        model=cfg["embedding.model"],
        api_key=key,
        dimensions=cfg["embedding.dimensions"],
        batch=cfg["embedding.batch"],
        timeout=cfg["embedding.timeout"],
        retries=cfg["embedding.retries"],
    )
