"""技能包（zip）解析与校验。

安全底线（否则上传 zip 等于给服务器写文件权限）：
- 拒绝绝对路径、`..`、盘符、符号链接；
- 限制 zip 体积、解压后总体积、文件数量；
- 必须含 SKILL.md（根部或唯一一层子目录里）。
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from app.core.config import get_settings
from app.core.exceptions import SemanticError

TEXT_SUFFIXES = {
    ".md",
    ".txt",
    ".py",
    ".js",
    ".ts",
    ".sh",
    ".ps1",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".sql",
    ".html",
    ".css",
}


@dataclass
class SkillFileData:
    path: str
    size: int
    sha256: str
    content: str | None  # 文本才入库，二进制为 None


@dataclass
class SkillPack:
    name: str
    description: str
    entry_path: str
    files: list[SkillFileData] = field(default_factory=list)

    @property
    def manifest(self) -> str:
        return json.dumps(
            [{"path": f.path, "size": f.size, "sha256": f.sha256} for f in self.files],
            ensure_ascii=False,
        )


_FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """极简 frontmatter 解析（只支持 `key: value`，避免为一行元数据引入 YAML 依赖）。"""
    match = _FRONTMATTER.match(text)
    if not match:
        return {}, text
    meta: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip().lower()] = value.strip().strip("'\"")
    return meta, text[match.end() :]


def _safe_member_path(name: str) -> PurePosixPath:
    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or ".." in path.parts:
        raise SemanticError(f"技能包内含非法路径：{name}")
    if any(part == "" for part in path.parts):
        raise SemanticError(f"技能包内含非法路径：{name}")
    if len(path.parts) and path.parts[0].endswith(":"):
        raise SemanticError(f"技能包内含绝对路径：{name}")
    return path


def _strip_root(paths: list[PurePosixPath]) -> tuple[str, list[PurePosixPath]]:
    """允许 zip 里套一层目录（GitHub 下载常见）；返回 (前缀, 去掉前缀的路径)。"""
    if any(len(p.parts) == 1 and p.name.lower() == "skill.md" for p in paths):
        return "", paths
    roots = {p.parts[0] for p in paths if len(p.parts) > 1}
    if len(roots) == 1:
        root = roots.pop()
        stripped = [PurePosixPath(*p.parts[1:]) for p in paths if len(p.parts) > 1]
        if any(p.name.lower() == "skill.md" and len(p.parts) == 1 for p in stripped):
            return root, stripped
    raise SemanticError("技能包根目录必须包含 SKILL.md")


def read_skill_zip(raw: bytes) -> SkillPack:
    settings = get_settings()
    if len(raw) > settings.skill_zip_max_mb * 1024 * 1024:
        raise SemanticError(f"zip 超过 {settings.skill_zip_max_mb} MB 上限")
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile as exc:
        raise SemanticError("不是合法的 zip 文件") from exc

    members = [info for info in archive.infolist() if not info.is_dir()]
    if len(members) > settings.skill_files_max:
        raise SemanticError(f"技能包文件数超过 {settings.skill_files_max} 上限")

    parsed: list[tuple[PurePosixPath, zipfile.ZipInfo]] = []
    total = 0
    for info in members:
        path = _safe_member_path(info.filename)
        mode = (info.external_attr >> 16) & 0o170000
        if mode == 0o120000:
            raise SemanticError(f"技能包不允许符号链接：{info.filename}")
        total += info.file_size
        parsed.append((path, info))

    if total > settings.skill_extract_max_mb * 1024 * 1024:
        raise SemanticError(f"解压后超过 {settings.skill_extract_max_mb} MB 上限")

    prefix, stripped = _strip_root([p for p, _ in parsed])
    by_path = {p: info for p, info in parsed}
    files: list[SkillFileData] = []
    entry_text: str | None = None
    for path in stripped:
        original = PurePosixPath(prefix, *path.parts) if prefix else path
        info = by_path[original]
        data = archive.read(info)
        digest = hashlib.sha256(data).hexdigest()
        content: str | None = None
        if path.suffix.lower() in TEXT_SUFFIXES:
            try:
                content = data.decode("utf-8")
            except UnicodeDecodeError:
                content = None
        if path.name.lower() == "skill.md" and len(path.parts) == 1:
            entry_text = content
        files.append(
            SkillFileData(path=str(path), size=len(data), sha256=digest, content=content)
        )

    if entry_text is None:
        raise SemanticError("SKILL.md 必须是 UTF-8 文本")

    meta, body = parse_frontmatter(entry_text)
    name = meta.get("name") or "skill"
    description = meta.get("description") or (body.strip().splitlines() or ["（无描述）"])[0][:500]
    return SkillPack(name=name[:64], description=description[:512], entry_path="SKILL.md", files=files)


def write_skill_pack(pack: SkillPack, raw: bytes, dest: Path) -> None:
    """把 zip 解到目标目录（只写已校验过的相对路径）。"""
    dest.mkdir(parents=True, exist_ok=True)
    archive = zipfile.ZipFile(io.BytesIO(raw))
    members = [info for info in archive.infolist() if not info.is_dir()]
    prefix, stripped = _strip_root([_safe_member_path(i.filename) for i in members])
    by_path = {_safe_member_path(i.filename): i for i in members}
    for path in stripped:
        original = PurePosixPath(prefix, *path.parts) if prefix else path
        target = dest.joinpath(*path.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(archive.read(by_path[original]))
