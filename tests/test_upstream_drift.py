"""Upstream drift detection for vendored Lichess puzzle tagger functions.

Compares AST hashes of tracked upstream functions against our snapshot in
upstream.json. Hard-fails on any unacknowledged change. Skips gracefully
when offline.

To resolve failures:
  1. Review the upstream diff for the flagged function
  2. Either update the vendored copy + hash in upstream.json
  3. Or set status to "skipped" with a reason explaining why we reject it
  4. Commit the upstream.json change (audit trail in git history)
"""

import ast
import hashlib
import json
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

import pytest

UPSTREAM_JSON = (
    Path(__file__).resolve().parent.parent
    / "src"
    / "server"
    / "lichess_tactics"
    / "upstream.json"
)

RAW_URL_TEMPLATE = (
    "https://raw.githubusercontent.com/{repo}/{branch}/{filepath}"
)

FETCH_TIMEOUT = 15  # seconds


def _load_upstream_config() -> dict:
    with open(UPSTREAM_JSON) as f:
        return json.load(f)


def _fetch_source(repo: str, branch: str, filepath: str) -> str | None:
    """Fetch raw source from GitHub. Returns None on network failure."""
    url = RAW_URL_TEMPLATE.format(repo=repo, branch=branch, filepath=filepath)
    try:
        response = urlopen(url, timeout=FETCH_TIMEOUT)
        return response.read().decode("utf-8")
    except (URLError, TimeoutError, OSError):
        return None


def _extract_function_hashes(source: str) -> dict[str, str]:
    """Parse source and compute AST hash for every top-level function."""
    tree = ast.parse(source)
    hashes = {}
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.FunctionDef):
            normalized = ast.dump(node)
            h = hashlib.sha256(normalized.encode()).hexdigest()[:16]
            hashes[node.name] = h
    return hashes


def _collect_tracked_functions(config: dict) -> list[tuple[str, str, str, str, str]]:
    """Yield (filepath, func_name, expected_hash, status, reason) tuples."""
    repo = config["repo"]
    branch = config["branch"]
    result = []
    for filepath, file_info in config["files"].items():
        for func_name, func_info in file_info["functions"].items():
            result.append((
                filepath,
                func_name,
                func_info["ast_hash"],
                func_info["status"],
                func_info.get("reason", ""),
            ))
    return result


# Cache fetched sources per file to avoid redundant downloads
_source_cache: dict[str, str | None] = {}


def _get_source(repo: str, branch: str, filepath: str) -> str | None:
    key = f"{repo}/{branch}/{filepath}"
    if key not in _source_cache:
        _source_cache[key] = _fetch_source(repo, branch, filepath)
    return _source_cache[key]


class TestUpstreamDrift:
    """Test that tracked upstream functions haven't changed since our snapshot."""

    @pytest.fixture(autouse=True)
    def _load_config(self):
        self.config = _load_upstream_config()
        self.repo = self.config["repo"]
        self.branch = self.config["branch"]
        self.commit = self.config["commit"]

    def _check_function(
        self,
        filepath: str,
        func_name: str,
        expected_hash: str,
        status: str,
        reason: str,
    ):
        source = _get_source(self.repo, self.branch, filepath)
        if source is None:
            pytest.skip(
                f"Cannot fetch {filepath} from GitHub (offline or rate-limited)"
            )

        upstream_hashes = _extract_function_hashes(source)

        if func_name not in upstream_hashes:
            pytest.fail(
                f"{func_name}() no longer exists in upstream {filepath}. "
                f"Investigate: renamed, removed, or restructured. "
                f"Update upstream.json accordingly."
            )

        actual_hash = upstream_hashes[func_name]
        if actual_hash != expected_hash:
            if status == "vendored":
                pytest.fail(
                    f"VENDORED function {func_name}() changed upstream in {filepath}. "
                    f"Expected hash: {expected_hash}, got: {actual_hash}. "
                    f"Review the upstream change and either:\n"
                    f"  1. Update vendored copy + hash in upstream.json\n"
                    f"  2. Set status to 'skipped' with a reason"
                )
            elif status == "watching":
                pytest.fail(
                    f"WATCHED function {func_name}() changed upstream in {filepath}. "
                    f"Expected hash: {expected_hash}, got: {actual_hash}. "
                    f"Evaluate the change and update hash in upstream.json, "
                    f"or set status to 'skipped' with a reason."
                )
            elif status == "skipped":
                pytest.fail(
                    f"SKIPPED function {func_name}() changed upstream in {filepath} "
                    f"since last evaluation. Expected hash: {expected_hash}, got: {actual_hash}. "
                    f"Previous skip reason: '{reason}'. "
                    f"Re-evaluate: the change may address the original skip reason."
                )

    def test_util_piece_value(self):
        self._check_function("tagger/util.py", "piece_value", "110df5fe39d67d80", "vendored", "")

    def test_util_material_count(self):
        self._check_function("tagger/util.py", "material_count", "cb934bd1db3ce974", "vendored", "")

    def test_util_material_diff(self):
        self._check_function("tagger/util.py", "material_diff", "2438796a6ac34de8", "vendored", "")

    def test_util_attacked_opponent_squares(self):
        self._check_function("tagger/util.py", "attacked_opponent_squares", "6d4203686eb27b8c", "vendored", "")

    def test_util_is_defended(self):
        self._check_function("tagger/util.py", "is_defended", "542004835727640b", "vendored", "")

    def test_util_is_hanging(self):
        self._check_function("tagger/util.py", "is_hanging", "3657422509ee58b7", "vendored", "")

    def test_util_can_be_taken_by_lower_piece(self):
        self._check_function("tagger/util.py", "can_be_taken_by_lower_piece", "f8a15b93cb97cb32", "vendored", "")

    def test_util_is_in_bad_spot(self):
        self._check_function("tagger/util.py", "is_in_bad_spot", "abd8201fdfbde070", "vendored", "")

    def test_util_is_trapped(self):
        self._check_function("tagger/util.py", "is_trapped", "6bdd130286e6569b", "vendored", "")

    def test_util_attacker_pieces(self):
        self._check_function("tagger/util.py", "attacker_pieces", "2c3a9577368f8c33", "vendored", "")

    # --- cook.py vendored ---

    def test_cook_double_check(self):
        self._check_function("tagger/cook.py", "double_check", "0922451ade5cd959", "vendored", "")

    def test_cook_back_rank_mate(self):
        self._check_function("tagger/cook.py", "back_rank_mate", "3a5e227a98c03a22", "vendored", "")

    def test_cook_smothered_mate(self):
        self._check_function("tagger/cook.py", "smothered_mate", "8d4ab0be0a6f05f7", "vendored", "")

    def test_cook_arabian_mate(self):
        self._check_function("tagger/cook.py", "arabian_mate", "ae6417171b712b33", "vendored", "")

    def test_cook_hook_mate(self):
        self._check_function("tagger/cook.py", "hook_mate", "63ca010b4420e89d", "vendored", "")

    def test_cook_anastasia_mate(self):
        self._check_function("tagger/cook.py", "anastasia_mate", "1958ab9940488e23", "vendored", "")

    def test_cook_dovetail_mate(self):
        self._check_function("tagger/cook.py", "dovetail_mate", "973f1cdd5d04cd36", "vendored", "")

    def test_cook_boden_or_double_bishop_mate(self):
        self._check_function("tagger/cook.py", "boden_or_double_bishop_mate", "57d36a02b2c5db5e", "vendored", "")

    def test_cook_exposed_king(self):
        self._check_function("tagger/cook.py", "exposed_king", "cb08eaac4a35927f", "vendored", "")

    # --- cook.py watchlist ---

    def test_cook_deflection_watch(self):
        self._check_function("tagger/cook.py", "deflection", "f93113adfb62f12b", "watching", "")

    def test_cook_interference_watch(self):
        self._check_function("tagger/cook.py", "interference", "2e02a83594058324", "watching", "")

    def test_cook_attraction_watch(self):
        self._check_function("tagger/cook.py", "attraction", "9f24d9e8829d71df", "watching", "")

    def test_cook_intermezzo_watch(self):
        self._check_function("tagger/cook.py", "intermezzo", "e66ce93010180a08", "watching", "")

    def test_cook_overloading_watch(self):
        self._check_function("tagger/cook.py", "overloading", "9c18789a37d02c15", "watching", "")

    def test_cook_x_ray_watch(self):
        self._check_function("tagger/cook.py", "x_ray", "04e572640b9c2bbe", "watching", "")

    def test_cook_sacrifice_watch(self):
        self._check_function("tagger/cook.py", "sacrifice", "ebf02f994a2ae1cb", "watching", "")

    def test_cook_quiet_move_watch(self):
        self._check_function("tagger/cook.py", "quiet_move", "206d03135aedda61", "watching", "")

    def test_cook_clearance_watch(self):
        self._check_function("tagger/cook.py", "clearance", "334e87a34f3cdb09", "watching", "")

    def test_cook_trapped_piece_watch(self):
        self._check_function("tagger/cook.py", "trapped_piece", "49c47f4f924ab5fc", "watching", "")

    def test_cook_capturing_defender_watch(self):
        self._check_function("tagger/cook.py", "capturing_defender", "f371d74f1a616ee6", "watching", "")

    def test_cook_self_interference_watch(self):
        self._check_function("tagger/cook.py", "self_interference", "5245cd0629671e9f", "watching", "")

    # --- cook.py skipped ---

    def test_cook_fork_skipped(self):
        self._check_function(
            "tagger/cook.py", "fork", "80024bd09e695614", "skipped",
            "Puzzle-mainline oriented (iterates ChildNode moves). Reimplemented for static board analysis in analysis.py."
        )
