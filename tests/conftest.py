"""Fixtures shared by more than one test module."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def skewed_corpus():
    """Builds a repository where a few words reach every unit and one word
    reaches a single unit.

    This is the shape that tells the retrieval defects apart. It also exceeds
    the selective threshold's floor of 64 units, so the rare term exercises
    the path where the vector shortlist and the lexical candidate set
    disagree about who deserves a score.
    """

    def build(root: Path, count: int = 80) -> Path:
        for index in range(count):
            (root / f"mod_{index}.py").write_text(
                f"def handler_{index}(request, response):\n"
                '    """Handle request and return response."""\n'
                "    return response\n",
                encoding="utf-8",
            )
        (root / "special.py").write_text(
            "def retry_request_with_backoff(request, response):\n"
            '    """Retry a failed request and return response."""\n'
            "    return response\n",
            encoding="utf-8",
        )
        return root

    return build
