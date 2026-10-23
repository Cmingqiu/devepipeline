from __future__ import annotations

import io
import zipfile

import pytest

from app.core.config import get_settings
from app.core.exceptions import SemanticError
from app.services.skill_pack import parse_frontmatter, read_skill_zip


def make_zip(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return buffer.getvalue()


SKILL_MD = """---
name: code-review
description: 按团队规范做代码评审
---

# Code Review

1. 先看接口契约。
2. 再查 N+1。
""".encode()


def test_parses_skill_md_at_root() -> None:
    raw = make_zip({"SKILL.md": SKILL_MD, "scripts/check.sh": b"echo ok\n"})
    pack = read_skill_zip(raw)
    assert pack.name == "code-review"
    assert pack.description == "按团队规范做代码评审"
    assert pack.entry_path == "SKILL.md"
    paths = {item.path for item in pack.files}
    assert paths == {"SKILL.md", "scripts/check.sh"}
    assert next(item for item in pack.files if item.path == "SKILL.md").content.startswith("---")
    assert '"scripts/check.sh"' in pack.manifest


def test_accepts_single_top_level_directory() -> None:
    raw = make_zip({"my-skill/SKILL.md": SKILL_MD, "my-skill/lib/a.py": b"print(1)\n"})
    pack = read_skill_zip(raw)
    assert pack.name == "code-review"
    assert {item.path for item in pack.files} == {"SKILL.md", "lib/a.py"}


def test_binary_file_has_no_content() -> None:
    raw = make_zip({"SKILL.md": SKILL_MD, "assets/logo.png": b"\x89PNG\r\n\x1a\n\x00\x01"})
    pack = read_skill_zip(raw)
    binary = next(item for item in pack.files if item.path == "assets/logo.png")
    assert binary.content is None
    assert binary.size > 0


@pytest.mark.parametrize(
    "entry_name",
    ["../evil.sh", "/etc/passwd", "a/../../evil.sh", "C:/Windows/system32/x.dll"],
)
def test_rejects_path_traversal(entry_name: str) -> None:
    raw = make_zip({"SKILL.md": SKILL_MD, entry_name: b"x"})
    with pytest.raises(SemanticError):
        read_skill_zip(raw)


def test_rejects_missing_skill_md() -> None:
    raw = make_zip({"README.md": b"# hi"})
    with pytest.raises(SemanticError):
        read_skill_zip(raw)


def test_rejects_bad_zip() -> None:
    with pytest.raises(SemanticError):
        read_skill_zip(b"not a zip")


def test_rejects_oversized_zip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "skill_zip_max_mb", 1, raising=False)
    # 用不可压缩数据，保证 zip 本身体积就超限（全零会被 deflate 压到很小）
    import os as _os

    raw = make_zip({"SKILL.md": SKILL_MD, "big.bin": _os.urandom(2 * 1024 * 1024)})
    with pytest.raises(SemanticError):
        read_skill_zip(raw)


def test_rejects_bomb_after_extract(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "skill_extract_max_mb", 1, raising=False)
    raw = make_zip({"SKILL.md": SKILL_MD, "zeros.bin": b"0" * (2 * 1024 * 1024)})
    with pytest.raises(SemanticError):
        read_skill_zip(raw)


def test_rejects_too_many_files(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "skill_files_max", 3, raising=False)
    entries = {"SKILL.md": SKILL_MD}
    for index in range(5):
        entries[f"f{index}.md"] = b"x"
    with pytest.raises(SemanticError):
        read_skill_zip(make_zip(entries))


def test_rejects_symlink_member() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("SKILL.md", SKILL_MD)
        info = zipfile.ZipInfo("link.md")
        info.external_attr = (0o120777 << 16)
        archive.writestr(info, "SKILL.md")
    with pytest.raises(SemanticError):
        read_skill_zip(buffer.getvalue())


def test_frontmatter_absent_falls_back() -> None:
    meta, body = parse_frontmatter("# 标题\n正文")
    assert meta == {}
    assert body.startswith("# 标题")
