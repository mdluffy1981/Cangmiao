from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .go.board import Board
from .go.coords import Move, Point, from_sgf, other
from .go.game import SUPPORTED_SIZES
from .i18n import tr
from .sgf import SgfError, _Parser, decode_bytes


@dataclass
class TsumegoNode:
    color: str
    move: Move
    comment: str = ""
    accepted: bool = True
    children: list[TsumegoNode] = field(default_factory=list)


@dataclass
class TsumegoProblem:
    title: str
    size: int
    to_move: str
    board: Board
    root: TsumegoNode


def _prop(node, name: str) -> str | None:
    prop = node.props.get(name)
    if prop is None:
        return None
    if len(prop.values) != 1:
        raise SgfError(tr("属性 {0} 必须只有一个值", name), prop.line, prop.col)
    return prop.values[0]


def _setup_points(values: list[str], size: int, name: str) -> list[Point]:
    result: list[Point] = []
    for value in values:
        points = value.split(":")
        if len(points) == 1:
            try:
                point = from_sgf(value, size)
            except ValueError as e:
                raise SgfError(str(e)) from None
            if point is None:
                raise SgfError(tr("{0} 属性不能包含停一手", name))
            result.append(point)
            continue
        if len(points) != 2:
            raise SgfError(tr("{0} 属性包含无效区域：{1}", name, value))
        try:
            start = from_sgf(points[0], size)
            end = from_sgf(points[1], size)
        except ValueError as e:
            raise SgfError(str(e)) from None
        if start is None or end is None:
            raise SgfError(tr("{0} 属性包含无效区域：{1}", name, value))
        result.extend(
            (x, y)
            for y in range(min(start[1], end[1]), max(start[1], end[1]) + 1)
            for x in range(min(start[0], end[0]), max(start[0], end[0]) + 1)
        )
    return result


def _append_tree(tree, parent: TsumegoNode, size: int) -> None:
    current = parent
    for index, node in enumerate(tree.nodes):
        if index and any(name in node.props for name in ("AB", "AW", "AE", "PL")):
            raise SgfError(tr("摆子和指定行棋方属性只支持出现在根节点"), node.line, node.col)
        has_black, has_white = "B" in node.props, "W" in node.props
        if has_black and has_white:
            raise SgfError(tr("同一节点同时包含黑白着手"), node.line, node.col)
        if not (has_black or has_white):
            continue
        color = "B" if has_black else "W"
        prop = node.props[color]
        if len(prop.values) != 1:
            raise SgfError(tr("属性 {0} 必须只有一个值", color), prop.line, prop.col)
        try:
            move = from_sgf(prop.values[0].strip(), size)
        except ValueError as e:
            raise SgfError(str(e), prop.line, prop.col) from None
        if move is None:
            raise SgfError(tr("死活题答案不能包含停一手"), prop.line, prop.col)
        comment_prop = node.props.get("C")
        comment = " ".join(comment_prop.values) if comment_prop else ""
        lowered = comment.casefold()
        accepted = not any(word in lowered for word in ("wrong", "incorrect", "错误", "不正确"))
        step = TsumegoNode(color, move, comment, accepted)
        current.children.append(step)
        current = step
    for child in tree.children:
        _append_tree(child, current, size)


def _validate_turns(node: TsumegoNode, expected: str) -> None:
    for step in node.children:
        if step.color != expected:
            raise SgfError(tr("答案着手颜色不交替，应为{0}方", tr("黑" if expected == "B" else "白")))
        _validate_turns(step, other(expected))


def parse_tsumego(text: str, source_name: str = "") -> list[TsumegoProblem]:
    trees = _Parser(text).collection()
    problems: list[TsumegoProblem] = []
    for index, tree in enumerate(trees, 1):
        root = tree.nodes[0]
        size_text = _prop(root, "SZ")
        try:
            size = int(size_text) if size_text else 19
        except ValueError:
            prop = root.props["SZ"]
            raise SgfError(tr("无效的棋盘尺寸：SZ[{0}]", size_text), prop.line, prop.col) from None
        if size not in SUPPORTED_SIZES:
            prop = root.props.get("SZ")
            raise SgfError(tr("不支持的棋盘尺寸 {0}（仅支持 9/13/19 路）", size),
                           prop.line if prop else root.line, prop.col if prop else root.col)

        grid = [["" for _ in range(size)] for _ in range(size)]
        for color, name in (("B", "AB"), ("W", "AW")):
            prop = root.props.get(name)
            if prop is None:
                continue
            for x, y in _setup_points(prop.values, size, name):
                if grid[y][x]:
                    raise SgfError(tr("摆子位置重复或黑白重叠：{0}", prop.values[0]), prop.line, prop.col)
                grid[y][x] = color

        answer_root = TsumegoNode("", None)
        _append_tree(tree, answer_root, size)
        first = answer_root.children[0] if answer_root.children else None
        to_move = _prop(root, "PL") or (first.color if first else "B")
        if to_move not in ("B", "W"):
            prop = root.props.get("PL")
            raise SgfError(tr("PL 必须是 B 或 W"), prop.line if prop else root.line,
                           prop.col if prop else root.col)
        _validate_turns(answer_root, to_move)
        title = _prop(root, "GN") or (Path(source_name).stem if source_name else tr("题目 {0}", index))
        if len(trees) > 1:
            title = tr("{0} · {1}", title, index)
        if not answer_root.children:
            raise SgfError(tr("题目没有答案着手"), root.line, root.col)
        board = Board(size, tuple(tuple(row) for row in grid))
        problems.append(TsumegoProblem(title, size, to_move, board, answer_root))
    return problems


def load_tsumego(path: str | Path) -> list[TsumegoProblem]:
    source = Path(path)
    return parse_tsumego(decode_bytes(source.read_bytes()), source.name)
