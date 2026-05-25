from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True)
class StateSnapshot(Generic[T]):
    value: T
    data: dict[str, Any]
    path: Path
    updated_at: float
    stale: bool
    source: str
    error: str = ""


class JsonStateStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def _path(self, name: str) -> Path:
        return self.root / f"{name}.json"

    def _last_good_path(self, name: str) -> Path:
        if name == "last_good_state":
            return self._path(name)
        return self.root / f"{name}.last_good.json"

    def read(self, name: str, model: type[T], max_age_s: int | None = None) -> StateSnapshot[T]:
        path = self._path(name)
        candidates = [("current", path), ("last_good", self._last_good_path(name))]
        last_error = ""
        for source, candidate in candidates:
            try:
                raw = json.loads(candidate.read_text(encoding="utf-8"))
                if not isinstance(raw, dict):
                    raise ValueError("JSON root is not an object")
                value = model.model_validate(raw)
                updated_at = candidate.stat().st_mtime
                stale = max_age_s is not None and time.time() - updated_at > max_age_s
                return StateSnapshot(value, raw, candidate, updated_at, stale, source)
            except (FileNotFoundError, OSError, json.JSONDecodeError, ValueError, ValidationError) as exc:
                last_error = str(exc)
                if source == "current" and candidate.exists():
                    self._quarantine_bad_file(candidate)

        value = model()
        return StateSnapshot(value, value.model_dump(by_alias=True), path, 0.0, True, "default", last_error)

    def write(self, name: str, value: BaseModel | dict[str, Any], *, update_last_good: bool = True) -> None:
        data = value.model_dump(by_alias=True) if isinstance(value, BaseModel) else dict(value)
        self._write_path(self._path(name), data)
        if update_last_good:
            self._write_path(self._last_good_path(name), data)

    def write_raw(self, path: str | Path, data: dict[str, Any], *, update_last_good: bool = False) -> None:
        target = Path(path)
        self._write_path(target, data)
        if update_last_good:
            self._write_path(target.with_suffix(".last_good.json"), data)

    def rollback(self, name: str) -> bool:
        current = self._path(name)
        last_good = self._last_good_path(name)
        if not last_good.exists():
            return False
        current.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(last_good, current)
        return True

    def _write_path(self, path: Path, data: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(prefix=f".{path.stem}-", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_path, path)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def _quarantine_bad_file(self, path: Path) -> None:
        try:
            bad_path = path.with_suffix(f".bad-{int(time.time())}.json")
            if not bad_path.exists():
                path.replace(bad_path)
        except OSError:
            pass

