"""Feature flags for incremental rollout of tactical chaining."""

import os


def is_chain_detection_enabled() -> bool:
    return os.environ.get("CHESS_TEACHER_ENABLE_CHAINING", "0") == "1"


def is_tier2_chains_enabled() -> bool:
    return (is_chain_detection_enabled()
            and os.environ.get("CHESS_TEACHER_ENABLE_TIER2_CHAINS", "0") == "1")
