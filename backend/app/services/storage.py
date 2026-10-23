from __future__ import annotations

from pathlib import Path

from app.core.config import BACKEND_DIR, get_settings


def storage_root() -> Path:
    root = Path(get_settings().storage_dir)
    if not root.is_absolute():
        root = BACKEND_DIR / root
    return root


def skill_dir(project_id: int, skill_id: int) -> Path:
    return storage_root() / "skills" / str(project_id) / str(skill_id)


def ensure_skill_dir(project_id: int, skill_id: int) -> Path:
    path = skill_dir(project_id, skill_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def remove_skill_dir(project_id: int, skill_id: int) -> None:
    import shutil

    target = skill_dir(project_id, skill_id)
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
