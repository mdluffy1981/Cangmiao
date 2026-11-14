"""SGF (FF[4]) reading and writing for the main line of a single game."""
from __future__ import annotations

import datetime as _dt
import math
import re
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .go.board import IllegalMove
from .go.coords import from_sgf, to_sgf
from .go.game import SUPPORTED_SIZES, GameRecord
from .go.rules import get_rules, rules_from_sgf
from . import APP_NAME, __version__
from .paths import atomic_write_text
from .i18n import tr

AI_NAME = "KataGo"

# Properties that are understood or harmless metadata; anything else produces a warning.
_USED = {"GM", "FF", "CA", "SZ", "KM", "RU", "PB", "PW", "DT", "RE", "AP", "B", "W"}
_ROOT_ONLY = _USED - {"B", "W"}


class SgfError(Exception):
    def __init__(self, message: str, line: int = 0, col: int = 0):
        self.message, self.line, self.col = message, line, col
        loc = tr("第 {0} 行第 {1} 列：", line, col) if line else ""
        super().__init__(loc + message)


@dataclass
class _Prop:
    name: str
    values: list[str]
    line: int
    col: int


@dataclass
class _Node:
    props: "OrderedDict[str, _Prop]"
    line: int
    col: int


@dataclass
class _Tree:
    nodes: list[_Node] = field(default_factory=list)
    children: list["_Tree"] = field(default_factory=list)


@dataclass
class LoadResult:
    game: GameRecord
    warnings: list[str]


class _Parser:
    def __init__(self, text: str):
        self.s = text
        self.i = 0
        self.line = 1
        self.col = 1

    def _adv(self, n: int = 1) -> None:
        for _ in range(n):
            if self.i < len(self.s):
                if self.s[self.i] == "\n":
                    self.line += 1
                    self.col = 1
                else:
                    self.col += 1
                self.i += 1

    def _ws(self) -> None:
        while self.i < len(self.s) and self.s[self.i].isspace():
            self._adv()

    def _peek(self) -> str:
        return self.s[self.i] if self.i < len(self.s) else ""

    def err(self, msg: str) -> SgfError:
        return SgfError(msg, self.line, self.col)

    def collection(self) -> list[_Tree]:
        trees = []
        if self._peek() == "\ufeff":
            self._adv()
        self._ws()
        if self._peek() != "(":
            raise self.err(tr("应为 SGF 起始符“(”，不允许棋谱外的内容"))
        while True:
            self._ws()
            if self._peek() != "(":
                break
            trees.append(self.tree())
        self._ws()
        if not trees:
            raise self.err(tr("SGF 中没有棋谱"))
        if self._peek():
            raise self.err(tr("棋谱结束后存在多余内容"))
        return trees

    def tree(self, depth: int = 0) -> _Tree:
        if depth > 100:
            raise self.err(tr("变化分支嵌套过深（最多 100 层）"))
        if self._peek() != "(":
            raise self.err(tr("应为“(”"))
        self._adv()
        t = _Tree()
        self._ws()
        while self._peek() == ";":
            t.nodes.append(self.node())
            self._ws()
        if not t.nodes:
            raise self.err(tr("变化分支中没有节点"))
        while self._peek() == "(":
            t.children.append(self.tree(depth + 1))
            self._ws()
        if self._peek() != ")":
            raise self.err(tr("应为“)”，棋谱可能被截断或格式损坏"))
        self._adv()
        return t

    def node(self) -> _Node:
        n = _Node(OrderedDict(), self.line, self.col)
        self._adv()  # ';'
        self._ws()
        while self._peek() and "A" <= self._peek() <= "Z":
            pl, pc = self.line, self.col
            name = ""
            while self._peek() and "A" <= self._peek() <= "Z":
                name += self._peek()
                self._adv()
            if not name:
                raise self.err(tr("属性名必须包含大写字母"))
            self._ws()
            values = []
            while self._peek() == "[":
                values.append(self.value())
                self._ws()
            if not values:
                raise self.err(tr("属性 {0} 缺少值", name))
            if name in n.props:
                raise SgfError(tr("节点中重复的属性 {0}", name), pl, pc)
            n.props[name] = _Prop(name, values, pl, pc)
        return n

    def value(self) -> str:
        self._adv()  # '['
        out = []
        while True:
            c = self._peek()
            if c == "":
                raise self.err(tr("属性值缺少结束符“]”"))
            if c == "\\":
                self._adv()
                nxt = self._peek()
                if nxt == "":
                    raise self.err(tr("属性值缺少结束符“]”"))
                if nxt not in "\r\n":
                    out.append(nxt)
                self._adv()
                if nxt in "\r\n" and self._peek() in ("\n" if nxt == "\r" else "\r",):
                    self._adv()
                continue
            if c == "]":
                self._adv()
                return "".join(out)
            out.append(c)
            self._adv()


def decode_bytes(data: bytes) -> str:
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    parser = _Parser(data.decode("latin-1"))
    parser._ws()
    if parser._peek() != "(":
        raise parser.err(tr("应为 SGF 起始符“(”"))
    parser._adv()
    parser._ws()
    if parser._peek() != ";":
        raise parser.err(tr("棋谱缺少根节点"))
    encoding = parser.node().props.get("CA")
    if encoding:
        enc = encoding.values[0].strip()
        try:
            return data.decode(enc)
        except (LookupError, UnicodeError) as e:
            raise SgfError(tr("无法按 CA[{0}] 解码：{1}", enc, e), encoding.line, encoding.col) from e
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        try:
            return data.decode("gb18030")
        except UnicodeDecodeError as e:
            raise SgfError(tr("文件既不是 UTF-8 也不是 GB18030（字节 {0}）", e.start)) from e


def parse_sgf(text: str) -> LoadResult:
    trees = _Parser(text).collection()
    warnings: list[str] = []
    if len(trees) > 1:
        warnings.append(tr("文件包含 {0} 局棋谱，只读取第一局", len(trees)))
    tree = trees[0]
    main: list[_Node] = []
    t: Optional[_Tree] = tree
    skipped = 0
    while t is not None:
        main.extend(t.nodes)
        if len(t.children) > 1:
            skipped += len(t.children) - 1
        t = t.children[0] if t.children else None
    if skipped:
        warnings.append(tr("忽略了 {0} 个变化分支，只读取主变化线", skipped))

    root = main[0]
    rp = root.props
    for node in main:
        for name, p in node.props.items():
            if name in _USED | {"PL", "HA"} and len(p.values) != 1:
                raise SgfError(tr("属性 {0} 必须只有一个值", name), p.line, p.col)
            if node is not root and name in _ROOT_ONLY:
                raise SgfError(tr("属性 {0} 只支持出现在根节点", name), p.line, p.col)

    def single(name: str) -> Optional[str]:
        p = rp.get(name)
        return p.values[0] if p else None

    gm = single("GM")
    if gm is not None and gm.strip() != "1":
        raise SgfError(tr("不是围棋棋谱（GM 不为 1）"), rp["GM"].line, rp["GM"].col)
    ff = single("FF")
    if ff is not None and ff not in ("3", "4"):
        raise SgfError(tr("不支持 SGF 版本 FF[{0}]", ff), rp["FF"].line, rp["FF"].col)

    sz_raw = single("SZ")
    size = 19
    if sz_raw is not None:
        p = rp["SZ"]
        if ":" in sz_raw:
            raise SgfError(tr("不支持非正方形棋盘：SZ[{0}]", sz_raw), p.line, p.col)
        try:
            size = int(sz_raw.strip())
        except ValueError:
            raise SgfError(tr("无效的棋盘尺寸：SZ[{0}]", sz_raw), p.line, p.col) from None
        if size not in SUPPORTED_SIZES:
            raise SgfError(tr("不支持的棋盘尺寸 {0}（仅支持 9/13/19 路）", size), p.line, p.col)

    rules_key = "chinese"
    ru = single("RU")
    if ru is not None:
        rs = rules_from_sgf(ru)
        if rs is None:
            warnings.append(tr("不支持的规则“{0}”，改用中国规则", ru))
        else:
            rules_key = rs.key

    komi = get_rules(rules_key).default_komi
    km = single("KM")
    if km is not None:
        try:
            komi = float(km)
        except ValueError:
            p = rp["KM"]
            raise SgfError(tr("无效的贴目：KM[{0}]", km), p.line, p.col) from None
        if not math.isfinite(komi) or abs(komi) > 150 or not (komi * 2).is_integer():
            p = rp["KM"]
            raise SgfError(tr("贴目必须是 0.5 的整数倍：KM[{0}]", km), p.line, p.col)

    pb, pw = single("PB") or "", single("PW") or ""
    human = "B"
    if AI_NAME.lower() in pw.lower() and AI_NAME.lower() not in pb.lower():
        human = "B"
    elif AI_NAME.lower() in pb.lower() and AI_NAME.lower() not in pw.lower():
        human = "W"
    elif pb or pw:
        warnings.append(tr("无法从对局者姓名判断 AI 执色，默认人类执黑"))

    game = GameRecord(size=size, rules_key=rules_key, komi=komi, human_color=human,
                      black_name=pb, white_name=pw, date=single("DT") or "")

    ignored: "OrderedDict[str, tuple[int, int]]" = OrderedDict()
    for idx, node in enumerate(main):
        for name, p in node.props.items():
            if name in ("AB", "AW", "AE"):
                raise SgfError(tr("不支持摆子/让子局面（AB/AW/AE 属性）"), p.line, p.col)
            if name == "HA" and p.values[0].strip() not in ("", "0"):
                raise SgfError(tr("不支持让子局（HA 属性）"), p.line, p.col)
            if name == "PL":
                raise SgfError(tr("不支持指定行棋方（PL 属性）；仅支持黑先、黑白交替"), p.line, p.col)
            if name in _USED or name == "HA":
                if idx > 0 and name not in ("B", "W"):
                    ignored.setdefault(name, (p.line, p.col))
                continue
            ignored.setdefault(name, (p.line, p.col))
        has_b, has_w = "B" in node.props, "W" in node.props
        if has_b and has_w:
            raise SgfError(tr("同一节点同时包含黑白着手"), node.line, node.col)
        if not (has_b or has_w):
            continue
        color = "B" if has_b else "W"
        p = node.props[color]
        if color != game.to_move:
            raise SgfError(tr("着手颜色不交替：第 {0} 手应为{1}方", len(game.moves) + 1,
                              tr("黑") if game.to_move == "B" else tr("白")),
                           p.line, p.col)
        try:
            mv = from_sgf(p.values[0].strip(), size)
        except ValueError as e:
            raise SgfError(str(e), p.line, p.col) from None
        try:
            game.play(color, mv)
        except IllegalMove as e:
            raise SgfError(tr("第 {0} 手非法：{1}", len(game.moves) + 1, e), p.line, p.col) from None
    if ignored:
        desc = "、".join(tr("{0}（第 {1} 行）", n, l) for n, (l, _c) in ignored.items())
        warnings.append(tr("以下属性不受支持，将被忽略：{0}", desc))

    re_val = single("RE")
    if re_val:
        if not re.fullmatch(r"(?:0|Draw|Void|\?|[BW]\+(?:[0-9]+(?:\.[0-9]+)?|R|Resign|T|Time|F|Forfeit)?)",
                            re_val.strip()):
            raise SgfError(tr("无效的终局结果 RE[{0}]", re_val), rp["RE"].line, rp["RE"].col)
        game.result = re_val.strip()
    game.dirty = bool(warnings)
    return LoadResult(game, warnings)


def load_sgf(path: str | Path) -> LoadResult:
    data = Path(path).read_bytes()
    return parse_sgf(decode_bytes(data))


def _esc(text: str) -> str:
    return text.replace("\\", "\\\\").replace("]", "\\]")


def game_to_sgf(game: GameRecord) -> str:
    black = game.black_name or ("KataGo" if game.human_color == "W" else tr("人类"))
    white = game.white_name or ("KataGo" if game.human_color == "B" else tr("人类"))
    date = game.date or _dt.date.today().isoformat()
    props = [
        ("GM", "1"), ("FF", "4"), ("CA", "UTF-8"), ("AP", f"{APP_NAME}:{__version__}"),
        ("SZ", str(game.size)), ("KM", f"{game.komi:g}"), ("RU", game.rules.sgf_name),
        ("PB", black), ("PW", white), ("DT", date),
    ]
    if game.result:
        props.append(("RE", game.result))
    out = ["(;" + "".join(f"{k}[{_esc(v)}]" for k, v in props)]
    for i, m in enumerate(game.moves):
        out.append(f";{m.color}[{to_sgf(m.move, game.size)}]")
        if i % 10 == 9:
            out.append("\n")
    out.append(")\n")
    return "".join(out)


def save_sgf(game: GameRecord, path: str | Path) -> None:
    atomic_write_text(Path(path), game_to_sgf(game))
