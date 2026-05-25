import os

import psutil
from broadcast_control.services.pid import PIDManager


def test_pid_manager_tracks_expected_process(tmp_path):
    manager = PIDManager(tmp_path / "main.pid.json", psutil.Process(os.getpid()).exe())
    manager.write(os.getpid())

    proc = manager.current()

    assert proc is not None
    assert proc.pid == os.getpid()


def test_pid_manager_rejects_wrong_exe(tmp_path):
    manager = PIDManager(tmp_path / "main.pid.json", tmp_path / "missing.exe")
    manager.write(os.getpid())

    assert manager.current() is None
