"""独立模拟子进程：stdin/stdout 使用 UTF-8 JSON Lines 协议。"""
from __future__ import annotations

import argparse
import datetime
import json
import math
import os
from pathlib import Path
import queue
import random
import sys
import threading
import time
from typing import Any, TextIO

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
for _path in (str(_ROOT), str(_SRC)):
    if _path not in sys.path:
        sys.path.insert(0, _path)
os.chdir(_ROOT)

from vale.core.config_loader import load_config  # noqa: E402
from vale.core.event_log import EventLog  # noqa: E402
from vale.core.scheduler import run_tick  # noqa: E402
from vale.core.world import World  # noqa: E402
from vale.domains.society.agents import AgentModule  # noqa: E402
from vale.domains.environment.climate import ClimateModule  # noqa: E402

_WORLD_ID = "brookvale-town-001"
_DEFAULT_SPEED = 1.0
_STATUS_INTERVAL = 0.25  # 全速模式下的状态上报间隔（秒）


def _create_db_path() -> str:
    directory = _ROOT / "data" / "worlds" / _WORLD_ID
    directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    path = directory / f"sim-{timestamp}-{os.getpid()}.db"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    os.close(fd)
    return str(path)


class SimulationWorker:
    def __init__(self, seed: int, output: TextIO) -> None:
        self.seed = seed
        self.output = output
        self.state = "paused"
        self.speed = _DEFAULT_SPEED
        self.db_path: str | None = None
        self.world: World | None = None
        self.event_log: EventLog | None = None
        self.commands: queue.Queue[tuple[dict[str, Any] | None, str | None]] = queue.Queue()
        self._status_time: float | None = None
        self._status_tick: int = 0

    def _emit(self, message: dict[str, Any]) -> None:
        self.output.write(json.dumps(message, ensure_ascii=False) + "\n")
        self.output.flush()

    def _status(self, message_type: str = "status") -> None:
        current_tick = self.world.current_tick if self.world is not None else 0
        now = time.monotonic()
        rate = None
        if self._status_time is not None and current_tick >= self._status_tick:
            elapsed = now - self._status_time
            if elapsed > 1e-6:
                rate = round((current_tick - self._status_tick) / elapsed, 1)
        self._status_time = now
        self._status_tick = current_tick
        self._emit({
            "type": message_type,
            "status": "ready" if message_type == "ready" else self.state,
            "state": self.state,
            "current_tick": current_tick,
            "db_path": self.db_path,
            "rate": rate,
        })

    def _error(self, message: str) -> None:
        current_tick = self.world.current_tick if self.world is not None else 0
        self._emit({
            "type": "error",
            "error": message,
            "status": self.state,
            "state": self.state,
            "current_tick": current_tick,
            "db_path": self.db_path,
        })

    def _read_stdin(self) -> None:
        try:
            for line in sys.stdin:
                if not line.strip():
                    continue
                try:
                    command = json.loads(line)
                except json.JSONDecodeError as exc:
                    self.commands.put((None, f"命令不是有效 JSON：{exc.msg}"))
                    continue
                if not isinstance(command, dict):
                    self.commands.put((None, "命令必须是 JSON 对象"))
                    continue
                self.commands.put((command, None))
        except Exception as exc:  # noqa: BLE001 - 通过协议报告输入线程错误
            self.commands.put((None, f"读取命令失败：{type(exc).__name__}: {exc}"))
        finally:
            self.commands.put(({"command": "stop"}, None))

    @staticmethod
    def _speed(value: Any) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("speed 的 seconds 必须是数字")
        seconds = float(value)
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError("speed 的 seconds 必须是大于等于 0 的有限秒数（0 表示全速）")
        return seconds

    def _serve(self) -> None:
        self.db_path = _create_db_path()
        self.event_log = EventLog(self.db_path)
        config = load_config(_WORLD_ID)
        self.world = World(
            world_id=config.world.world_id,
            event_log=self.event_log,
            start_tick=config.world.start_tick,
            config=config,
        )
        self.world.register(ClimateModule(rng=random.Random(self.seed)))
        self.world.register(AgentModule(rng=random.Random(self.seed * 7 + 13)))

        reader = threading.Thread(target=self._read_stdin, daemon=True)
        reader.start()
        self._status("ready")

        next_tick: float | None = None
        while True:
            timeout = None
            if self.state == "running":
                if self.speed > 0:
                    if next_tick is not None:
                        timeout = max(0.0, next_tick - time.monotonic())
                else:
                    timeout = 0.0  # 全速：不等待，立即推进
            try:
                command, error = self.commands.get(timeout=timeout)
            except queue.Empty:
                command, error = None, None

            if error is not None:
                self._error(error)
            elif command is not None:
                action = command.get("command")
                if action == "run":
                    if self.state == "paused":
                        self.state = "running"
                        next_tick = time.monotonic() + self.speed
                    self._status()
                elif action == "pause":
                    self.state = "paused"
                    next_tick = None
                    self._status()
                elif action == "step":
                    if self.state != "paused":
                        self._error("step 只能在 paused 状态使用")
                    else:
                        run_tick(self.world)
                        self._status()
                elif action == "speed":
                    try:
                        self.speed = self._speed(command.get("seconds"))
                    except ValueError as exc:
                        self._error(str(exc))
                    else:
                        if self.state == "running":
                            next_tick = time.monotonic() + self.speed
                        self._status()
                elif action == "stop":
                    break
                else:
                    self._error(f"未知命令：{action!r}")

            if self.state == "running":
                if self.speed > 0:
                    if next_tick is not None and time.monotonic() >= next_tick:
                        run_tick(self.world)
                        self._status()
                        next_tick = time.monotonic() + self.speed
                else:
                    # 全速：连续推进，定期上报状态，命令到达即时让出
                    next_report = time.monotonic() + _STATUS_INTERVAL
                    while self.state == "running":
                        run_tick(self.world)
                        now = time.monotonic()
                        if now >= next_report:
                            self._status()
                            next_report = now + _STATUS_INTERVAL
                        if not self.commands.empty():
                            break
                    if self.state == "running":
                        self._status()

    def run(self) -> None:
        try:
            self._serve()
        except Exception as exc:  # noqa: BLE001 - 子进程边界统一转为可读协议错误
            self.state = "stopped"
            self._error(f"模拟子进程失败：{type(exc).__name__}: {exc}")
        finally:
            if self.event_log is not None:
                try:
                    self.event_log.close()
                except Exception as exc:  # noqa: BLE001 - 关闭错误也需可读
                    self._error(f"关闭 EventLog 失败：{type(exc).__name__}: {exc}")
            self.state = "stopped"
            self._status()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    protocol_output = sys.stdout
    # scheduler 和模块的 print 不能混入 JSON Lines stdout。
    sys.stdout = sys.stderr
    SimulationWorker(args.seed, protocol_output).run()


if __name__ == "__main__":
    main()
