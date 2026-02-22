"""ELO-based difficulty profiles for coaching depth and breadth."""

from dataclasses import dataclass


@dataclass
class EloProfile:
    name: str
    elo_range: str              # display label e.g. "800-1000"
    screen_depth: int           # S_d — shallow search depth for screening
    screen_breadth: int         # S_b — number of MultiPV lines in screen pass
    validate_depth: int         # V_d — deep search depth for validation
    validate_breadth: int       # V_b — top candidates to validate
    max_concept_depth: int      # max ply for "simple" tactics (player's move)
    recommend_depth: int        # max ply for annotating recommended alternatives
    cp_threshold: int           # max cp loss to still recommend a move


ELO_PROFILES: dict[str, EloProfile] = {
    "beginner":     EloProfile("beginner",     "600-800",   3, 15, 12, 3, 2, 4, 200),
    "intermediate": EloProfile("intermediate", "800-1000",  4, 15, 14, 4, 3, 6, 175),
    "advancing":    EloProfile("advancing",    "1000-1200", 4, 12, 16, 4, 4, 7, 150),
    "club":         EloProfile("club",         "1200-1400", 6, 10, 18, 5, 5, 8, 125),
    "competitive":  EloProfile("competitive",  "1400+",     6,  8, 20, 5, 6, 10, 100),
}

DEFAULT_PROFILE = "intermediate"


def get_profile(name: str) -> EloProfile:
    """Look up an ELO profile by name, falling back to the default."""
    return ELO_PROFILES.get(name, ELO_PROFILES[DEFAULT_PROFILE])
