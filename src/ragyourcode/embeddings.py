"""Dependency-free deterministic embeddings.

The default hasher is deliberately local and reproducible. It is useful for
small/medium repositories and can later be replaced by an API or sentence
transformer without changing the index schema.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Sequence

TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|[\u4e00-\u9fff]+|\d+")
CJK_RE = re.compile(r"^[\u4e00-\u9fff]+$")
DEFAULT_DIMENSIONS = 384
EMBEDDING_PROVIDER = "signed-feature-hash"
EMBEDDING_VERSION = 1


def embedding_metadata(dimensions: int = DEFAULT_DIMENSIONS) -> dict[str, object]:
    """Reports which embedding scheme and version produced an index, and how
    wide its vectors are. Stored inside the index so vectors built by an
    incompatible scheme are detected and discarded instead of being silently
    mixed in.
    """
    return {"provider": EMBEDDING_PROVIDER, "version": EMBEDDING_VERSION, "dimensions": dimensions}


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
