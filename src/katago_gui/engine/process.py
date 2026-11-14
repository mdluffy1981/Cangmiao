"""Asynchronous GTP engine wrapper built on QProcess."""
from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass
from typing import Callable, Optional

from PySide6.QtCore import QObject, QProcess, QTimer, Signal

from .gtp import AnalysisSnapshot, GtpParseError, GtpResponse, ResponseAssembler, parse_analysis_line, parse_response
from ..i18n import tr

log = logging.getLogger(__name__)

# Failure kinds reported via GtpEngine.failed
START_FAILED = "start_failed"
COMMAND_TIMEOUT = "command_timeout"
SEARCH_TIMEOUT = "search_timeout"
EXITED = "exited"
PROTOCOL = "protocol"

# Windows NTSTATUS exit codes (as signed 32-bit) that mean the engine could not load a dependency.
STATUS_DLL_NOT_FOUND = -1073741515  # 0xC0000135
STATUS_ENTRYPOINT_NOT_FOUND = -1073741511  # 0xC0000139

FAILURE_TEXT = {
    START_FAILED: "引擎无法启动",
    COMMAND_TIMEOUT: "引擎响应超时",
    SEARCH_TIMEOUT: "AI 思考超时",
    EXITED: "引擎意外退出",
    PROTOCOL: "引擎输出无法解析",
}


@dataclass
class _Pending:
    id: int
    text: str
    callback: Optional[Callable[[GtpResponse], None]]
    timeout_s: float
    timeout_kind: str
    streaming: bool = False


class GtpEngine(QObject):
    failed = Signal(str, str)  # kind, detail
    stderr_line = Signal(str)
    analysis_update = Signal(object)  # AnalysisSnapshot
    analysis_finished = Signal(bool, str)  # ok, error text
    io_log = Signal(str)

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._proc: Optional[QProcess] = None
        self._queue: deque[_Pending] = deque()
        self._inflight: Optional[_Pending] = None
        self._next_id = 1
        self._asm = ResponseAssembler()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._on_timeout)
        self._dead = True
        self._stream_header_seen = False
        self._stop_requested = False
        self._stop_sent = False
        self._stderr_buf = b""
        self.stderr_tail: deque[str] = deque(maxlen=200)

    # ---------- lifecycle ----------
    @property
    def running(self) -> bool:
        return self._proc is not None and not self._dead

    @property
    def busy(self) -> bool:
        return self._inflight is not None or bool(self._queue)

    @property
    def analyzing(self) -> bool:
        return self._inflight is not None and self._inflight.streaming

    def start(self, program: str, args: list[str], cwd: str) -> None:
        self.kill()
        self._dead = False
        self._asm.reset()
        self._stderr_buf = b""
        self.stderr_tail.clear()
        proc = QProcess(self)
        proc.setProgram(program)
        proc.setArguments(args)
        proc.setWorkingDirectory(cwd)
        proc.readyReadStandardOutput.connect(self._on_stdout)
        proc.readyReadStandardError.connect(self._on_stderr)
        proc.errorOccurred.connect(self._on_error)
        proc.finished.connect(self._on_finished)
        self._proc = proc
        self.io_log.emit(tr("启动：{0} {1}", program, " ".join(args)))
        proc.start()

    def kill(self) -> None:
        self._timer.stop()
        self._queue.clear()
        self._inflight = None
        proc, self._proc = self._proc, None
        self._dead = True
        if proc is not None:
            for sig in (proc.readyReadStandardOutput, proc.readyReadStandardError, proc.errorOccurred, proc.finished):
                try:
                    sig.disconnect()
                except (RuntimeError, TypeError):
                    pass
            if proc.state() != QProcess.ProcessState.NotRunning:
                proc.kill()
                proc.waitForFinished(3000)
            proc.deleteLater()

    def quit(self) -> None:
        if self.running and not self.busy and self._proc is not None:
            self._dead = True  # an exit after 'quit' is expected, not a failure
            self._proc.write(b"quit\n")
            self._proc.waitForFinished(2000)
        self.kill()

    # ---------- commands ----------
    def send(self, command: str, callback: Optional[Callable[[GtpResponse], None]] = None,
             timeout_s: float = 30.0, timeout_kind: str = COMMAND_TIMEOUT) -> None:
        if not self.running:
            raise RuntimeError(tr("引擎未运行"))
        self._queue.append(_Pending(self._take_id(), command, callback, timeout_s, timeout_kind))
        self._pump()

    def start_analysis(self, color: str, interval_cs: int = 20, max_moves: int = 10) -> None:
        if not self.running:
            raise RuntimeError(tr("引擎未运行"))
        if self.busy:
            raise RuntimeError(tr("引擎忙"))
        self._stream_header_seen = False
        self._stop_requested = False
        self._stop_sent = False
        cmd = f"kata-analyze {color} {interval_cs} maxmoves {max_moves} minmoves {max_moves} rootInfo true"
        self._queue.append(_Pending(self._take_id(), cmd, None, 30.0, COMMAND_TIMEOUT, streaming=True))
        self._pump()

    def stop_analysis(self) -> None:
        p = self._inflight
        if p is None or not p.streaming or self._stop_requested:
            return
        self._stop_requested = True
        if self._stream_header_seen:
            self._send_stop()

    def _send_stop(self) -> None:
        if self._stop_sent or self._proc is None:
            return
        self._stop_sent = True
        self._write("")
        self._timer.start(15000)

    def _take_id(self) -> int:
        i = self._next_id
        self._next_id += 1
        return i

    def _write(self, text: str) -> None:
        assert self._proc is not None
        self._proc.write((text + "\n").encode("utf-8"))
        if text:
            self.io_log.emit(f">> {text}")

    def _pump(self) -> None:
        if self._inflight is not None or not self._queue or not self.running:
            return
        p = self._queue.popleft()
        self._inflight = p
        self._write(f"{p.id} {p.text}")
        self._timer.start(int(p.timeout_s * 1000))

    # ---------- process I/O ----------
    def _on_stdout(self) -> None:
        proc = self._proc
        while proc is not None and proc is self._proc and not self._dead and proc.canReadLine():
            raw = bytes(proc.readLine().data()).decode("utf-8", errors="replace")
            self._handle_line(raw)

    def _handle_line(self, raw: str) -> None:
        p = self._inflight
        line = raw.rstrip("\r\n")
        if p is not None and p.streaming and self._stream_header_seen:
            if line.strip() == "":
                self._finish_stream(True, "")
            else:
                try:
                    snap = parse_analysis_line(line)
                except GtpParseError as e:
                    self._fail(PROTOCOL, str(e))
                    return
                if snap is not None:
                    self.analysis_update.emit(snap)
            return
        if line.strip():
            self.io_log.emit(f"<< {line}")
        if p is not None and p.streaming and line.startswith("="):
            resp = parse_response([line])
            if resp.id != p.id:
                self._fail(PROTOCOL, tr("分析响应编号不匹配：期望 {0}，收到 {1}", p.id, resp.id))
                return
            # Streaming header: subsequent lines are analysis until a blank line.
            self._stream_header_seen = True
            self._timer.stop()
            if self._stop_requested:
                self._send_stop()
            return
        block = self._asm.feed(line)
        if block is None:
            return
        try:
            resp = parse_response(block)
        except GtpParseError as e:
            self._fail(PROTOCOL, str(e))
            return
        if p is None:
            log.warning("unexpected GTP response: %s", block)
            return
        if resp.id != p.id:
            self._fail(PROTOCOL, tr("响应编号不匹配：期望 {0}，收到 {1}", p.id, resp.id))
            return
        self._timer.stop()
        self._inflight = None
        if p.streaming:
            self.analysis_finished.emit(False, resp.text or tr("分析命令失败"))
        elif p.callback is not None:
            p.callback(resp)
        self._pump()

    def _finish_stream(self, ok: bool, err: str) -> None:
        self._timer.stop()
        self._inflight = None
        self._asm.reset()
        self.analysis_finished.emit(ok, err)
        self._pump()

    def _on_stderr(self) -> None:
        if self._proc is None:
            return
        self._stderr_buf += bytes(self._proc.readAllStandardError().data())
        *lines, self._stderr_buf = self._stderr_buf.split(b"\n")
        for b in lines:
            s = b.decode("utf-8", errors="replace").rstrip("\r")
            if s:
                self.stderr_tail.append(s)
                self.stderr_line.emit(s)

    def _on_error(self, err: QProcess.ProcessError) -> None:
        if err == QProcess.ProcessError.FailedToStart:
            detail = self._proc.errorString() if self._proc else ""
            self._fail(START_FAILED, detail)

    def _on_finished(self, code: int, status: QProcess.ExitStatus) -> None:
        if self._dead:
            return
        tail = "\n".join(list(self.stderr_tail)[-8:])
        detail = tr("退出码 {0}", code) + (f"\n{tail}" if tail else "")
        if code in (STATUS_DLL_NOT_FOUND, STATUS_ENTRYPOINT_NOT_FOUND):
            detail += "\n" + tr("引擎缺少运行库（DLL）或版本不匹配。CUDA 版需要 NVIDIA 显卡和最新驱动；"
                                "请重新安装 Cangmiao CUDA 版，或改用 CPU/OpenCL 引擎。")
        self._fail(EXITED, detail)

    def _on_timeout(self) -> None:
        p = self._inflight
        if p is None:
            return
        kind = COMMAND_TIMEOUT if p.streaming else p.timeout_kind
        self._fail(kind, tr("命令“{0}”在规定时间内无响应", p.text))

    def _fail(self, kind: str, detail: str) -> None:
        if self._dead and kind != START_FAILED:
            return
        self.io_log.emit(tr("!! {0}：{1}", tr(FAILURE_TEXT.get(kind, kind)), detail))
        self.kill()
        self.failed.emit(kind, detail)
