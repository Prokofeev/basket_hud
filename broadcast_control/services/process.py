from __future__ import annotations

import subprocess
from pathlib import Path

import psutil

from .pid import PIDManager


class ScraperProcessController:
    def __init__(self, exe: str | Path, cwd: str | Path, pid_manager: PIDManager) -> None:
        self.exe = Path(exe)
        self.cwd = Path(cwd)
        self.pid = pid_manager

    def current(self) -> psutil.Process | None:
        return self.pid.current() or self.pid.adopt_existing()

    def all_running(self) -> list[psutil.Process]:
        result: list[psutil.Process] = []
        expected = self.exe.resolve()
        for proc in psutil.process_iter(["pid", "exe"]):
            try:
                exe = proc.info.get("exe")
                if exe and Path(exe).resolve() == expected:
                    result.append(psutil.Process(int(proc.info["pid"])))
            except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
                continue
        return result

    def is_running(self) -> bool:
        return self.current() is not None

    def start(self) -> int:
        proc = self.current()
        if proc:
            return proc.pid
        if not self.exe.exists():
            raise FileNotFoundError(str(self.exe))
        started = subprocess.Popen([str(self.exe)], cwd=str(self.cwd))
        self.pid.write(started.pid)
        return started.pid

    def stop(self, timeout_s: float = 5.0) -> None:
        procs = self.all_running()
        if not procs:
            self.pid.clear()
            return
        seen: set[int] = set()
        targets: list[psutil.Process] = []
        for proc in procs:
            if proc.pid in seen:
                continue
            try:
                children = proc.children(recursive=True)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                children = []
            for target in children + [proc]:
                if target.pid not in seen:
                    seen.add(target.pid)
                    targets.append(target)
        try:
            current_pid = psutil.Process().pid
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            current_pid = -1
        for target in targets:
            if target.pid == current_pid:
                continue
            try:
                target.terminate()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        _, alive = psutil.wait_procs(targets, timeout=timeout_s)
        for target in alive:
            try:
                target.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        self.pid.clear()

    def restart(self) -> int:
        self.stop()
        return self.start()
