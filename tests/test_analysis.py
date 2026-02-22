"""Tests for the position analysis module using well-known positions."""

import chess

from server.analysis import (
    analyze,
    analyze_activity,
    analyze_center_control,
    analyze_development,
    analyze_files_and_diagonals,
    analyze_king_safety,
    analyze_material,
    analyze_pawn_structure,
    analyze_space,
    analyze_tactics,
)


# ---------------------------------------------------------------------------
# Test positions (FEN)
# ---------------------------------------------------------------------------

STARTING = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
CASTLED_KS = "r1bq1rk1/ppppppbp/2n2np1/8/2B1P3/2N2N2/PPPP1PPP/R1BQ1RK1 w - - 0 1"
PIN_POSITION = "4k3/8/8/8/4n3/8/8/4R2K w - - 0 1"
FORK_POSITION = "r3k3/2N5/8/8/8/8/8/4K3 w q - 0 1"
PASSED_PAWN = "8/8/8/3P4/8/8/1p6/8 w - - 0 1"
BACKWARD_PAWN = "8/8/2p1p3/8/3P4/8/8/8 w - - 0 1"
PAWN_CHAIN = "8/8/8/4P3/3P4/2P5/8/8 w - - 0 1"
OPEN_E_FILE = "r3r1k1/ppp2ppp/8/3p4/3P4/8/PPP2PPP/R3R1K1 w - - 0 1"
AFTER_1E4_E5 = "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2"
EMPTY_BOARD = "8/8/8/8/8/8/8/8 w - - 0 1"


# ---------------------------------------------------------------------------
# Material
# ---------------------------------------------------------------------------


class TestMaterial:
    def test_starting_position(self):
        board = chess.Board(STARTING)
        m = analyze_material(board)
        assert m.white.pawns == 8
        assert m.white.knights == 2
        assert m.white.bishops == 2
        assert m.white.rooks == 2
        assert m.white.queens == 1
        assert m.black.pawns == 8
        assert m.white_total == m.black_total
        assert m.imbalance == 0
        assert m.white_bishop_pair is True
        assert m.black_bishop_pair is True

    def test_starting_totals(self):
        board = chess.Board(STARTING)
        m = analyze_material(board)
        # 8*1 + 2*3 + 2*3 + 2*5 + 9 = 39
        assert m.white_total == 39
        assert m.black_total == 39

    def test_pin_position_material(self):
        board = chess.Board(PIN_POSITION)
        m = analyze_material(board)
        assert m.white.rooks == 1
        assert m.black.knights == 1
        assert m.imbalance == 5 - 3  # rook vs knight

    def test_empty_board(self):
        board = chess.Board(EMPTY_BOARD)
        m = analyze_material(board)
        assert m.white_total == 0
        assert m.black_total == 0
        assert m.white_bishop_pair is False


# ---------------------------------------------------------------------------
# Pawn Structure
# ---------------------------------------------------------------------------


class TestPawnStructure:
    def test_starting_position(self):
        board = chess.Board(STARTING)
        ps = analyze_pawn_structure(board)
        assert len(ps.white) == 8
        assert len(ps.black) == 8
        assert ps.white_islands == 1
        assert ps.black_islands == 1
        # No pawns should be isolated, doubled, passed, or backward
        for p in ps.white + ps.black:
            assert p.is_isolated is False
            assert p.is_doubled is False
            assert p.is_passed is False
            assert p.is_backward is False

    def test_passed_pawn(self):
        board = chess.Board(PASSED_PAWN)
        ps = analyze_pawn_structure(board)
        # White d5 pawn should be passed and isolated
        assert len(ps.white) == 1
        wp = ps.white[0]
        assert wp.square == "d5"
        assert wp.is_passed is True
        assert wp.is_isolated is True
        # Black b2 pawn should be passed and isolated
        assert len(ps.black) == 1
        bp = ps.black[0]
        assert bp.square == "b2"
        assert bp.is_passed is True
        assert bp.is_isolated is True

    def test_backward_pawn(self):
        board = chess.Board(BACKWARD_PAWN)
        ps = analyze_pawn_structure(board)
        # White d4 pawn: stop square d5 is attacked by c6 and e6 pawns,
        # and no friendly pawns on c or e files to support
        wp = ps.white[0]
        assert wp.square == "d4"
        assert wp.is_backward is True

    def test_pawn_chain(self):
        board = chess.Board(PAWN_CHAIN)
        ps = analyze_pawn_structure(board)
        assert len(ps.white) == 3
        pawn_map = {p.square: p for p in ps.white}
        # c3 is the base (supports d4, not supported from behind)
        assert pawn_map["c3"].is_chain_base is True
        assert pawn_map["c3"].is_chain_member is False
        # d4 is a chain member (supported by c3) and also base for e5
        assert pawn_map["d4"].is_chain_member is True
        # e5 is a chain member (supported by d4)
        assert pawn_map["e5"].is_chain_member is True

    def test_doubled_pawns(self):
        board = chess.Board("8/8/8/8/3P4/3P4/8/8 w - - 0 1")
        ps = analyze_pawn_structure(board)
        for p in ps.white:
            assert p.is_doubled is True

    def test_islands(self):
        # Pawns on a, b, e, f = 2 islands
        board = chess.Board("8/8/8/8/PP2PP2/8/8/8 w - - 0 1")
        ps = analyze_pawn_structure(board)
        assert ps.white_islands == 2

    def test_no_pawns(self):
        board = chess.Board(EMPTY_BOARD)
        ps = analyze_pawn_structure(board)
        assert ps.white_islands == 0
        assert ps.black_islands == 0


# ---------------------------------------------------------------------------
# King Safety
# ---------------------------------------------------------------------------


class TestKingSafety:
    def test_castled_kingside(self):
        board = chess.Board(CASTLED_KS)
        ks = analyze_king_safety(board, chess.WHITE)
        assert ks.king_square == "g1"
        assert ks.castled == "kingside"
        assert ks.pawn_shield_count >= 2  # f2, g2, h2 area

    def test_starting_position(self):
        board = chess.Board(STARTING)
        ks = analyze_king_safety(board, chess.WHITE)
        assert ks.castled == "none"
        assert ks.has_kingside_castling_rights is True
        assert ks.has_queenside_castling_rights is True

    def test_no_king(self):
        board = chess.Board(EMPTY_BOARD)
        ks = analyze_king_safety(board, chess.WHITE)
        assert ks.king_square is None
        assert ks.castled == "none"
        assert ks.pawn_shield_count == 0

    def test_open_files_near_king(self):
        board = chess.Board(OPEN_E_FILE)
        ks = analyze_king_safety(board, chess.WHITE)
        assert ks.castled == "kingside"
        # e-file is open, near the king on g1 (files f, g, h)
        # f and h files have pawns, g file... let's check
        # King on g1, checking files f(5), g(6), h(7)

    def test_castled_queenside(self):
        board = chess.Board("r3kbnr/pppppppp/8/8/8/8/PPPPPPPP/R1K1QBNR w kq - 0 1")
        ks = analyze_king_safety(board, chess.WHITE)
        assert ks.castled == "queenside"


# ---------------------------------------------------------------------------
# Piece Activity
# ---------------------------------------------------------------------------


class TestActivity:
    def test_starting_position_low_mobility(self):
        board = chess.Board(STARTING)
        act = analyze_activity(board)
        # Knights can move (2 squares each), but bishops/rooks/queen blocked
        assert act.white_total_mobility > 0
        # Rooks and queen have 0 mobility at start
        for p in act.white:
            if p.piece in ("R", "Q"):
                assert p.mobility == 0

    def test_castled_position_higher_mobility(self):
        board = chess.Board(CASTLED_KS)
        act = analyze_activity(board)
        # Developed position should have more mobility
        assert act.white_total_mobility > 10
        assert act.black_total_mobility > 10

    def test_centralization(self):
        # Knight on e4 should have centralization 0
        board = chess.Board("8/8/8/8/4N3/8/8/4K2k w - - 0 1")
        act = analyze_activity(board)
        knight = [p for p in act.white if p.piece == "N"][0]
        assert knight.centralization == 0

    def test_corner_piece(self):
        # Knight on a1 should have high centralization distance
        board = chess.Board("8/8/8/8/8/8/8/N3K2k w - - 0 1")
        act = analyze_activity(board)
        knight = [p for p in act.white if p.piece == "N"][0]
        assert knight.centralization >= 3


# ---------------------------------------------------------------------------
# Tactical Motifs
# ---------------------------------------------------------------------------


class TestTactics:
    def test_pin(self):
        board = chess.Board(PIN_POSITION)
        t = analyze_tactics(board)
        assert len(t.pins) >= 1
        pin = t.pins[0]
        assert pin.pinned_square == "e4"
        assert pin.pinner_square == "e1"
        assert pin.pinned_to == "e8"  # king

    def test_pin_is_absolute(self):
        # Pin to king is always absolute
        board = chess.Board(PIN_POSITION)
        t = analyze_tactics(board)
        pin = t.pins[0]
        assert pin.is_absolute is True

    def test_fork(self):
        board = chess.Board(FORK_POSITION)
        t = analyze_tactics(board)
        assert len(t.forks) >= 1
        fork = [f for f in t.forks if f.forking_square == "c7"][0]
        assert "a8" in fork.targets
        assert "e8" in fork.targets

    def test_hanging_piece(self):
        # Black knight on e4 attacked by white rook, no defenders
        board = chess.Board(PIN_POSITION)
        t = analyze_tactics(board)
        hanging = [h for h in t.hanging if h.square == "e4"]
        assert len(hanging) >= 1

    def test_hanging_piece_color(self):
        board = chess.Board(PIN_POSITION)
        t = analyze_tactics(board)
        hanging = [h for h in t.hanging if h.square == "e4"]
        assert hanging[0].color == "black"

    def test_no_tactics_starting(self):
        board = chess.Board(STARTING)
        t = analyze_tactics(board)
        assert len(t.pins) == 0
        assert len(t.forks) == 0
        assert len(t.skewers) == 0
        assert len(t.hanging) == 0

    def test_skewer(self):
        # White rook skewers black king through to black rook
        board = chess.Board("4k3/8/8/8/8/8/8/R3K2r w - - 0 1")
        t = analyze_tactics(board)
        # The rook on a1 should skewer e8 king to h1 rook (but king is not
        # on the same line... let's use a proper skewer position)

    def test_skewer_rook(self):
        # Rook on a1, black queen on a5, black rook on a8
        board = chess.Board("r7/8/8/q7/8/8/8/R3K2k w - - 0 1")
        t = analyze_tactics(board)
        skewers = [s for s in t.skewers if s.attacker_square == "a1"]
        assert len(skewers) >= 1
        skewer = skewers[0]
        assert skewer.front_square == "a5"
        assert skewer.behind_square == "a8"

    def test_discovered_attack(self):
        # White bishop on a1, white knight on d4 blocks diagonal to black queen on h8
        board = chess.Board("7q/8/8/8/3N4/8/8/B3K2k w - - 0 1")
        t = analyze_tactics(board)
        disc = [d for d in t.discovered_attacks if d.slider_square == "a1"]
        assert len(disc) >= 1

    def test_discovered_attack_significance(self):
        # Pawn blocking rook targeting a pawn = low significance
        # White rook on a1, white pawn on a3, black pawn on a7
        board = chess.Board("8/p7/8/8/8/P7/8/R3K2k w - - 0 1")
        t = analyze_tactics(board)
        disc = [d for d in t.discovered_attacks
                if d.slider_square == "a1" and d.blocker_square == "a3"]
        assert len(disc) >= 1
        assert disc[0].significance == "low"


# ---------------------------------------------------------------------------
# Double Check
# ---------------------------------------------------------------------------


class TestDoubleCheck:
    def test_double_check_detected(self):
        # Knight on f6 and bishop on b5 both give check to king on e8
        # (no d-pawn blocking bishop)
        board = chess.Board("r1bqk2r/ppp2ppp/5N2/1B6/4P3/8/PPPP1PPP/RNBQK2R b KQkq - 0 1")
        t = analyze_tactics(board)
        assert len(t.double_checks) == 1
        assert len(t.double_checks[0].checker_squares) == 2

    def test_single_check_not_double(self):
        # Only one checker
        board = chess.Board("4k3/8/8/8/8/8/8/4R2K b - - 0 1")
        t = analyze_tactics(board)
        assert len(t.double_checks) == 0

    def test_no_check_no_double(self):
        board = chess.Board(STARTING)
        t = analyze_tactics(board)
        assert len(t.double_checks) == 0


# ---------------------------------------------------------------------------
# Mate Patterns
# ---------------------------------------------------------------------------


class TestMatePatterns:
    def test_back_rank_mate(self):
        # Classic back-rank: Rd8#, king on g8, pawns f7 g7 h7
        board = chess.Board("3R2k1/5ppp/8/8/8/8/8/4K3 b - - 0 1")
        t = analyze_tactics(board)
        assert any(mp.pattern == "back_rank" for mp in t.mate_patterns)

    def test_smothered_mate(self):
        # Philidor's legacy: Nf7#, king on g8 surrounded by own pieces
        board = chess.Board("6rk/5Npp/8/8/8/8/8/4K3 b - - 0 1")
        # Verify it's actually checkmate
        assert board.is_checkmate()
        t = analyze_tactics(board)
        assert any(mp.pattern == "smothered" for mp in t.mate_patterns)

    def test_no_mate_pattern_when_not_checkmate(self):
        board = chess.Board(STARTING)
        t = analyze_tactics(board)
        assert len(t.mate_patterns) == 0


# ---------------------------------------------------------------------------
# Mate Threats
# ---------------------------------------------------------------------------


class TestMateThreats:
    def test_mate_threat_detected(self):
        # White rook on d1, black king on g8 with pawns f7/g7/h7
        # White threatens Rd8# (back-rank mate)
        board = chess.Board("6k1/5ppp/8/8/8/8/8/3RK3 w - - 0 1")
        t = analyze_tactics(board)
        assert len(t.mate_threats) >= 1
        assert t.mate_threats[0].threatening_color == "white"

    def test_no_mate_threat(self):
        board = chess.Board(STARTING)
        t = analyze_tactics(board)
        assert len(t.mate_threats) == 0


# ---------------------------------------------------------------------------
# Back Rank Weakness
# ---------------------------------------------------------------------------


class TestBackRankWeakness:
    def test_back_rank_weakness_detected(self):
        # Black king on g8, pawns f7 g7 h7, White has a rook
        board = chess.Board("6k1/5ppp/8/8/8/8/8/R3K3 w - - 0 1")
        t = analyze_tactics(board)
        weak = [w for w in t.back_rank_weaknesses if w.weak_color == "black"]
        assert len(weak) >= 1
        assert weak[0].king_square == "g8"

    def test_no_weakness_with_escape(self):
        # King on g8, f7 pawn, but g7 and h7 open — not weak
        board = chess.Board("6k1/5p2/8/8/8/8/8/R3K3 w - - 0 1")
        t = analyze_tactics(board)
        weak = [w for w in t.back_rank_weaknesses if w.weak_color == "black"]
        assert len(weak) == 0

    def test_no_weakness_without_heavy_piece(self):
        # Back rank blocked but opponent has no rook/queen
        board = chess.Board("6k1/5ppp/8/8/8/8/8/4K3 w - - 0 1")
        t = analyze_tactics(board)
        weak = [w for w in t.back_rank_weaknesses if w.weak_color == "black"]
        assert len(weak) == 0


# ---------------------------------------------------------------------------
# X-Ray Attacks
# ---------------------------------------------------------------------------


class TestXRayAttacks:
    def test_rook_xray_through_enemy(self):
        # White rook on a1, black knight on a4, black rook on a8
        # Rook x-rays through knight to target rook
        board = chess.Board("r7/8/8/8/n7/8/8/R3K2k w - - 0 1")
        t = analyze_tactics(board)
        xrays = [x for x in t.xray_attacks
                 if x.slider_square == "a1" and x.target_square == "a8"]
        assert len(xrays) >= 1
        assert xrays[0].through_square == "a4"

    def test_bishop_xray_through_enemy(self):
        # White bishop on a1, black pawn on d4, black queen on g7
        board = chess.Board("8/6q1/8/8/3p4/8/8/B3K2k w - - 0 1")
        t = analyze_tactics(board)
        xrays = [x for x in t.xray_attacks
                 if x.slider_square == "a1" and x.target_square == "g7"]
        assert len(xrays) >= 1

    def test_no_xray_when_unblocked(self):
        # Rook directly attacks — not an x-ray
        board = chess.Board("r7/8/8/8/8/8/8/R3K2k w - - 0 1")
        t = analyze_tactics(board)
        # Direct attack, not x-ray (through_square would need an enemy piece)
        xrays = [x for x in t.xray_attacks
                 if x.slider_square == "a1" and x.target_square == "a8"]
        assert len(xrays) == 0

    def test_no_xray_starting_position(self):
        board = chess.Board(STARTING)
        t = analyze_tactics(board)
        assert len(t.xray_attacks) == 0


# ---------------------------------------------------------------------------
# Exposed King
# ---------------------------------------------------------------------------


class TestExposedKing:
    def test_exposed_king_detected(self):
        # Black king on d3 (advanced, no pawn shield) — exposed from White's POV
        board = chess.Board("8/8/8/8/8/3k4/8/4K3 w - - 0 1")
        t = analyze_tactics(board)
        exposed = [e for e in t.exposed_kings if e.color == "black"]
        assert len(exposed) >= 1

    def test_king_on_home_rank_not_exposed(self):
        board = chess.Board(STARTING)
        t = analyze_tactics(board)
        assert len(t.exposed_kings) == 0

    def test_king_with_pawn_shield_not_exposed(self):
        # Black king advanced to d3 with pawns on d4/e4 (shield rank behind king)
        board = chess.Board("8/8/8/8/3pp3/3k4/8/4K3 w - - 0 1")
        t = analyze_tactics(board)
        exposed = [e for e in t.exposed_kings if e.color == "black"]
        assert len(exposed) == 0


# ---------------------------------------------------------------------------
# Open Files & Diagonals
# ---------------------------------------------------------------------------


class TestFilesAndDiagonals:
    def test_open_e_file(self):
        board = chess.Board(OPEN_E_FILE)
        fd = analyze_files_and_diagonals(board)
        e_file = fd.files[4]  # e = file index 4
        assert e_file.is_open is True

    def test_rooks_on_open_file(self):
        board = chess.Board(OPEN_E_FILE)
        fd = analyze_files_and_diagonals(board)
        # Both e1 and e8 rooks on open e-file
        assert "e1" in fd.rooks_on_open_files
        assert "e8" in fd.rooks_on_open_files

    def test_starting_no_open_files(self):
        board = chess.Board(STARTING)
        fd = analyze_files_and_diagonals(board)
        for fs in fd.files:
            assert fs.is_open is False

    def test_semi_open_file(self):
        # After 1.e4, e-file is semi-open for... actually both pawns moved
        # Let's use a position where white has no e-pawn but black does
        board = chess.Board("rnbqkbnr/pppppppp/8/8/8/8/PPPP1PPP/RNBQKBNR w KQkq - 0 1")
        fd = analyze_files_and_diagonals(board)
        e_file = fd.files[4]
        assert e_file.semi_open_white is True
        assert e_file.semi_open_black is False
        assert e_file.is_open is False

    def test_bishop_on_long_diagonal(self):
        board = chess.Board(CASTLED_KS)
        fd = analyze_files_and_diagonals(board)
        # g7 bishop is on long diagonal a1-h8
        assert "g7" in fd.bishops_on_long_diagonals


# ---------------------------------------------------------------------------
# Center Control
# ---------------------------------------------------------------------------


class TestCenterControl:
    def test_starting_position(self):
        board = chess.Board(STARTING)
        cc = analyze_center_control(board)
        # Only d-pawn and e-pawn attack center squares from each side
        # White: d2 attacks e3 (not center), c3 (not center)... wait
        # Center squares: d4, e4, d5, e5
        # White pawns: d2 attacks c3, e3; e2 attacks d3, f3 — none attack center
        assert cc.white_pawn_control == 0
        assert cc.black_pawn_control == 0

    def test_after_1e4_e5(self):
        board = chess.Board(AFTER_1E4_E5)
        cc = analyze_center_control(board)
        # e4 pawn attacks d5 and f5 — d5 is center
        assert cc.white_pawn_control >= 1
        # e5 pawn attacks d4 and f4 — d4 is center
        assert cc.black_pawn_control >= 1

    def test_castled_position(self):
        board = chess.Board(CASTLED_KS)
        cc = analyze_center_control(board)
        # Both sides have pieces developed, should have piece control
        assert cc.white_total > 0
        assert cc.black_total > 0


# ---------------------------------------------------------------------------
# Development
# ---------------------------------------------------------------------------


class TestDevelopment:
    def test_starting_position(self):
        board = chess.Board(STARTING)
        dev = analyze_development(board)
        assert dev.white_developed == 0
        assert dev.black_developed == 0
        assert dev.white_castled == "none"
        assert dev.black_castled == "none"

    def test_castled_position(self):
        board = chess.Board(CASTLED_KS)
        dev = analyze_development(board)
        # White: Nc3, Nf3, Bc4 developed (3 of 4 minors off starting squares)
        assert dev.white_developed >= 3
        # Black: Nc6, Nf6, Bg7 developed
        assert dev.black_developed >= 3
        assert dev.white_castled == "kingside"
        assert dev.black_castled == "kingside"


# ---------------------------------------------------------------------------
# Space
# ---------------------------------------------------------------------------


class TestSpace:
    def test_starting_position(self):
        board = chess.Board(STARTING)
        sp = analyze_space(board)
        # Both sides control some squares in opponent's half
        assert sp.white_squares >= 0
        assert sp.black_squares >= 0

    def test_after_1e4_e5(self):
        board = chess.Board(AFTER_1E4_E5)
        sp = analyze_space(board)
        # e4 pawn controls d5, f5 in black's territory
        assert sp.white_squares >= 1
        assert sp.black_squares >= 1

    def test_empty_board(self):
        board = chess.Board(EMPTY_BOARD)
        sp = analyze_space(board)
        assert sp.white_squares == 0
        assert sp.black_squares == 0


# ---------------------------------------------------------------------------
# Top-Level Report
# ---------------------------------------------------------------------------


class TestAnalyze:
    def test_starting_report(self):
        board = chess.Board(STARTING)
        report = analyze(board)
        assert report.fen == STARTING
        assert report.turn == "white"
        assert report.fullmove_number == 1
        assert report.is_check is False
        assert report.is_checkmate is False
        assert report.is_stalemate is False
        assert report.material.imbalance == 0
        assert report.development.white_developed == 0

    def test_checkmate(self):
        # Scholar's mate final position
        fen = "r1bqkb1r/pppp1Qpp/2n2n2/4p3/2B1P3/8/PPPP1PPP/RNB1K1NR b KQkq - 0 4"
        board = chess.Board(fen)
        report = analyze(board)
        assert report.is_checkmate is True
        assert report.is_check is True

    def test_stalemate(self):
        fen = "k7/8/KQ6/8/8/8/8/8 b - - 0 1"
        board = chess.Board(fen)
        report = analyze(board)
        assert report.is_stalemate is True

    def test_empty_board_no_crash(self):
        board = chess.Board(EMPTY_BOARD)
        report = analyze(board)
        assert report.material.white_total == 0
        assert report.king_safety_white.king_square is None

    def test_report_has_all_fields(self):
        board = chess.Board(STARTING)
        report = analyze(board)
        assert report.material is not None
        assert report.pawn_structure is not None
        assert report.king_safety_white is not None
        assert report.king_safety_black is not None
        assert report.activity is not None
        assert report.tactics is not None
        assert report.files_and_diagonals is not None
        assert report.center_control is not None
        assert report.development is not None
        assert report.space is not None

    def test_report_serializable(self):
        """PositionReport should be convertible to dict via dataclasses.asdict."""
        from dataclasses import asdict
        board = chess.Board(STARTING)
        report = analyze(board)
        d = asdict(report)
        assert isinstance(d, dict)
        assert d["fen"] == STARTING
        assert isinstance(d["material"]["white"]["pawns"], int)
