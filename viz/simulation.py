"""纯 Python 模拟子进程控制器，不依赖任何 GUI 工具包。"""
from __future__ import annotations

from collections import deque

import json
import math
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from typing import Any, Callable

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
_READY_TIMEOUT = 30.0
_STOP_TIMEOUT = 5.0
_KILL_TIMEOUT = 2.0


class SimulationController:
    def __init__(
        self,
        on_status: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.db_path: str | None = None
        self.state = "stopped"
        self.current_tick = 0
        self.rate: float | None = None
        self.last_error: str | None = None
        self.on_status = on_status

        self._process: subprocess.Popen[str] | None = None
        self._reader: threading.Thread | None = None
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._is_ready = False
        self._stderr_tail: deque[str] = deque(maxlen=200)
        self._stderr_reader: threading.Thread | None = None

    def start(self, seed: int = 0) -> None:
        with self._condition:
            if self._process is not None and self._process.poll() is None:
                raise RuntimeError("模拟子进程已经在运行")
            self.db_path = None
            self.current_tick = 0
            self.rate = None
            self.last_error = None
            self.state = "stopped"
            self._is_ready = False

        env = os.environ.copy()
        python_paths = [str(_ROOT), str(_SRC)]
        if env.get("PYTHONPATH"):
            python_paths.append(env["PYTHONPATH"])
        env["PYTHONPATH"] = os.pathsep.join(python_paths)
        env["PYTHONIOENCODING"] = "utf-8"

        try:
            process = subprocess.Popen(
                [sys.executable, "-m", "viz.sim_worker", "--seed", str(seed)],
                shell=False,
                cwd=str(_ROOT),
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
        except OSError as exc:
            message = f"无法启动模拟子进程：{exc}"
            with self._condition:
                self.last_error = message
                self.state = "stopped"
                self._condition.notify_all()
            raise RuntimeError(message) from exc

        reader = threading.Thread(
            target=self._read_stdout,
            args=(process,),
            name="simulation-stdout",
            daemon=True,
        )
        stderr_reader = threading.Thread(
            target=self._drain_stderr,
            args=(process,),
            name="simulation-stderr",
            daemon=True,
        )
        with self._condition:
            self._process = process
            self._reader = reader
            self._stderr_reader = stderr_reader
        reader.start()
        stderr_reader.start()

        deadline = time.monotonic() + _READY_TIMEOUT
        with self._condition:
            while not self._is_ready and self.last_error is None:
                returncode = process.poll()
                if returncode is not None:
                    stderr_text = "".join(self._stderr_tail).strip()
                    detail = f"\nstderr 末尾：\n{stderr_text}" if stderr_text else ""
                    self.last_error = f"模拟子进程在 ready 前退出（退出码 {returncode}）{detail}"
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self.last_error = "等待模拟子进程 ready 超时"
                    break
                self._condition.wait(min(remaining, 0.2))
            error = self.last_error if not self._is_ready else None

        if error is not None:
            self.stop()
            raise RuntimeError(error)

    def run(self) -> None:
        self._send("run")

    def pause(self) -> None:
        self._send("pause")

    def step(self) -> None:
        self._send("step")

    def set_speed(self, seconds: float) -> None:
        if isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
            raise ValueError("seconds 必须是数字")
        value = float(seconds)
        if not math.isfinite(value) or value < 0:
            raise ValueError("seconds 必须是大于等于 0 的有限秒数（0 表示全速）")
        self._send("speed", seconds=value)

    def stop(self) -> None:
        with self._condition:
            process = self._process
            reader = self._reader
            stderr_reader = self._stderr_reader

        if process is None:
            with self._condition:
                self.state = "stopped"
                self._condition.notify_all()
            return

        if process.poll() is None:
            try:
                self._send("stop")
            except RuntimeError:
                pass
            try:
                process.wait(timeout=_STOP_TIMEOUT)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=_KILL_TIMEOUT)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=_KILL_TIMEOUT)
        else:
            process.wait(timeout=_KILL_TIMEOUT)

        for stream_reader in (reader, stderr_reader):
            if stream_reader is not None and stream_reader is not threading.current_thread():
                stream_reader.join(timeout=_KILL_TIMEOUT)
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass

        with self._condition:
            self.state = "stopped"
            self._condition.notify_all()
            snapshot = self._snapshot("status")
        self._notify(snapshot)

    def close(self) -> None:
        self.stop()

    def _send(self, command: str, **values: Any) -> None:
        with self._condition:
            process = self._process
            if process is None or process.poll() is not None or self.state == "stopped":
                raise RuntimeError("模拟子进程未运行")
            if process.stdin is None:
                raise RuntimeError("模拟子进程 stdin 不可用")
            message = {"command": command, **values}
            try:
                process.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
                process.stdin.flush()
            except (BrokenPipeError, OSError, ValueError) as exc:
                self.last_error = f"发送 {command} 命令失败：{exc}"
                self._condition.notify_all()
                raise RuntimeError(self.last_error) from exc

    def _drain_stderr(self, process: subprocess.Popen[str]) -> None:
        """持续读取子进程 stderr：防止 PIPE 缓冲区满阻塞子进程，
        同时保留末尾若干行用于 ready 前崩溃的诊断。"""
        try:
            if process.stderr is None:
                return
            for line in process.stderr:
                self._stderr_tail.append(line)
        except Exception:
            pass

    def _read_stdout(self, process: subprocess.Popen[str]) -> None:
        try:
            if process.stdout is None:
                raise RuntimeError("模拟子进程 stdout 不可用")
            for line in process.stdout:
                if not line.strip():
                    continue
                try:
                    message = json.loads(line)
                except json.JSONDecodeError as exc:
                    self._receive(process, {
                        "type": "error",
                        "error": f"子进程返回无效 JSON：{exc.msg}",
                    })
                    continue
                if not isinstance(message, dict):
                    self._receive(process, {
                        "type": "error",
                        "error": "子进程状态必须是 JSON 对象",
                    })
                    continue
                self._receive(process, message)
        except Exception as exc:  # noqa: BLE001 - 读取线程边界记录可读错误
            self._receive(process, {
                "type": "error",
                "error": f"读取子进程状态失败：{type(exc).__name__}: {exc}",
            })
        finally:
            with self._condition:
                if self._process is process:
                    if self.state != "stopped":
                        if process.poll() is None and self.last_error is None:
                            self.last_error = "模拟子进程 stdout 意外关闭"
                        self.state = "stopped"
                    self._condition.notify_all()

    def _receive(
        self,
        process: subprocess.Popen[str],
        message: dict[str, Any],
    ) -> None:
        with self._condition:
            if self._process is not process:
                return
            message_type = str(message.get("type", "status"))
            if message_type == "ready":
                self._is_ready = True
            state = message.get("state")
            if isinstance(state, str):
                self.state = state
            tick = message.get("current_tick")
            if isinstance(tick, int) and not isinstance(tick, bool):
                self.current_tick = tick
            rate = message.get("rate")
            if "rate" in message:
                self.rate = float(rate) if isinstance(rate, (int, float)) and not isinstance(rate, bool) else None
            db_path = message.get("db_path")
            if isinstance(db_path, str):
                self.db_path = db_path
            if message_type == "error":
                self.last_error = str(message.get("error") or "未知模拟错误")
            self._condition.notify_all()
            snapshot = self._snapshot(message_type)
        self._notify(snapshot)

    def _snapshot(self, message_type: str) -> dict[str, Any]:
        return {
            "type": message_type,
            "state": self.state,
            "current_tick": self.current_tick,
            "rate": self.rate,
            "db_path": self.db_path,
            "last_error": self.last_error,
        }

    def _notify(self, snapshot: dict[str, Any]) -> None:
        if self.on_status is None:
            return
        try:
            self.on_status(snapshot)
        except Exception as exc:  # noqa: BLE001 - 回调错误不能终止协议读取线程
            with self._condition:
                self.last_error = f"on_status 回调失败：{type(exc).__name__}: {exc}"
                self._condition.notify_all()
