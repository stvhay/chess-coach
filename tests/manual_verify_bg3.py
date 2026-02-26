"""Manual verification script for Bg3 brilliancy bug.

Run this to verify the fix works for the original bug report position.
"""

import chess
from server.game_tree import GameNode, GameTree
from server.report import serialize_report
from server.prompts.system import build_coaching_system_prompt
from server.prompts.personas import PERSONAS


def verify_bg3_position():
    """Reproduce the Bg3 position from the bug report."""
    # Position after 8...Bd6
    fen = "r1bqk1nr/ppp2ppp/2nb4/3p4/3P4/2N2N2/PPP2PPP/R1BQKB1R w KQkq - 2 9"
    board = chess.Board(fen)

    # Create game tree (simplified - not full game history)
    root = GameNode(board=board, source="played")

    # Student's move: Bg3
    # Assume it scored +45 (example)
    bg3 = root.add_child(chess.Move.from_uci("f1g3"), "played", score_cp=45)

    # Alternatives (assume Qe2+ scored +42, slightly worse)
    qe2 = root.add_child(chess.Move.from_uci("d1e2"), "engine", score_cp=42)
    ne2 = root.add_child(chess.Move.from_uci("c3e2"), "engine", score_cp=38)
    g3 = root.add_child(chess.Move.from_uci("g2g3"), "engine", score_cp=35)
    bb5 = root.add_child(chess.Move.from_uci("f1b5"), "engine", score_cp=40)

    tree = GameTree(root=root, decision_point=root, player_color=chess.WHITE)

    # Generate report (pass "inaccuracy" to test upgrade to "brilliant")
    report = serialize_report(tree, quality="inaccuracy", cp_loss=10)

    # Generate system prompt
    persona = PERSONAS["Anna Cramling"]
    system_prompt = build_coaching_system_prompt(
        persona_block=persona.persona_block,
        move_quality="brilliant",  # After upgrade
        elo_profile="intermediate",
        verbosity="normal",
    )

    print("=" * 80)
    print("VERIFICATION: Bg3 Position Coaching Prompt")
    print("=" * 80)
    print()

    # Verify report structure
    print("📋 Report Structure Checks:")
    print()

    checks = [
        ("✓ Brilliancy detected", "Move classification: brilliant" in report),
        ("✓ Alternatives labeled 'Other option'", "# Other option" in report),
        ("✓ No 'Stronger Alternative' label", "# Stronger Alternative" not in report),
    ]

    for label, passed in checks:
        status = "✅" if passed else "❌"
        print(f"{status} {label}")

    print()
    print("=" * 80)
    print("📄 Sample Report Output:")
    print("=" * 80)
    print()
    print(report[:500] + "..." if len(report) > 500 else report)
    print()
    print("=" * 80)
    print("📝 System Prompt Guidance Check:")
    print("=" * 80)
    print()

    # Extract brilliant guidance from system prompt
    if "Move quality — brilliant:" in system_prompt:
        start = system_prompt.index("Move quality — brilliant:")
        # Find next section or end
        next_section = system_prompt.find("\n\n", start + 100)
        if next_section == -1:
            guidance = system_prompt[start:]
        else:
            guidance = system_prompt[start:next_section]

        print(guidance)
        print()

        # Verify explicit alternative handling
        has_explicit = any(
            phrase in guidance.lower()
            for phrase in ["not stronger", "equal to or better", "just as good or better"]
        )

        print(f"{'✅' if has_explicit else '❌'} Explicit alternative handling present")
    else:
        print("❌ Brilliant guidance not found in system prompt!")

    print()
    print("=" * 80)
    print("🎯 Expected LLM Behavior:")
    print("=" * 80)
    print()
    print("With this prompt, the LLM should:")
    print("  1. Celebrate the brilliant Bg3 move enthusiastically")
    print("  2. Explain what makes Bg3 special (tactical/positional reasons)")
    print("  3. If discussing Qe2+, make clear Bg3 is just as good or better")
    print("  4. NOT say 'Qe2+ could have given you a stronger advantage'")
    print()

    # Return success status
    all_passed = all(passed for _, passed in checks) and has_explicit
    return all_passed


if __name__ == "__main__":
    success = verify_bg3_position()
    exit(0 if success else 1)
