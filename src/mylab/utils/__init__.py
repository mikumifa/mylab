from .git import (
    branch_exists,
    detect_git_branch,
    detect_source_branch,
    has_commits,
    list_tracked_files,
    working_tree_is_clean,
)
from .text import (
    describe_language,
    detect_preferred_language,
    shell_join,
    slugify,
    utc_now,
)

__all__ = [
    "branch_exists",
    "describe_language",
    "detect_git_branch",
    "detect_preferred_language",
    "detect_source_branch",
    "has_commits",
    "list_tracked_files",
    "shell_join",
    "slugify",
    "utc_now",
    "working_tree_is_clean",
]
