from pathlib import Path

from ragyourcode.parser import parse_file


def test_generic_parser_keeps_last_line_without_trailing_newline(tmp_path: Path):
    source = tmp_path / "service.js"
    source.write_text("function first() {\n  return 1;\n}\nfunction last() {\n  return 2;\n}", encoding="utf-8")
    units = parse_file(source, tmp_path)
    assert [unit.name for unit in units] == ["first", "last"]
    assert units[-1].end_line == 6
    assert "return 2" in units[-1].source
