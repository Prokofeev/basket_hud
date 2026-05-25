from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppPaths:
    base_dir: Path
    content_root: Path
    json_dir: Path
    config_path: Path
    result_path: Path
    player_path: Path
    player_candidates_path: Path
    player_cache_dir: Path
    main_exe: Path
    manager_exe: Path
    pid_path: Path

    @classmethod
    def resolve(cls, base_dir: str | Path | None = None) -> "AppPaths":
        if base_dir is None:
            if getattr(sys, "frozen", False):
                root = Path(sys.executable).resolve().parent
            else:
                root = Path.cwd().resolve()
        else:
            root = Path(base_dir).resolve()

        candidates = [root, root.parent]
        data_root = root
        for candidate in candidates:
            if (candidate / "json" / "config.json").exists() or (candidate / "json" / "result.json").exists():
                data_root = candidate
                break

        json_dir = data_root / "json"
        return cls(
            base_dir=root,
            content_root=data_root,
            json_dir=json_dir,
            config_path=json_dir / "config.json",
            result_path=json_dir / "result.json",
            player_path=json_dir / "player.json",
            player_candidates_path=json_dir / "player_candidates.json",
            player_cache_dir=json_dir / "players",
            main_exe=data_root / "main.exe",
            manager_exe=data_root / "manager.exe",
            pid_path=json_dir / "main.pid.json",
        )


def env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}

