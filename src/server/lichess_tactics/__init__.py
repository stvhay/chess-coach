"""Vendored and adapted tactical detection from Lichess puzzle tagger.

Upstream: https://github.com/ornicar/lichess-puzzler
License: AGPL-3.0
Commit: d021969ec326c83cfa357f3ad58dbd9cea44e64f

See upstream.json for per-function hash tracking and drift detection.
"""

from server.lichess_tactics._util import (
    attacked_opponent_squares,
    can_be_taken_by_lower_piece,
    is_defended,
    is_hanging,
    is_in_bad_spot,
    is_trapped,
    material_count,
    piece_value,
)

__all__ = [
    "attacked_opponent_squares",
    "can_be_taken_by_lower_piece",
    "is_defended",
    "is_hanging",
    "is_in_bad_spot",
    "is_trapped",
    "material_count",
    "piece_value",
]
