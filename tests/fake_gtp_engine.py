"""A tiny scripted GTP engine used by tests. Behaviour flags come from FAKE_GTP_BEHAVIOR (comma separated)."""
from __future__ import annotations

import os
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from katago_gui.go.coords import from_gtp, other, to_gtp  # noqa: E402
from katago_gui.go.game import GameRecord  # noqa: E402
from katago_gui.go.board import IllegalMove  # noqa: E402

FLAGS = set(filter(None, os.environ.get("FAKE_GTP_BEHAVIOR", "").split(",")))
COMMANDS = ["protocol_version", "name", "version", "list_commands", "quit", "boardsize", "clear_board", "komi",
             "play", "undo", "genmove", "final_score", "kata-set-rules", "kata-set-param", "kata-analyze"]
if "no_analyze" in FLAGS:
    COMMANDS.remove("kata-analyze")

out_lock = threading.Lock()


def emit(text: str) -> None:
    with out_lock:
        sys.stdout.write(text)
        sys.stdout.flush()


def respond(cid: str, ok: bool, body: str = "") -> None:
    emit(f"{'=' if ok else '?'}{cid} {body}".rstrip() + "\n\n")


class Engine:
    def __init__(self) -> None:
        self.game = GameRecord(size=19)
        self.undos = 0
        self.started = False

    def run(self) -> None:
        if "exit_on_start" in FLAGS:
            sys.stderr.write("fatal: cannot load model\n")
            sys.exit(2)
        pending = None
        while True:
            line = pending if pending is not None else sys.stdin.readline()
            pending = None
            if not line:
                return
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            cid = ""
            if parts[0].isdigit():
                cid, parts = parts[0], parts[1:]
            cmd, args = parts[0], parts[1:]
            if not self.started:
                self.started = True
                if "slow_start" in FLAGS:
                    sys.stderr.write("Tuning...\n")
                    sys.stderr.flush()
                    time.sleep(1.0)
            if cmd == "kata-analyze" and "kata-analyze" in COMMANDS:
                pending = self.analyze(cid, args)
                continue
            if cmd == "quit":
                respond(cid, True)
                return
            self.handle(cid, cmd, args)

    def handle(self, cid: str, cmd: str, args: list[str]) -> None:
        g = self.game
        if cmd not in COMMANDS:
            respond(cid, False, "unknown command")
        elif cmd == "protocol_version":
            respond(cid, True, "2")
        elif cmd == "name":
            respond(cid, True, "FakeGo")
        elif cmd == "version":
            respond(cid, True, "0.1")
        elif cmd == "list_commands":
            respond(cid, True, "\n".join(COMMANDS))
        elif cmd == "boardsize":
            self.game = GameRecord(size=int(args[0]))
            respond(cid, True)
        elif cmd == "clear_board":
            self.game = GameRecord(size=g.size)
            respond(cid, True)
        elif cmd in ("komi", "kata-set-rules", "kata-set-param"):
            if cmd == "kata-set-param" and "reject_param" in FLAGS:
                respond(cid, False, "cannot set parameter")
                return
            respond(cid, True)
        elif cmd == "play":
            if "crash_on_play" in FLAGS:
                sys.exit(4)
            if "reject_play" in FLAGS and len(g.moves) > 0:
                respond(cid, False, "illegal move")
                return
            try:
                color = args[0].upper()[0]
                if color != g.to_move:
                    raise ValueError("wrong color")
                g.play(color, from_gtp(args[1], g.size))
                respond(cid, True)
            except (ValueError, IllegalMove) as e:
                respond(cid, False, f"illegal move {e}")
        elif cmd == "undo":
            self.undos += 1
            if "reject_undo" in FLAGS or ("reject_second_undo" in FLAGS and self.undos % 2 == 0) or not g.moves:
                respond(cid, False, "cannot undo")
            else:
                g.undo()
                respond(cid, True)
        elif cmd == "genmove":
            color = args[0].upper()[0]
            if "crash_on_genmove" in FLAGS:
                sys.exit(3)
            if "slow_genmove" in FLAGS:
                time.sleep(60)
            if "genmove_resign" in FLAGS:
                respond(cid, True, "resign")
                return
            if "genmove_illegal" in FLAGS and g.moves and g.moves[0].move is not None:
                respond(cid, True, to_gtp(g.moves[0].move, g.size))
                return
            if "genmove_pass" in FLAGS:
                g.play(color, None)
                respond(cid, True, "pass")
                return
            for y in range(g.size):
                for x in range(g.size):
                    if g.is_legal(color, (x, y)):
                        g.play(color, (x, y))
                        respond(cid, True, to_gtp((x, y), g.size))
                        return
            g.play(color, None)
            respond(cid, True, "pass")
        elif cmd == "final_score":
            if "fail_final_score" in FLAGS:
                respond(cid, False, "cannot score")
            else:
                respond(cid, True, "W+7.5")

    def analyze(self, cid: str, args: list[str]):
        if "wrong_analysis_id" in FLAGS:
            cid = str(int(cid) + 1)
        emit(f"={cid}\n")
        stop = threading.Event()
        holder: dict = {}

        def reader() -> None:
            holder["line"] = sys.stdin.readline()
            stop.set()

        threading.Thread(target=reader, daemon=True).start()
        visits = 0
        g = self.game
        empties = [(x, y) for y in range(g.size) for x in range(g.size) if not g.board.get((x, y))][:3]
        while not stop.wait(0.05):
            if "silent_analysis" in FLAGS:
                continue
            visits += 10
            parts = []
            for i, p in enumerate(empties):
                mv = to_gtp(p, g.size)
                parts.append(f"info move {mv} visits {visits // (i + 1)} winrate {0.6 - 0.1 * i:.3f} "
                             f"scoreLead {2.5 - i:.1f} prior 0.1 order {i} pv {mv} {to_gtp(empties[-1], g.size)}")
            emit(" ".join(parts) + f" rootInfo visits {visits} winrate 0.6 scoreLead 2.5\n")
        if "slow_analysis_stop" in FLAGS:
            time.sleep(0.25)
        emit("\n")
        line = holder.get("line", "")
        return line if line.strip() else None


if __name__ == "__main__":
    Engine().run()
