"""Pure GTP / KataGo output parsing (no Qt)."""
from __future__ import annotations

import re
import math
from dataclasses import dataclass, field
from typing import Optional

RESPONSE_HEAD = re.compile(r"^([=?])(\d*)\s?(.*)$")


@dataclass
class GtpResponse:
    ok: bool
    id: Optional[int]
    text: str

    @property
    def error(self) -> str:
        return "" if self.ok else self.text


class GtpParseError(Exception):
    pass


def parse_response(lines: list[str]) -> GtpResponse:
    """Parse a complete response block (without the terminating blank line)."""
    if not lines:
        raise GtpParseError("空响应")
    m = RESPONSE_HEAD.match(lines[0])
    if not m:
        raise GtpParseError(f"无法解析的 GTP 响应：{lines[0]!r}")
    rid = int(m.group(2)) if m.group(2) else None
    body = "\n".join([m.group(3)] + lines[1:]).strip()
    return GtpResponse(m.group(1) == "=", rid, body)


class ResponseAssembler:
    """Accumulates stdout lines into GTP response blocks."""

    def __init__(self) -> None:
        self._buf: list[str] = []

    def feed(self, line: str) -> Optional[list[str]]:
        line = line.rstrip("\r\n").replace("\t", " ")
        if line.strip() == "":
            if self._buf:
                block, self._buf = self._buf, []
                return block
            return None
        if not self._buf and not RESPONSE_HEAD.match(line):
            return None  # stray output before a response header
        self._buf.append(line)
        return None

    def reset(self) -> None:
        self._buf = []


@dataclass
class CandidateMove:
    move: str
    visits: int
    winrate: float  # side-to-move perspective as reported
    score_lead: float
    prior: float
    order: int
    pv: list[str] = field(default_factory=list)


@dataclass
class AnalysisSnapshot:
    candidates: list[CandidateMove]
    root_visits: int = 0
    root_winrate: Optional[float] = None  # side to move
    root_score_lead: Optional[float] = None


def _parse_fields(tokens: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    i = 0
    while i + 1 < len(tokens):
        key, val = tokens[i], tokens[i + 1]
        out[key] = val
        i += 2
    return out


def parse_analysis_line(line: str) -> Optional[AnalysisSnapshot]:
    """Parse a kata-analyze output line ('info move ... pv ... info move ... rootInfo ...')."""
    line = line.strip()
    if not line.startswith("info") and not line.startswith("rootInfo"):
        return None
    candidates: list[CandidateMove] = []
    snap = AnalysisSnapshot(candidates)
    # Split into segments at 'info' / 'rootInfo' keywords.
    segments: list[tuple[str, list[str]]] = []
    for tok in line.split():
        if tok in ("info", "rootInfo", "ownership", "ownershipStdev", "movesOwnership"):
            segments.append((tok, []))
        elif segments:
            segments[-1][1].append(tok)
    for kind, toks in segments:
        if kind == "info":
            pv: list[str] = []
            if "pv" in toks:
                idx = toks.index("pv")
                pv = toks[idx + 1:]
                toks = toks[:idx]
            f = _parse_fields(toks)
            try:
                candidates.append(CandidateMove(
                    move=f["move"],
                    visits=int(f["visits"]),
                    winrate=float(f["winrate"]),
                    score_lead=float(f["scoreLead"] if "scoreLead" in f else f["scoreMean"]),
                    prior=float(f.get("prior", 0)),
                    order=int(f.get("order", len(candidates))),
                    pv=pv,
                ))
            except (KeyError, ValueError) as e:
                raise GtpParseError(f"候选着法字段无效：{e}") from e
        elif kind == "rootInfo":
            f = _parse_fields(toks)
            try:
                snap.root_visits = int(f.get("visits", 0))
                if "winrate" in f:
                    snap.root_winrate = float(f["winrate"])
                if "scoreLead" in f:
                    snap.root_score_lead = float(f["scoreLead"])
            except ValueError as e:
                raise GtpParseError(f"根节点分析字段无效：{e}") from e
    for c in candidates:
        if (c.visits < 0 or c.order < 0 or not 0 <= c.winrate <= 1
                or not math.isfinite(c.score_lead) or not 0 <= c.prior <= 1):
            raise GtpParseError(f"候选着法 {c.move} 的数值超出范围")
    if (snap.root_visits < 0
            or (snap.root_winrate is not None and not 0 <= snap.root_winrate <= 1)
            or (snap.root_score_lead is not None and not math.isfinite(snap.root_score_lead))):
        raise GtpParseError("根节点分析数值超出范围")
    candidates.sort(key=lambda c: c.order)
    if not snap.root_visits:
        snap.root_visits = sum(c.visits for c in candidates)
    if snap.root_winrate is None and candidates:
        snap.root_winrate = candidates[0].winrate
        snap.root_score_lead = candidates[0].score_lead
    return snap
