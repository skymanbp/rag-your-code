"""Vectors from a model somebody else runs, over an OpenAI-compatible endpoint.

One request shape reaches both a hosted service and a model server on
localhost, which is why it is the only shape implemented: `ollama`, LM Studio,
vLLM and llama.cpp all speak it, and so do OpenAI, Voyage, Together and Azure.
The local case matters most here, because it is the one that keeps this
project's original promise -- the source never leaves the machine.

Nothing in this module runs unless `embedding.provider` says so. The default
provider opens no socket, and that is the property everything else is built
on: an index of a private repository, reproducible, on a machine with the
network switched off.

Only the standard library is used, because `dependencies = []` is a design
constraint rather than an accident.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request

# Errors the endpoint will give the same answer to however many times it is
# asked: a wrong key, a wrong model name, a malformed request. Retrying them
# wastes the caller's time and, on a metered endpoint, their money.
PERMANENT_STATUSES = frozenset({400, 401, 403, 404, 405, 422})

# Hosts where cleartext HTTP cannot put a credential on a network. Anything
# else over `http://` gets the request refused rather than the key sent in the
# open -- a local model server is the reason plain HTTP is allowed at all.
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "[::1]"})


class ProviderError(RuntimeError):
    """An embeddings request that cannot be completed as configured.

    Raised rather than absorbed. Falling back to the local hash would leave an
    index whose vectors come from two incompatible spaces, and a cosine
    between them is not a weak signal -- it is a meaningless one that ranking
    would nonetheless act on.
    """


def _describe_status(status: int, body: str) -> str:
    """A failure a user can act on, with nothing sensitive in it.

    The request carried a credential; the report of the request must not. Only
    the status and the endpoint's own message are repeated, truncated, and the
    Authorization header is never part of either.
    """
    detail = body.strip().replace("\n", " ")[:300]
    if status == 401 or status == 403:
        return f"HTTP {status}: the endpoint rejected the credential. {detail}"
    if status == 404:
        return f"HTTP {status}: no embeddings endpoint at that URL. {detail}"
    if status == 429:
        return f"HTTP {status}: rate limited. {detail}"
    return f"HTTP {status}: {detail}"


def check_endpoint(endpoint: str, has_key: bool) -> None:
    """Refuse a configuration that would put a key on the wire in cleartext.

    A model server on localhost over plain HTTP is the intended local setup and
    is allowed. The same URL pointing anywhere else means the credential
    crosses a network unencrypted, which is a leak rather than a preference.
    """
    parts = urllib.parse.urlsplit(endpoint)
    if parts.scheme not in {"http", "https"}:
        raise ProviderError(f"embedding.endpoint must be an http or https URL, not {parts.scheme or 'a bare path'!r}")
    if not parts.hostname:
        raise ProviderError("embedding.endpoint has no host")
    if parts.scheme == "http" and has_key and parts.hostname not in LOOPBACK_HOSTS:
        raise ProviderError(
            f"refusing to send a credential in cleartext to {parts.hostname}. "
            "Use https, or point embedding.endpoint at a local model server."
        )


def embed_batch(
    texts: list[str],
    *,
    endpoint: str,
    model: str,
    api_key: str,
    dimensions: int,
    timeout: int = 60,
    retries: int = 3,
    sleep=time.sleep,
) -> list[list[float]]:
    """Vectors for one batch of texts, in the order they were given.

    Results are reordered by the index the endpoint reports rather than
    trusting the order they arrive in, because the response schema promises an
    index and not a sequence.

    Transport failures and rate limits are retried with exponential backoff;
    a rejected key or an unknown model is not, because the answer will not
    change. When the attempts run out the exception propagates: the caller's
    contract is that a build either uses one vector space or does not finish.
    """
    if not texts:
        return []
    check_endpoint(endpoint, bool(api_key))
    payload = json.dumps({"model": model, "input": texts}).encode("utf-8")
    headers = {"Content-Type": "application/json", "User-Agent": "rag-your-code"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    last: str = ""
    for attempt in range(retries + 1):
        request = urllib.request.Request(endpoint, data=payload, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
            return _vectors_from(body, len(texts), dimensions)
        except urllib.error.HTTPError as error:
            detail = ""
            try:
                detail = error.read().decode("utf-8", "replace")
            except OSError:
                # The body is a courtesy; the status is the fact. A connection
                # that died before the error body arrived still has to report
                # the status rather than turn into a different exception.
                detail = ""
            last = _describe_status(error.code, detail)
            if error.code in PERMANENT_STATUSES:
                raise ProviderError(last) from error
        except urllib.error.URLError as error:
            last = f"could not reach {urllib.parse.urlsplit(endpoint).netloc}: {error.reason}"
        except (TimeoutError, OSError) as error:
            last = f"transport failure: {error}"
        except json.JSONDecodeError as error:
            raise ProviderError(f"the endpoint returned something that is not JSON: {error}") from error
        if attempt < retries:
            sleep(2 ** attempt)
    raise ProviderError(f"{retries + 1} attempts failed. Last: {last}")


def _vectors_from(body: object, expected: int, dimensions: int) -> list[list[float]]:
    """Read the vectors out of a response, refusing anything unusable.

    Width is checked rather than adopted. `embedding.dimensions` decides the
    space an index lives in, and a setting quietly overridden by whatever a
    model happened to return is indistinguishable from a setting that never
    worked -- so a mismatch names both numbers and stops.
    """
    if not isinstance(body, dict) or not isinstance(body.get("data"), list):
        raise ProviderError("the response has no `data` array; is this an OpenAI-compatible embeddings endpoint?")
    rows = body["data"]
    if len(rows) != expected:
        raise ProviderError(f"asked for {expected} vectors and got {len(rows)}")
    ordered: list[list[float] | None] = [None] * expected
    for position, row in enumerate(rows):
        if not isinstance(row, dict) or not isinstance(row.get("embedding"), list):
            raise ProviderError("a row in `data` carries no `embedding` array")
        index = row.get("index", position)
        if not isinstance(index, int) or not 0 <= index < expected:
            raise ProviderError(f"a row reports index {index!r}, which is not a position in this batch")
        vector = row["embedding"]
        if len(vector) != dimensions:
            raise ProviderError(
                f"the model returned {len(vector)}-dimension vectors and embedding.dimensions is {dimensions}. "
                f"Set embedding.dimensions to {len(vector)} and rebuild."
            )
        if any(not isinstance(value, (int, float)) or value != value for value in vector):
            raise ProviderError("a vector contains a non-numeric or NaN component")
        ordered[index] = [float(value) for value in vector]
    if any(vector is None for vector in ordered):
        raise ProviderError("the response skipped a position in the batch")
    return [vector for vector in ordered if vector is not None]
