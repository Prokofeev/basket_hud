from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

import psutil


@dataclass(frozen=True)
class ProcessInfo:
    pid: int
    exe: str
    started_at: float


class PIDManager:
    def __init__(self, pid_path: str | Path, expected_exe: str | Path) -> None:
        self.pid_path = Path(pid_path)
        self.expected_exe = Path(expected_exe).resolve()

    def read(self) -> ProcessInfo | None:
        try:
            raw = json.loads(self.pid_path.read_text(encoding="utf-8"))
            return ProcessInfo(int(raw["pid"]), str(raw["exe"]), float(raw["started_at"]))
        except Exception:
            return None

    def write(self, pid: int) -> None:
        self.pid_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"pid": pid, "exe": str(self.expected_exe), "started_at": time.time()}
        self.pid_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def current(self) -> psutil.Process | None:
        info = self.read()
        if not info or not psutil.pid_exists(info.pid):
            self.clear()
            return None
        try:
            proc = psutil.Process(info.pid)
            if Path(proc.exe()).resolve() != self.expected_exe:
                self.clear()
                return None
            return proc
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            self.clear()
            return None

    def adopt_existing(self) -> psutil.Process | None:
        for proc in psutil.process_iter(["pid", "name", "exe"]):
            try:
                exe = proc.info.get("exe")
                if exe and Path(exe).resolve() == self.expected_exe:
                    self.write(int(proc.info["pid"]))
                    return psutil.Process(int(proc.info["pid"]))
            except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
                continue
        return None

    def clear(self) -> None:
        try:
            self.pid_path.unlink()
        except FileNotFoundError:
            pass

