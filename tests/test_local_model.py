"""Guards for the one embedder that is both semantic and offline.

None of this installs `sentence-transformers`. The package is an optional extra
and CI must stay able to prove the *default* install never needs it, so the
model is stubbed into `sys.modules` exactly the way the remote provider is
served by a loopback HTTP stub: the contract under test is this project's side
of the seam, not somebody else's library.

The load-bearing test is the last one. Every other property here matters only
while a default install still imports nothing.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from ragyourcode import config as config_module
from ragyourcode.embeddings import LocalEmbedder, LocalModelEmbedder, embedder
from ragyourcode.providers import ProviderError

MODEL = "stub/multilingual-mini"
# 32 rather than something smaller because `embedding.dimensions` refuses to go
# below it, and a fixture that cannot be written into a settings file is testing
# a path no user can take.
WIDTH = 32


class _StubModel:
    """A model whose vectors are deliberately not a function of the tokens.

    A stub that hashed its input would reproduce the very thing the feature
    hash already does, and every assertion about "semantic" would then pass for
    the wrong reason.
    """

    def __init__(self, name: str, width: int = WIDTH) -> None:
        self.name, self.width, self.calls = name, width, []

    def get_sentence_embedding_dimension(self) -> int:
        return self.width

    def encode(self, texts, normalize_embeddings=False):
        del normalize_embeddings  # the stub returns unit vectors already
        self.calls.append(list(texts))
        rows = []
        for position, _ in enumerate(texts):
            row = [0.0] * self.width
            row[position % self.width] = 1.0
            rows.append(row)
        return rows


@pytest.fixture
def stub_package(monkeypatch):
    """Installs a fake `sentence_transformers` for the duration of one test."""
    import types

    created: list[_StubModel] = []
    module = types.ModuleType("sentence_transformers")

    def factory(name, *args, **kwargs):
        del args, kwargs
        model = _StubModel(name)
        created.append(model)
        return model

    module.SentenceTransformer = factory
    monkeypatch.setitem(sys.modules, "sentence_transformers", module)
    return created


def _cfg(tmp_path: Path, **overrides):
    """Written to the settings file rather than poked onto the object, so what
    is under test is the same path a user's `rag-your-code.toml` takes.
    """
    values: dict[str, object] = {
        "provider": "sentence-transformers",
        "model": MODEL,
        "dimensions": WIDTH,
        "batch": 2,
    }
    values.update({path.split(".", 1)[1]: value for path, value in overrides.items()})
    lines = ["[embedding]"]
    lines.extend(
        f'{name} = "{value}"' if isinstance(value, str) else f"{name} = {value}"
        for name, value in values.items()
    )
    (tmp_path / "rag-your-code.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return config_module.load(tmp_path)


def test_selecting_the_model_without_installing_it_says_how_to_install_it(tmp_path, monkeypatch):
    """A missing optional dependency is a setup problem, and the message has to
    be the fix rather than a traceback out of an import somebody never made.
    """
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)
    with pytest.raises(ProviderError) as raised:
        embedder(_cfg(tmp_path))
    assert "pip install rag-your-code[sentence-transformers]" in str(raised.value)


def test_a_width_that_disagrees_with_the_model_is_refused_at_build_time(tmp_path, stub_package):
    """`cosine` returns 0.0 when two widths disagree rather than raising, which
    is right for an index built under an older setting and wrong as a way to
    discover that this one is misconfigured: the vector half would simply be
    absent, silently, and the ranking would look merely mediocre.
    """
    del stub_package
    with pytest.raises(ProviderError) as raised:
        embedder(_cfg(tmp_path, **{"embedding.dimensions": WIDTH + 1}))
    assert "reindex" in str(raised.value)


def test_the_model_name_is_required_and_named_in_the_message(tmp_path, stub_package):
    del stub_package
    with pytest.raises(ProviderError) as raised:
        embedder(_cfg(tmp_path, **{"embedding.model": ""}))
    assert "embedding.model" in str(raised.value)


def test_the_index_records_which_model_produced_it(tmp_path, stub_package):
    """Two models behind one setting are two vector spaces, and a cosine across
    them is a number with no meaning that ranking would act on anyway.
    """
    del stub_package
    made = embedder(_cfg(tmp_path))
    assert made.metadata == {
        "provider": "sentence-transformers",
        "version": 1,
        "dimensions": WIDTH,
        "model": MODEL,
    }


def test_it_declares_itself_semantic_and_the_hash_does_not(tmp_path, stub_package):
    """`semantic` is what gates `search.vector_recall`, so it decides whether a
    vector may add candidates or only reorder them. Measured under the hash,
    the same widening was harmful; this flag is the whole difference.
    """
    del stub_package
    assert embedder(_cfg(tmp_path)).semantic is True
    assert LocalEmbedder(WIDTH).semantic is False


def test_text_is_sent_in_batches_rather_than_one_call_per_unit(tmp_path, stub_package):
    """Eleven hundred units one call at a time is not a slower version of the
    same thing; it is the difference between usable and not.
    """
    made = embedder(_cfg(tmp_path))
    vectors = made.many([f"unit {index}" for index in range(5)])
    assert len(vectors) == 5 and all(len(row) == WIDTH for row in vectors)
    assert [len(call) for call in stub_package[0].calls] == [2, 2, 1]


def test_a_default_install_never_imports_the_optional_package(tmp_path, monkeypatch):
    """The property everything else here is allowed to exist on top of.

    `dependencies = []` is the promise, and it is only true while the default
    provider reaches none of this code. The import is made to raise rather than
    trusted to be unused.
    """
    real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__

    def refuse(name, *args, **kwargs):
        if name.startswith("sentence_transformers"):
            raise AssertionError("the default provider must not import sentence-transformers")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", refuse)
    made = embedder(_cfg(tmp_path, **{"embedding.provider": "signed-feature-hash"}))
    assert isinstance(made, LocalEmbedder)
    assert len(made.one("charge the card again")) == WIDTH


def test_the_class_is_importable_without_the_package_being_installed():
    """Importing `ragyourcode.embeddings` must not need the extra, or the
    optional dependency would be a required one wearing a different label.
    """
    assert LocalModelEmbedder.semantic is True
