from pathlib import Path

import pytest

from ragyourcode.parser import parse_file


@pytest.mark.parametrize(
    ("filename", "source", "expected"),
    [
        ("sample.rb", "def greet(name)\n  name\nend\n", "greet"),
        ("sample.kt", "fun greet(name: String): String { return name }\n", "greet"),
        ("sample.swift", "func greet(name: String) -> String { return name }\n", "greet"),
        ("sample.php", "function greet($name) { return $name; }\n", "greet"),
        ("sample.go", "func greet(name string) string { return name }\n", "greet"),
        ("sample.rs", "fn greet(name: String) -> String { name }\n", "greet"),
        ("sample.sh", "function greet() { echo hi; }\n", "greet"),
        ("sample.cs", "public string Greet(string name) { return name; }\n", "Greet"),
    ],
)
def test_supported_language_declarations(tmp_path: Path, filename: str, source: str, expected: str):
    path = tmp_path / filename
    path.write_text(source, encoding="utf-8")
    units = parse_file(path, tmp_path)
    assert [unit.name for unit in units] == [expected]
