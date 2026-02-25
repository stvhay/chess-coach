"""Game tree data structures for coaching analysis.

Replaces the flat AnnotatedLine/PlyAnnotation/CoachingContext pipeline
with a tree-based representation. GameNode holds positions with lazy
tactical/positional analysis. GameTree represents the decision point
with played line context, player move, and engine alternatives.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass, field, field as dc_field, replace

import chess

from server.analysis import (
    MateThreat,
    PositionReport,
    TacticalMotifs,
    analyze,
    analyze_material,
    analyze_tactics,
)
from server.elo_profiles import EloProfile
from server.engine import EngineProtocol, Evaluation
from server.motifs import (
    HIGH_VALUE_KEYS,
    MODERATE_VALUE_KEYS,
    MOTIF_REGISTRY,
    motif_labels as _motif_labels,
)


@dataclass
class TeachabilityWeights:
    """Configuration for pedagogical interest scoring."""
    motif_base: dict[str, float] = dc_field(default_factory=dict)
    value_bonus_per_100cp: float = 1.0
    mate_bonus: float = 5.0
    checkmate_bonus: float = 100.0
    sacrifice_bonus: float = 4.0
    positional_bonus: float = 1.0
    deep_only_penalty: float = -2.0
    eval_loss_penalty: float = -3.0
    unsound_penalty: float = 0.0


DEFAULT_WEIGHTS = TeachabilityWeights(
    motif_base={
        "pin": 3.0,
        "fork": 3.0,
        "skewer": 3.0,
        "hanging": 3.0,
        "discovered": 3.0,
        "double_check": 3.0,
        "trapped": 3.0,
        "mate_threat": 3.0,
        "back_rank": 2.0,
        "xray": 2.0,
        "exposed_king": 2.0,
        "overloaded": 2.0,
        "capturable_defender": 2.0,
    },
)


@dataclass
class GameNode:
    """A single position in the game tree.

    Holds a board, the move that reached it, parent/child links,
    and lazy-computed analysis caches.
    """
    board: chess.Board
    move: chess.Move | None = None          # None for root
    parent: GameNode | None = field(default=None, repr=False)
    children: list[GameNode] = field(default_factory=list)
    source: str = ""                        # "played", "engine", "best"
    score_cp: int | None = None
    score_mate: int | None = None

    # Lazy analysis — computed on first access, cached
    _tactics: TacticalMotifs | None = field(default=None, repr=False)
    _report: PositionReport | None = field(default=None, repr=False)

    @property
    def tactics(self) -> TacticalMotifs:
        """Tactical motifs for this position, computed lazily."""
        if self._tactics is None:
            self._tactics = analyze_tactics(self.board)
        return self._tactics

    @property
    def report(self) -> PositionReport:
        """Full position report, computed lazily."""
        if self._report is None:
            self._report = analyze(self.board)
        return self._report

    @property
    def san(self) -> str:
        """SAN notation of the move that reached this node."""
        if self.move is None:
            return ""
        if self.parent is None:
            return ""
        return self.parent.board.san(self.move)

    @property
    def fullmove_number(self) -> int:
        """The fullmove number of this position."""
        return self.board.fullmove_number

    def add_child(
        self,
        move: chess.Move,
        source: str,
        score_cp: int | None = None,
        score_mate: int | None = None,
    ) -> GameNode:
        """Create a child node, insert maintaining eval-sorted order (best first).

        Sorting: mate scores first (positive mate > negative mate),
        then by score_cp descending. Nodes with no score go last.
        """
        child_board = self.board.copy()
        child_board.push(move)
        child = GameNode(
            board=child_board,
            move=move,
            parent=self,
            source=source,
            score_cp=score_cp,
            score_mate=score_mate,
        )
        # Insert in sorted position (best eval first)
        keys = [_sort_key(c) for c in self.children]
        idx = bisect.bisect_right(keys, _sort_key(child))
        self.children.insert(idx, child)
        return child


def _sort_key(node: GameNode) -> tuple[int, int]:
    """Sort key for eval-sorted order: best (highest) first.

    Returns a tuple that sorts in ascending order, so we negate values
    to get descending (best-first) order.

    Priority: mate-for-us > high cp > low cp > mate-against-us
    """
    if node.score_mate is not None:
        if node.score_mate > 0:
            # Mate in N: lower N is better → negate to sort ascending
            return (0, node.score_mate)
        else:
            # Getting mated: worse → sort after all cp scores
            return (2, -node.score_mate)
    if node.score_cp is not None:
        return (1, -node.score_cp)
    # No score — sort last
    return (3, 0)


@dataclass
class OpponentResponse:
    """A candidate response move by the opponent after the student's move."""
    san: str
    uci: str
    score_cp: int | None
    score_mate: int | None
    description: str      # "captures your knight on c6", "develops bishop to g7"
    is_best: bool         # matches the PV's first move


@dataclass
class GameTree:
    """The coaching game tree rooted at the starting position.

    decision_point is the position where the student moved.
    Children of decision_point include the player's actual move
    and engine alternatives.
    """
    root: GameNode
    decision_point: GameNode
    player_color: chess.Color
    opponent_responses: list[OpponentResponse] = field(default_factory=list)

    def played_line(self) -> list[GameNode]:
        """Return the path from root to decision_point (inclusive)."""
        path: list[GameNode] = []
        node = self.decision_point
        while node is not None:
            path.append(node)
            node = node.parent
        path.reverse()
        return path

    def player_move_node(self) -> GameNode | None:
        """Find the child of decision_point with source='played'."""
        for child in self.decision_point.children:
            if child.source == "played":
                return child
        return None

    def alternatives(self) -> list[GameNode]:
        """Non-played children of decision_point, sorted by eval."""
        return [c for c in self.decision_point.children if c.source != "played"]


def _material_cp(board: chess.Board) -> int:
    """Total material in centipawns from White's perspective."""
    mat = analyze_material(board)
    return (mat.white_total - mat.black_total) * 100


def _detect_sacrifice(nodes: list[GameNode], score_mate: int | None) -> bool:
    """Detect sacrifice pattern: player gives up 200+ cp then line recovers.

    Checks even plies (player moves) for cumulative material loss of 200+ cp.
    The line must end favorably (checkmate or material recovery).
    """
    if not nodes:
        return False

    # Need parent to get starting material
    if nodes[0].parent is None:
        return False

    base_material = _material_cp(nodes[0].parent.board)
    cumulative = 0
    max_deficit = 0
    has_checkmate = False

    for i, node in enumerate(nodes):
        current_material = _material_cp(node.board)
        mat_change = current_material - base_material
        cumulative = mat_change

        # Player plies are even (0, 2, 4...)
        if i % 2 == 0 and cumulative < max_deficit:
            max_deficit = cumulative

        if node.board.is_checkmate():
            has_checkmate = True

    if max_deficit <= -200:
        if has_checkmate or score_mate is not None:
            return True
        if cumulative >= max_deficit + 200:
            return True
    return False


def _add_continuation_children(
    parent_node: GameNode,
    pv_uci: list[str],
    max_ply: int,
) -> list[GameNode]:
    """Add PV continuation moves as children, returning the chain of nodes."""
    nodes: list[GameNode] = []
    current = parent_node
    for uci in pv_uci[:max_ply]:
        try:
            move = chess.Move.from_uci(uci)
            if move not in current.board.legal_moves:
                break
        except (ValueError, chess.InvalidMoveError):
            break
        child = current.add_child(move, source="engine")
        nodes.append(child)
        current = child
    return nodes


_PIECE_NAMES = {
    chess.PAWN: "pawn", chess.KNIGHT: "knight", chess.BISHOP: "bishop",
    chess.ROOK: "rook", chess.QUEEN: "queen", chess.KING: "king",
}

# Piece values for insight targeting (king=0 ensures check is not reported as targeting)
_PIECE_VALUES = {
    chess.QUEEN: 9, chess.ROOK: 5, chess.BISHOP: 3,
    chess.KNIGHT: 3, chess.PAWN: 1, chess.KING: 0,
}


def _describe_opponent_move(board: chess.Board, move: chess.Move, student_is_white: bool) -> str:
    """Generate a short natural-language description of an opponent's move.

    board is the position BEFORE the move is played.
    Includes one notable insight about what the move accomplishes beyond
    the basic action (e.g., what it targets or defends).
    """
    piece_type = board.piece_type_at(move.from_square)
    piece_name = _PIECE_NAMES.get(piece_type, "piece") if piece_type else "piece"
    dest = chess.square_name(move.to_square)

    # Castling
    if board.is_castling(move):
        if chess.square_file(move.to_square) == 6:  # g-file = kingside
            desc = "castles kingside"
        else:
            desc = "castles queenside"
    elif board.is_capture(move):
        captured_sq = move.to_square
        # En passant: captured piece is not on to_square
        if board.is_en_passant(move):
            captured_name = "pawn"
        else:
            captured_type = board.piece_type_at(captured_sq)
            captured_name = _PIECE_NAMES.get(captured_type, "piece") if captured_type else "piece"
        desc = f"captures your {captured_name} on {dest}"
        if move.promotion:
            promo_name = _PIECE_NAMES.get(move.promotion, "piece")
            desc += f", promoting to {promo_name}"
    elif move.promotion:
        promo_name = _PIECE_NAMES.get(move.promotion, "piece")
        desc = f"promotes pawn to {promo_name} on {dest}"
    else:
        # Non-capture, non-special: describe the move
        if piece_type == chess.PAWN:
            desc = f"pushes pawn to {dest}"
        elif piece_type in (chess.KNIGHT, chess.BISHOP) and chess.square_rank(move.from_square) == (0 if not student_is_white else 7):
            desc = f"develops {piece_name} to {dest}"
        else:
            desc = f"moves {piece_name} to {dest}"

    # Check for check
    board_copy = board.copy()
    board_copy.push(move)
    if board_copy.is_check():
        desc += " with check"
    elif not board.is_capture(move):
        # Add insight for non-captures (captures are self-describing)
        insight = _move_insight(board_copy, move, student_is_white)
        if insight:
            desc += f", {insight}"

    return desc


def _move_insight(after_board: chess.Board, move: chess.Move, student_is_white: bool) -> str:
    """Find one notable positional fact about a move.

    after_board is the position AFTER the move is played.
    Returns a short phrase like "targeting your rook on a1" or
    "challenging the center", or empty string if nothing notable.
    """
    to_sq = move.to_square
    # The side that just moved is the opponent of the student
    opponent_color = chess.WHITE if not student_is_white else chess.BLACK

    # 1. Does the piece attack a student's high-value piece?
    attacked = after_board.attacks(to_sq)
    best_target: tuple[int, str] | None = None  # (value, description)
    student_color = chess.WHITE if student_is_white else chess.BLACK
    for sq in attacked:
        piece = after_board.piece_at(sq)
        if piece is None or piece.color != student_color:
            continue
        val = _PIECE_VALUES.get(piece.piece_type, 0)
        if val >= 3:  # only mention bishop+ targets
            name = _PIECE_NAMES.get(piece.piece_type, "piece")
            sq_name = chess.square_name(sq)
            candidate = (val, f"targeting your {name} on {sq_name}")
            if best_target is None or val > best_target[0]:
                best_target = candidate
    if best_target is not None:
        return best_target[1]

    # 2. Does a pawn move challenge the center?
    piece_type = after_board.piece_type_at(to_sq)
    center = {chess.E4, chess.D4, chess.E5, chess.D5}
    if piece_type == chess.PAWN and to_sq in center:
        return "challenging the center"

    # 3. Does the piece defend an attacked friendly piece?
    for sq in attacked:
        piece = after_board.piece_at(sq)
        if piece is None or piece.color != opponent_color:
            continue
        if after_board.is_attacked_by(student_color, sq):
            name = _PIECE_NAMES.get(piece.piece_type, "piece")
            sq_name = chess.square_name(sq)
            return f"defending their {name} on {sq_name}"

    return ""


async def _generate_opponent_responses(
    player_node: GameNode,
    engine: EngineProtocol,
    profile: EloProfile,
    student_is_white: bool,
) -> list[OpponentResponse]:
    """Generate candidate opponent responses after the student's move.

    Runs a screen-pass analysis on the position after the student's move
    and returns the top candidate responses with descriptions.
    """
    board = player_node.board
    fen = board.fen()

    lines = await engine.analyze_lines(
        fen, n=profile.screen_breadth, depth=profile.screen_depth,
    )
    if not lines:
        return []

    # Engine's top line is the best response
    best_uci = lines[0].uci
    best_cp = lines[0].score_cp

    responses: list[OpponentResponse] = []
    for line in lines[:profile.validate_breadth]:
        # Filter out responses significantly worse than the best
        if best_cp is not None and line.score_cp is not None:
            if best_cp - line.score_cp > profile.cp_threshold:
                continue

        try:
            move = chess.Move.from_uci(line.uci)
            if move not in board.legal_moves:
                continue
        except (ValueError, chess.InvalidMoveError):
            continue

        san = board.san(move)
        description = _describe_opponent_move(board, move, student_is_white)
        is_best = (line.uci == best_uci)

        responses.append(OpponentResponse(
            san=san,
            uci=line.uci,
            score_cp=line.score_cp,
            score_mate=line.score_mate,
            description=description,
            is_best=is_best,
        ))

    return responses


async def build_coaching_tree(
    engine: EngineProtocol,
    board_before: chess.Board,
    player_move_uci: str,
    eval_before: Evaluation,
    profile: EloProfile,
) -> GameTree:
    """Build a coaching game tree for the student's move.

    Replaces screen_and_validate + annotate_lines.

    Steps:
    1. Build played-line path from move_stack.
    2. Screen: MultiPV at decision point → engine children.
    3. Rank by teachability → take top candidates.
    4. Validate: deep eval on top candidates → update scores, add continuations.
    5. Annotate player's actual move similarly.
    6. Return GameTree.
    """
    # 1. Build played-line path
    # If board_before has move history, replay from starting position.
    # Otherwise, use board_before directly as root (e.g., FEN-initialized boards).
    if board_before.move_stack:
        root = GameNode(board=chess.Board(), source="played")
        current = root
        for hist_move in board_before.move_stack:
            current = current.add_child(hist_move, source="played")
        decision_point = current
    else:
        root = GameNode(board=board_before.copy(), source="played")
        decision_point = root
    player_color = board_before.turn

    # 2. Screen: wide shallow search
    fen = board_before.fen()
    screen_lines = await engine.analyze_lines(
        fen, n=profile.screen_breadth, depth=profile.screen_depth
    )

    if not screen_lines:
        # No engine lines — still add player move if valid
        tree = GameTree(root=root, decision_point=decision_point, player_color=player_color)
        _add_player_move(tree, engine, board_before, player_move_uci, profile)
        return tree

    # Create engine children from screen results
    screen_nodes: list[GameNode] = []
    for line in screen_lines:
        try:
            move = chess.Move.from_uci(line.uci)
            if move not in board_before.legal_moves:
                continue
        except (ValueError, chess.InvalidMoveError):
            continue
        node = decision_point.add_child(
            move, source="engine",
            score_cp=line.score_cp, score_mate=line.score_mate,
        )
        # Add shallow continuation from screen PV
        if len(line.pv) > 1:
            _add_continuation_children(node, line.pv[1:], max_ply=profile.max_concept_depth)
        screen_nodes.append(node)

    # 3. Rank by teachability
    student_is_white = player_color == chess.WHITE
    _rank_nodes_by_teachability(
        screen_nodes,
        max_concept_depth=profile.max_concept_depth,
        student_is_white=student_is_white,
    )
    # Re-sort decision_point children by interest_score (stored temporarily)
    # Take top candidates for validation
    screen_nodes.sort(key=lambda n: getattr(n, '_interest_score', 0), reverse=True)
    top_candidates = screen_nodes[:profile.validate_breadth]

    # 4. Validate: deep eval on top candidates
    for node in top_candidates:
        temp = board_before.copy()
        temp.push(node.move)
        deep_eval = await engine.evaluate(temp.fen(), depth=profile.validate_depth)

        # Update scores from deep eval
        node.score_cp = deep_eval.score_cp
        node.score_mate = deep_eval.score_mate

        # Replace shallow continuation with deep PV
        node.children.clear()
        if deep_eval.pv:
            _add_continuation_children(node, deep_eval.pv, max_ply=profile.recommend_depth)

    # Remove non-validated engine nodes (keep only top candidates)
    validated_ucis = {n.move.uci() for n in top_candidates}
    decision_point.children = [
        c for c in decision_point.children
        if c.source != "engine" or c.move.uci() in validated_ucis
    ]

    # 5. Add player's actual move
    tree = GameTree(root=root, decision_point=decision_point, player_color=player_color)
    await _add_player_move_async(tree, engine, board_before, player_move_uci, profile)

    # 6. Enrich mate threats at decision point and player's move (async Stockfish)
    await enrich_node_mate_threats(decision_point, engine)
    player_node = tree.player_move_node()
    if player_node is not None:
        await enrich_node_mate_threats(player_node, engine)

    # 7. Generate opponent candidate responses after the player's move
    if player_node is not None:
        tree.opponent_responses = await _generate_opponent_responses(
            player_node, engine, profile,
            student_is_white=player_color == chess.WHITE,
        )

    return tree


async def _add_player_move_async(
    tree: GameTree,
    engine: EngineProtocol,
    board_before: chess.Board,
    player_move_uci: str,
    profile: EloProfile,
) -> None:
    """Add the player's actual move as a child of decision_point with deep eval."""
    try:
        player_move = chess.Move.from_uci(player_move_uci)
        if player_move not in board_before.legal_moves:
            return
    except (ValueError, chess.InvalidMoveError):
        return

    # Check if this move is already an engine child — if so, re-tag it
    for child in tree.decision_point.children:
        if child.move == player_move:
            child.source = "played"
            return

    temp = board_before.copy()
    temp.push(player_move)
    player_eval = await engine.evaluate(temp.fen(), depth=profile.validate_depth)

    player_node = tree.decision_point.add_child(
        player_move, source="played",
        score_cp=player_eval.score_cp, score_mate=player_eval.score_mate,
    )

    # Add continuation from PV
    if player_eval.pv:
        _add_continuation_children(
            player_node, player_eval.pv, max_ply=profile.max_concept_depth
        )


def _add_player_move(
    tree: GameTree,
    engine: EngineProtocol,
    board_before: chess.Board,
    player_move_uci: str,
    profile: EloProfile,
) -> None:
    """Synchronous fallback for adding player move without engine eval."""
    try:
        player_move = chess.Move.from_uci(player_move_uci)
        if player_move not in board_before.legal_moves:
            return
    except (ValueError, chess.InvalidMoveError):
        return

    tree.decision_point.add_child(player_move, source="played")


async def enrich_node_mate_threats(node: GameNode, engine: EngineProtocol) -> None:
    """Enrich a node's tactics with Stockfish-powered mate-in-N threats.

    Replaces shallow depth-1 mate threats with deeper Stockfish analysis.
    Only detects up to mate-in-3 (deeper is not coachable).
    """
    fen = node.board.fen()
    try:
        deep_threats = await engine.find_mate_threats(fen, max_depth=3)
    except Exception:
        return  # Engine failure — keep existing shallow analysis

    if not deep_threats:
        return

    # Replace existing depth-1 threats with deeper Stockfish analysis
    new_threats = [
        MateThreat(
            threatening_color=t["threatening_color"],
            mating_square=t["mating_square"],
            depth=t["depth"],
            mating_move=t["mating_move"],
        )
        for t in deep_threats
    ]
    node._tactics = replace(node.tactics, mate_threats=new_threats)


def _rank_nodes_by_teachability(
    nodes: list[GameNode],
    max_concept_depth: int = 4,
    student_is_white: bool = True,
    weights: TeachabilityWeights | None = None,
) -> None:
    """Score nodes by pedagogical interest. Sets _interest_score on each.

    Adapted from screener.rank_by_teachability to work with GameNode.
    Same heuristic, different data access pattern — walks node.tactics
    and child node trees instead of AnnotatedLine annotations.

    Uses TeachabilityWeights for configurable per-motif-type weights and
    value-based bonuses from TacticValue.material_delta.
    """
    if not nodes:
        return

    w = weights if weights is not None else DEFAULT_WEIGHTS

    # Find the best score for relative comparison
    best_cp = None
    for node in nodes:
        if node.score_cp is not None:
            if best_cp is None or node.score_cp > best_cp:
                best_cp = node.score_cp

    for node in nodes:
        score = 0.0
        early_motifs: set[str] = set()
        late_motifs: set[str] = set()

        # Walk the continuation (children chain) to find motifs
        chain = _get_continuation_chain(node)
        prev_motif_labels: set[str] = set()

        for i, chain_node in enumerate(chain):
            current_labels = _motif_labels(chain_node.tactics, chain_node.board)
            new_labels = current_labels - prev_motif_labels

            if i < max_concept_depth:
                early_motifs.update(new_labels)
                # Material gain from captures
                if chain_node.parent is not None:
                    mat_before = _material_cp(chain_node.parent.board)
                    mat_after = _material_cp(chain_node.board)
                    if mat_after - mat_before > 50:
                        score += 2.0
            else:
                late_motifs.update(new_labels)

            prev_motif_labels = current_labels

        # Checkmate scoring
        if "checkmate" in early_motifs or "checkmate" in late_motifs:
            if node.score_mate is not None:
                student_mates = (
                    (student_is_white and node.score_mate > 0) or
                    (not student_is_white and node.score_mate < 0)
                )
                if student_mates:
                    score += w.checkmate_bonus
                else:
                    score -= 50.0
            else:
                score += w.checkmate_bonus

        # Per-motif scoring using weights
        MATE_PREFIX = "mate_"

        for motif in early_motifs:
            if motif.startswith(MATE_PREFIX):
                score += w.mate_bonus
            elif motif in HIGH_VALUE_KEYS:
                score += w.motif_base.get(motif, 3.0)
            elif motif in MODERATE_VALUE_KEYS:
                score += w.motif_base.get(motif, 2.0)

        # All tactics in reachable depth — per-motif base weight
        for motif in early_motifs:
            score += w.motif_base.get(motif, 1.0)

        # Value-based bonus: scan tactic items for TacticValue
        for chain_node in chain[:max_concept_depth]:
            tactics = chain_node.tactics
            for spec_key, spec in MOTIF_REGISTRY.items():
                for item in getattr(tactics, spec.field, []):
                    value = getattr(item, "value", None)
                    if value is None:
                        continue
                    if value.is_sound and value.material_delta >= 100:
                        score += (value.material_delta / 100) * w.value_bonus_per_100cp
                    elif not value.is_sound:
                        score += w.unsound_penalty

        # Positional themes (inline structural checks — no summarize_position)
        for chain_node in chain[:max_concept_depth]:
            report = chain_node.report
            ps = report.pawn_structure
            if (any(p.is_passed for p in ps.white + ps.black) or
                    any(p.is_isolated for p in ps.white + ps.black) or
                    report.king_safety_white.open_files_near_king or
                    report.king_safety_black.open_files_near_king):
                score += w.positional_bonus
                break

        # Penalty: deep-only motifs
        only_deep = late_motifs - early_motifs
        score += w.deep_only_penalty * len(only_deep)

        # Sacrifice detection
        if _detect_sacrifice(chain, node.score_mate):
            score += w.sacrifice_bonus

        # Penalty: large eval loss vs best
        if best_cp is not None and node.score_cp is not None:
            loss = best_cp - node.score_cp
            if loss > 150:
                score += w.eval_loss_penalty

        node._interest_score = score


def _get_continuation_chain(node: GameNode, max_depth: int | None = None) -> list[GameNode]:
    """Get the linear continuation chain from a node (the first child path).

    max_depth limits how many children to follow (None = unlimited).
    The node itself is always included as chain[0].
    """
    chain = [node]
    current = node
    depth = 0
    while current.children:
        if max_depth is not None and depth >= max_depth:
            break
        current = current.children[0]
        chain.append(current)
        depth += 1
    return chain


