from __future__ import annotations

import os
import socket
import time
from dataclasses import dataclass

from broadcast_control.models.schemas import PlayerState, ResultState
from broadcast_control.services.process import ScraperProcessController
from broadcast_control.state.paths import AppPaths
from broadcast_control.state.store import JsonStateStore


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    severity: str
    detail: str


class HealthCheckService:
    def __init__(self, paths: AppPaths, store: JsonStateStore, process: ScraperProcessController) -> None:
        self.paths = paths
        self.store = store
        self.process = process

    def run(self, port: int = 8081) -> list[CheckResult]:
        checks: list[CheckResult] = []
        checks.append(CheckResult("main_exe", self.paths.main_exe.exists(), "fail", str(self.paths.main_exe)))
        checks.append(CheckResult("json_writable", os.access(self.paths.json_dir, os.W_OK), "fail", str(self.paths.json_dir)))

        result = self.store.read("result", ResultState, max_age_s=20)
        result_age = time.time() - result.updated_at if result.updated_at else 0
        checks.append(CheckResult("result_fresh", not result.stale, "warn", f"{result.source}, age={result_age:.1f}s"))

        player = self.store.read("player", PlayerState, max_age_s=120)
        checks.append(CheckResult("player_readable", bool(player.data), "warn", player.source))

        checks.append(CheckResult("scraper_process", self.process.is_running(), "warn", "running" if self.process.is_running() else "stopped"))
        checks.append(CheckResult("port_available_or_serving", self._port_check(port), "warn", f"port={port}"))
        return checks

    def _port_check(self, port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5)
            return sock.connect_ex(("127.0.0.1", int(port))) in (0, 10061)

