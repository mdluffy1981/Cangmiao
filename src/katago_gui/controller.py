"""Game controller: owns the GameRecord, drives the engine, and enforces state transitions."""
from __future__ import annotations

import enum
import logging
import time
from dataclasses import dataclass
from typing import Callable, Generator, Optional

from PySide6.QtCore import QObject, QTimer, Signal

from .engine import launch
from .engine.gtp import AnalysisSnapshot, CandidateMove, GtpResponse
from .engine.process import FAILURE_TEXT, SEARCH_TIMEOUT, GtpEngine
from .go.board import IllegalMove
from .go.coords import Move, from_gtp, other, to_gtp
from .go.game import GameRecord
from .settings import GameSettings, Settings
from .strength import get_preset
from . import paths
from .i18n import tr

log = logging.getLogger(__name__)


class State(enum.Enum):
    UNCONFIGURED = "未配置引擎"
    STARTING = "引擎启动中"
    SYNCING = "同步棋局中"
    READY = "等待落子"
    AI_THINKING = "AI 思考中"
    ANALYZING = "分析中"
    GAME_OVER = "对局已结束"
    ERROR = "引擎出错"


class InteractionMode(enum.Enum):
    PLAY = "play"
    ANALYSIS = "analysis"


@dataclass
class Cmd:
    text: str
    timeout_s: float = launch.COMMAND_TIMEOUT_S
    timeout_kind: str = "command_timeout"


class FlowError(Exception):
    """Recoverable failure: the flow stops, the local game stays as the flow left it."""


class EngineDiverged(Exception):
    """Engine and local game can no longer be trusted to agree."""


Flow = Generator[Cmd, GtpResponse, None]

ANALYSIS_REPORT_CS = 20  # kata-analyze report interval, centiseconds
ANALYSIS_MAX_MOVES = 30  # candidate evaluations requested in each engine report
DISPLAY_CANDIDATES = 10  # highest-winrate candidates shown in the table and on the board
# Candidates this close to the best one (side-to-move winrate and score lead) are graded 本手.
HONTE_MAX_WINRATE_LOSS = 0.02
HONTE_MAX_SCORE_LOSS = 1.0


class CandidateTier(enum.Enum):
    BEST = "最优解"
    HONTE = "本手"
    NORMAL = "普通"


@dataclass(frozen=True)
class RankedCandidate:
    rank: int
    tier: CandidateTier
    move: CandidateMove


def rank_candidates(candidates: list[CandidateMove], limit: int = DISPLAY_CANDIDATES) -> list[RankedCandidate]:
    """Keep the highest-winrate candidates (side to move) and grade each against the best one."""
    top = sorted(candidates, key=lambda c: (-c.winrate, -c.visits, c.order))[:limit]
    ranked: list[RankedCandidate] = []
    for rank, c in enumerate(top, start=1):
        if rank == 1:
            tier = CandidateTier.BEST
        elif (top[0].winrate - c.winrate <= HONTE_MAX_WINRATE_LOSS + 1e-12
              and top[0].score_lead - c.score_lead <= HONTE_MAX_SCORE_LOSS + 1e-12):
            # Include exact boundary values despite floating-point subtraction error.
            tier = CandidateTier.HONTE
        else:
            tier = CandidateTier.NORMAL
        ranked.append(RankedCandidate(rank, tier, c))
    return ranked


@dataclass
class AnalysisResult:
    snapshot: AnalysisSnapshot
    to_move: str
    move_number: int
    elapsed: float
    revision: int = 0

    def ranked_candidates(self) -> list[RankedCandidate]:
        return rank_candidates(self.snapshot.candidates)

    def black_winrate(self) -> Optional[float]:
        wr = self.snapshot.root_winrate
        if wr is None:
            return None
        return wr if self.to_move == "B" else 1.0 - wr

    def black_score_lead(self) -> Optional[float]:
        s = self.snapshot.root_score_lead
        if s is None:
            return None
        return s if self.to_move == "B" else -s


def color_name(c: str) -> str:
    return tr("黑方" if c == "B" else "白方")


class GameController(QObject):
    state_changed = Signal(object)
    game_changed = Signal()
    analysis_changed = Signal(object)  # AnalysisResult or None
    message = Signal(str)  # transient status text
    error = Signal(str)  # actionable error for the user
    engine_info = Signal(str)
    startup_progress = Signal(str)

    def __init__(self, settings: Settings, engine: Optional[GtpEngine] = None, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.settings = settings
        self.engine = engine or GtpEngine(self)
        self.engine.failed.connect(self._on_engine_failed)
        self.engine.stderr_line.connect(self._on_stderr)
        self.engine.analysis_update.connect(self._on_analysis_update)
        self.engine.analysis_finished.connect(self._on_analysis_finished)
        g = settings.game
        self.game = GameRecord(size=g.board_size, rules_key=g.rules, komi=g.komi, human_color=g.human_color)
        self.game.dirty = False
        self.strength_key = g.strength
        self.mode = InteractionMode.PLAY
        self.state = State.UNCONFIGURED
        self.commands: set[str] = set()
        self.supports_analysis = False
        self.engine_name = ""
        self.analysis: Optional[AnalysisResult] = None
        self._flow: Optional[Flow] = None
        self._flow_done: Optional[Callable[[bool], None]] = None
        self._after_analysis: Optional[Callable[[], None]] = None
        self._analysis_started = 0.0
        self._analysis_revision = 0
        self._analysis_stopping = False
        self._analysis_enabled = False
        self._position_revision = 0
        self._pending_opening_ai = False
        self._last_error = ""
        self._pending_move: Optional[tuple[GameRecord, bool, str, str]] = None

    # ------------------------------------------------------------------ state
    def _set_state(self, s: State) -> None:
        if s != self.state:
            self.state = s
            self.state_changed.emit(s)

    @property
    def last_error(self) -> str:
        return self._last_error

    def _resting_state(self) -> State:
        return State.GAME_OVER if self.game.finished else State.READY

    @property
    def interactive(self) -> bool:
        return self.state in (State.READY, State.GAME_OVER, State.ANALYZING) and not self._analysis_stopping

    @property
    def can_replace_game(self) -> bool:
        return self.interactive or self.state in (State.UNCONFIGURED, State.ERROR)

    @property
    def can_save(self) -> bool:
        return self.can_replace_game

    @property
    def analysis_stopping(self) -> bool:
        return self._analysis_stopping

    @property
    def analysis_enabled(self) -> bool:
        """True while analysis should keep following the position until the user stops it."""
        return self._analysis_enabled

    def can_human_play(self) -> bool:
        return (self.mode == InteractionMode.PLAY and self.interactive and not self.game.finished
                and self.game.to_move == self.game.human_color)

    def can_board_play(self) -> bool:
        if self.mode == InteractionMode.ANALYSIS:
            return self.interactive and not self.game.finished
        return self.can_human_play()

    def can_ai_move(self) -> bool:
        return (self.mode == InteractionMode.PLAY and self.interactive and not self.game.finished
                and self.game.to_move == self.game.ai_color)

    def can_undo(self) -> bool:
        return self.interactive and bool(self.game.moves)

    def can_analyze(self) -> bool:
        return self.supports_analysis and self.state in (State.READY, State.GAME_OVER)

    # ------------------------------------------------------------- engine life
    def start_engine(self, auto_ai_move: bool = True) -> None:
        self._cancel_work()
        self.engine.kill()
        self.commands.clear()
        self.supports_analysis = False
        self._clear_analysis()
        missing = self.settings.engine.missing()
        if missing:
            self._last_error = "；".join(missing)
            self._set_state(State.UNCONFIGURED)
            self.game_changed.emit()
            self.error.emit(tr("KataGo 引擎未配置：{0}", self._last_error))
            return
        self._set_state(State.STARTING)
        self.startup_progress.emit(tr("正在启动 KataGo（首次运行需加载模型并调优 GPU，可能需要数分钟）…"))

        def done(ok: bool) -> None:
            should_open = auto_ai_move or self._pending_opening_ai
            if ok and should_open and self.can_ai_move() and not self.game.moves:
                self._pending_opening_ai = False
                self.ai_move()

        self._run(self._handshake_flow(), State.STARTING, done)
        self._launch()

    def _launch(self) -> None:
        es = self.settings.engine
        self.engine.start(es.executable, launch.engine_args(es), str(paths.engine_work_dir()))

    def restart_engine(self) -> None:
        """Restart the engine and resync from the local record (recovery from ERROR)."""
        self.engine.kill()
        self.start_engine(auto_ai_move=False)

    def shutdown(self) -> None:
        self._cancel_work()
        self.engine.quit()

    def interrupt(self) -> None:
        self._enter_error(tr("当前操作已中止，已保留最后确认的棋局"))

    def _rollback_pending_move(self) -> None:
        pending, self._pending_move = self._pending_move, None
        if pending is not None:
            g, dirty, result, note = pending
            g.undo()
            g.dirty, g.result, g.result_note = dirty, result, note

    def _cancel_work(self) -> None:
        self._flow = None
        self._flow_done = None
        self._after_analysis = None
        self._analysis_stopping = False
        self._analysis_enabled = False
        self._rollback_pending_move()

    def _handshake_flow(self) -> Flow:
        r = yield Cmd("protocol_version", launch.STARTUP_TIMEOUT_S)
        if not r.ok or r.text.strip() != "2":
            raise EngineDiverged(tr("引擎不支持 GTP 协议版本 2：{0}", r.text))
        r = yield Cmd("name")
        if not r.ok or not r.text.strip():
            raise EngineDiverged(tr("引擎名称握手失败：{0}", r.text))
        name = r.text
        r = yield Cmd("version")
        if not r.ok or not r.text.strip():
            raise EngineDiverged(tr("引擎版本握手失败：{0}", r.text))
        ver = r.text
        r = yield Cmd("list_commands")
        self.commands = set(r.text.split()) if r.ok else set()
        missing = [c for c in launch.REQUIRED_COMMANDS if c not in self.commands]
        if missing:
            raise EngineDiverged(tr("引擎缺少必需的 GTP 命令：{0}（请使用 KataGo 引擎）", "、".join(missing)))
        self.supports_analysis = "kata-analyze" in self.commands
        self.engine_name = f"{name} {ver}"
        self.engine_info.emit(self.engine_name)
        yield from self._sync_flow()

    def _strength_flow(self, key: Optional[str] = None) -> Flow:
        if "kata-set-param" not in self.commands:
            raise EngineDiverged(tr("引擎不支持 kata-set-param，无法应用搜索预算，请更新 KataGo"))
        p = get_preset(key or self.strength_key)
        for key, val in (("maxVisits", p.max_visits), ("maxPlayouts", 10_000_000), ("maxTime", p.max_time)):
            r = yield Cmd(f"kata-set-param {key} {val}")
            if not r.ok:
                raise EngineDiverged(tr("设置思考强度失败（{0}）：{1}", key, r.text))

    def _sync_flow(self, game: Optional[GameRecord] = None, strength: Optional[str] = None) -> Flow:
        """Rebuild the engine's position from the local game record."""
        g = game if game is not None else self.game
        for text in (f"boardsize {g.size}", "clear_board", f"kata-set-rules {g.rules_key}", f"komi {g.komi:g}"):
            r = yield Cmd(text)
            if not r.ok:
                raise EngineDiverged(tr("同步棋局失败：{0} → {1}", text, r.text))
        yield from self._strength_flow(strength)
        for m in g.moves:
            text = f"play {m.color} {to_gtp(m.move, g.size)}"
            r = yield Cmd(text)
            if not r.ok:
                raise EngineDiverged(tr("同步棋局失败：{0} → {1}", text, r.text))

    # ---------------------------------------------------------------- runner
    def _run(self, flow: Flow, busy: State, done: Optional[Callable[[bool], None]] = None) -> None:
        self._flow = flow
        self._flow_done = done
        self._set_state(busy)
        QTimer.singleShot(0, lambda f=flow: self._step(f, None, first=True))

    def _step(self, flow: Flow, resp: Optional[GtpResponse], first: bool = False) -> None:
        if flow is not self._flow:
            return  # superseded (engine failure/restart)
        try:
            if first:
                cmd = next(flow)
            else:
                assert resp is not None
                cmd = flow.send(resp)
        except StopIteration:
            self._finish_flow(True)
            return
        except FlowError as e:
            self._report(str(e))
            self._finish_flow(False)
            return
        except EngineDiverged as e:
            self._enter_error(str(e))
            return
        try:
            self.engine.send(cmd.text, lambda r, f=flow: QTimer.singleShot(0, lambda: self._step(f, r)),
                             cmd.timeout_s, cmd.timeout_kind)
        except RuntimeError as e:
            self._enter_error(tr("引擎未运行：{0}", e))

    def _finish_flow(self, ok: bool) -> None:
        done = self._flow_done
        self._flow = None
        self._flow_done = None
        self._set_state(self._resting_state())
        self.game_changed.emit()
        if done is not None:
            done(ok)
        self._resume_analysis_later()

    def _report(self, text: str) -> None:
        self._last_error = text
        self.error.emit(text)

    def _enter_error(self, text: str) -> None:
        self._cancel_work()
        self.engine.kill()
        self._clear_analysis()
        self._last_error = text
        self._set_state(State.ERROR)
        self.game_changed.emit()
        self.error.emit(tr("{0}\n可点击“重启引擎”从当前棋谱恢复。", text))

    def _on_engine_failed(self, kind: str, detail: str) -> None:
        head = tr(FAILURE_TEXT.get(kind, kind))
        if self.state == State.STARTING and kind != SEARCH_TIMEOUT:
            head = tr("引擎启动失败：{0}", head)
        self._enter_error(tr("{0}。{1}", head, detail).strip())

    def _on_stderr(self, line: str) -> None:
        if self.state == State.STARTING:
            self.startup_progress.emit(line[:160])

    # ------------------------------------------------------------- guards
    def _guarded(self, action: Callable[[], None]) -> bool:
        """Run a board-changing action now, or after stopping analysis. Returns False if refused."""
        if self._analysis_stopping:
            self.message.emit(tr("正在停止分析，请等待当前操作完成"))
            return False
        if self.state == State.ANALYZING:
            self._after_analysis = action
            self._halt_analysis()
            return True
        if self.state in (State.READY, State.GAME_OVER):
            action()
            return True
        self.message.emit(tr("当前状态（{0}）下不能执行该操作", tr(self.state.value)))
        return False

    def when_idle(self, action: Callable[[], None], end_analysis: bool = False) -> bool:
        """Run a UI transition now, or after an active analysis has stopped.

        With end_analysis, analysis no longer resumes on its own afterwards (e.g. leaving the workspace).
        """
        accepted = self._guarded(action)
        if accepted and end_analysis:
            self._analysis_enabled = False
        return accepted

    # --------------------------------------------------------------- actions
    def new_game(self, size: int, human_color: str, rules_key: str, komi: float, strength: str,
                 on_committed: Optional[Callable[[], None]] = None,
                 mode: InteractionMode = InteractionMode.PLAY) -> bool:
        game = GameRecord(size=size, rules_key=rules_key, komi=komi, human_color=human_color)
        return self._replace_game(game, strength, on_committed, auto_ai=True, mode=mode)

    def replace_game(self, game: GameRecord, on_committed: Optional[Callable[[], None]] = None,
                     mode: Optional[InteractionMode] = None) -> bool:
        """Commit an imported game only after all replay commands succeed."""
        return self._replace_game(game, self.strength_key, on_committed, mode=mode)

    def _replace_game(self, game: GameRecord, strength: str,
                      on_committed: Optional[Callable[[], None]], auto_ai: bool = False,
                      mode: Optional[InteractionMode] = None) -> bool:
        get_preset(strength)
        target_mode = self.mode if mode is None else mode

        def commit() -> None:
            self._clear_analysis()
            self.game = game
            if self.mode != target_mode:
                self._analysis_enabled = False
            self.mode = target_mode
            self.strength_key = strength
            self._position_revision += 1
            self._pending_opening_ai = (
                auto_ai and target_mode == InteractionMode.PLAY
                and game.human_color == "W" and not game.moves
            )
            self.settings.game = GameSettings(game.size, game.human_color, game.rules_key, game.komi, strength)
            if on_committed is not None:
                on_committed()
            self.game_changed.emit()

        if self.state in (State.UNCONFIGURED, State.ERROR):
            commit()
            return True

        def flow() -> Flow:
            yield from self._sync_flow(game, strength)
            commit()

        def done(ok: bool) -> None:
            if ok and auto_ai and self.can_ai_move():
                self._pending_opening_ai = False
                self.ai_move()

        def act() -> None:
            self._clear_analysis()
            self._run(flow(), State.SYNCING, done)

        return self._guarded(act)

    def set_strength(self, key: str, on_committed: Optional[Callable[[], None]] = None) -> None:
        get_preset(key)

        def commit() -> None:
            self.strength_key = key
            self.settings.game.strength = key
            if on_committed is not None:
                on_committed()

        def flow() -> Flow:
            yield from self._strength_flow(key)
            commit()

        if self.state in (State.UNCONFIGURED, State.ERROR):
            commit()
        else:
            self._guarded(lambda: self._run(flow(), State.SYNCING))

    def set_mode(self, mode: InteractionMode, on_committed: Optional[Callable[[], None]] = None) -> bool:
        if mode == self.mode:
            if on_committed is not None:
                on_committed()
            return True

        def commit() -> None:
            self._clear_analysis()
            self.mode = mode
            self._analysis_enabled = False
            self._pending_opening_ai = False
            if on_committed is not None:
                on_committed()
            self.game_changed.emit()

        if self.state in (State.UNCONFIGURED, State.ERROR):
            commit()
            return True
        return self._guarded(commit)

    def board_play(self, move: Move) -> bool:
        if not self.can_board_play():
            if self.game.finished:
                self.message.emit(tr("对局已结束"))
            elif self.mode == InteractionMode.PLAY and self.state in (State.READY, State.ANALYZING):
                self.message.emit(tr("现在轮到 AI 行棋"))
            return False
        color = self.game.to_move if self.mode == InteractionMode.ANALYSIS else self.game.human_color
        try:
            self.game.check(color, move)
        except IllegalMove as e:
            self.message.emit(tr("非法着法：{0}", e))
            return False
        auto_reply = self.mode == InteractionMode.PLAY
        return self._guarded(lambda: self._play_now(move, auto_reply))

    def human_play(self, move: Move) -> bool:
        return self.board_play(move)

    def _play_now(self, move: Move, auto_reply: bool) -> None:
        if not self.can_board_play():
            return
        color = self.game.to_move
        previous = (self.game, self.game.dirty, self.game.result, self.game.result_note)
        try:
            self.game.play(color, move)
        except IllegalMove as e:
            self.message.emit(tr("非法着法：{0}", e))
            return
        self._pending_move = previous
        self._clear_analysis()
        self.game_changed.emit()

        def flow() -> Flow:
            r = yield Cmd(f"play {color} {to_gtp(move, self.game.size)}")
            if not r.ok:
                self._rollback_pending_move()
                raise FlowError(tr("引擎拒绝了该着法：{0}", r.text))
            self._pending_move = None
            self._position_revision += 1
            if self.game.ended_by_passes:
                yield from self._score_flow()
                return
            if auto_reply:
                yield from self._genmove_flow()

        self._run(flow(), State.AI_THINKING if auto_reply else State.SYNCING)

    def human_pass(self) -> bool:
        return self.board_play(None)

    def ai_move(self) -> bool:
        if self.mode == InteractionMode.ANALYSIS:
            self.message.emit(tr("AI 分析模式不会自动续弈"))
            return False
        if not self.can_ai_move():
            return False
        return self._guarded(lambda: self._run(self._genmove_flow(), State.AI_THINKING) if self.can_ai_move() else None)

    def _genmove_flow(self) -> Flow:
        self._clear_analysis()
        g = self.game
        color = g.ai_color
        self.message.emit(tr("AI 思考中…"))
        timeout = get_preset(self.strength_key).max_time + launch.SEARCH_GRACE_S
        r = yield Cmd(f"genmove {color}", timeout, SEARCH_TIMEOUT)
        if not r.ok:
            raise EngineDiverged(tr("AI 落子失败：{0}", r.text))
        text = r.text.strip()
        if text.lower() == "resign":
            g.set_result(f"{other(color)}+R")
            self._position_revision += 1
            self.message.emit(tr("AI（{0}）认输", color_name(color)))
            return
        try:
            mv = from_gtp(text, g.size)
        except ValueError as e:
            raise EngineDiverged(tr("AI 返回了无法识别的着法：{0}", e)) from None
        try:
            g.play(color, mv)
        except IllegalMove as e:
            raise EngineDiverged(tr("AI 返回的着法 {0} 在本地判定为非法（{1}），棋局可能已不同步", text, e)) from None
        self._position_revision += 1
        self.message.emit(tr("AI 落子：{0}", tr("停一手") if mv is None else text))
        if g.ended_by_passes:
            yield from self._score_flow()

    def _score_flow(self) -> Flow:
        r = yield Cmd("final_score", 60.0)
        if r.ok and r.text.strip() and r.text.strip() != "?":
            res = r.text.strip()
            self.game.set_result("0" if res == "0" else res)
            self.message.emit(tr("双方停一手，对局结束：{0}", format_result(res)))
        else:
            self.game.set_result("", tr("已终局，但引擎未能给出计分结果"))
            self.message.emit(tr("双方停一手，对局结束，但没有计分结果"))

    def resign(self) -> bool:
        if self.mode != InteractionMode.PLAY or not self.can_human_play():
            return False

        def act() -> None:
            self.game.set_result(f"{self.game.ai_color}+R")
            self._position_revision += 1
            self._clear_analysis()
            self.message.emit(tr("你已认输"))
            self._set_state(State.GAME_OVER)
            self.game_changed.emit()

        return self._guarded(act)

    def undo(self) -> bool:
        if not self.can_undo():
            return False
        return self._guarded(self._undo_now)

    def _undo_now(self) -> None:
        n = 1 if self.mode == InteractionMode.ANALYSIS else self.game.undo_count_for_human()
        if n == 0:
            return
        self._clear_analysis()
        g = self.game
        to_undo = g.moves[-n:]

        def flow() -> Flow:
            done = 0
            for _ in range(n):
                r = yield Cmd("undo")
                if not r.ok:
                    # Restore the engine to the unchanged local position.
                    for m in to_undo[len(to_undo) - done:]:
                        rr = yield Cmd(f"play {m.color} {to_gtp(m.move, g.size)}")
                        if not rr.ok:
                            raise EngineDiverged(tr("悔棋失败且无法恢复引擎局面：{0}", rr.text))
                    raise FlowError(tr("引擎拒绝悔棋：{0}", r.text))
                done += 1
            for _ in range(n):
                g.undo()
            self._position_revision += 1
            self.message.emit(tr("已悔棋 {0} 手", n))

        self._run(flow(), State.SYNCING)

    # -------------------------------------------------------------- analysis
    def start_analysis(self) -> bool:
        """Start analysing; it keeps running and follows later positions until stop_analysis()."""
        if not self.supports_analysis:
            self._report(tr("当前引擎不支持 kata-analyze，无法进行局面分析"))
            return False
        if not self.can_analyze():
            return False
        self._analysis_enabled = True
        return self._begin_analysis()

    def _begin_analysis(self) -> bool:
        self._analysis_started = time.monotonic()
        self._analysis_revision = self._position_revision
        self._analysis_stopping = False
        self._clear_analysis()
        try:
            self.engine.start_analysis(self.game.to_move, ANALYSIS_REPORT_CS, ANALYSIS_MAX_MOVES)
        except RuntimeError as e:
            self._analysis_enabled = False
            self._report(tr("无法开始分析：{0}", e))
            return False
        self._set_state(State.ANALYZING)
        return True

    def stop_analysis(self) -> None:
        """User stop: end the running analysis and do not resume it after later moves."""
        self._analysis_enabled = False
        self._halt_analysis()

    def _halt_analysis(self) -> None:
        if self.state == State.ANALYZING and not self._analysis_stopping:
            self._analysis_stopping = True
            self.engine.stop_analysis()
            self.state_changed.emit(self.state)

    def _resume_analysis_later(self) -> None:
        if self._analysis_enabled:
            QTimer.singleShot(0, self._resume_analysis)

    def _resume_analysis(self) -> None:
        if self._analysis_enabled and self._flow is None and self.can_analyze():
            self._begin_analysis()

    def _on_analysis_update(self, snap: AnalysisSnapshot) -> None:
        if self.state != State.ANALYZING:
            return
        for candidate in snap.candidates:
            if snap.root_visits and candidate.visits > snap.root_visits:
                self._report(tr("分析数据无效：候选 {0} 的访问数超过根节点访问数", candidate.move))
                self.stop_analysis()
                return
            if candidate.move.lower() == "pass":
                continue
            try:
                point = from_gtp(candidate.move, self.game.size)
            except ValueError as e:
                self._report(tr("分析数据包含无效坐标 {0}：{1}", candidate.move, e))
                self.stop_analysis()
                return
            if point is None:
                self._report(tr("分析数据包含无效坐标：{0}", candidate.move))
                self.stop_analysis()
                return
        elapsed = time.monotonic() - self._analysis_started
        if self._analysis_revision != self._position_revision:
            return
        self.analysis = AnalysisResult(
            snap, self.game.to_move, len(self.game.moves), elapsed, self._analysis_revision
        )
        self.analysis_changed.emit(self.analysis)

    def _on_analysis_finished(self, ok: bool, err: str) -> None:
        if self.state != State.ANALYZING:
            return
        requested = self._analysis_stopping
        self._analysis_stopping = False
        if not ok or not requested:
            # The engine ended the stream by itself: do not restart it in a loop.
            self._analysis_enabled = False
        self._set_state(self._resting_state())
        if not ok:
            self._report(tr("分析失败：{0}", err))
        pending, self._after_analysis = self._after_analysis, None
        if pending is not None:
            pending()
        else:
            self.message.emit(tr("分析已停止") if self.analysis is not None
                              else tr("分析已停止，未收到分析结果"))
        self._resume_analysis_later()

    def _clear_analysis(self) -> None:
        if self.analysis is not None:
            self.analysis = None
            self.analysis_changed.emit(None)


def format_result(res: str) -> str:
    if not res:
        return tr("无结果")
    if res in ("0", "Draw", "D"):
        return tr("和棋")
    if "+" in res:
        c, _, v = res.partition("+")
        who = tr("黑") if c.upper() == "B" else tr("白") if c.upper() == "W" else c
        if v.upper() in ("R", "RESIGN"):
            return tr("{0}中盘胜", who)
        if v.upper() in ("T", "TIME"):
            return tr("{0}超时胜", who)
        if v == "":
            return tr("{0}胜", who)
        return tr("{0}胜 {1} 目", who, v)
    return res
