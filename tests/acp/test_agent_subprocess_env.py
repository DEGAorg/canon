"""Tests for ``build_agent_subprocess_env``.

When canon is launched from a terminal that inherited ``CLAUDECODE=1``
(a Claude Code session, or any child shell of one), the spawned
``claude`` process detects the parent session and refuses to start.
The ACP handshake then closes at ``session/new`` with ``Query closed
before response received`` and the agent never reaches Ready.

These tests pin the env-prep contract so the strip cannot regress
silently — the symptom is invisible until a user actually types into
the prompt.
"""

from __future__ import annotations

from toad.acp.env_prep import (
    PARENT_CLAUDE_CODE_ENV_VARS,
    build_agent_subprocess_env,
)


def test_strips_all_known_claude_code_session_vars() -> None:
    parent = {
        "PATH": "/usr/bin",
        "CLAUDECODE": "1",
        "CLAUDE_CODE_ENTRYPOINT": "cli",
        "CLAUDE_CODE_EXECPATH": "/Users/x/.local/share/claude/versions/2.1",
        "CLAUDE_CODE_SESSION_ID": "deadbeef-1234",
        "USER": "alice",
    }

    env = build_agent_subprocess_env(parent, "/some/project")

    for var in PARENT_CLAUDE_CODE_ENV_VARS:
        assert var not in env, f"{var} leaked into the child env"
    # Unrelated vars are preserved.
    assert env["PATH"] == "/usr/bin"
    assert env["USER"] == "alice"


def test_sets_toad_cwd_to_provided_path() -> None:
    env = build_agent_subprocess_env({}, "/tmp/canon-demo")
    assert env["TOAD_CWD"] == "/tmp/canon-demo"


def test_defaults_enable_tool_search_to_false() -> None:
    env = build_agent_subprocess_env({}, "/cwd")
    assert env["ENABLE_TOOL_SEARCH"] == "false"


def test_preserves_operator_override_of_enable_tool_search() -> None:
    """An operator may set ENABLE_TOOL_SEARCH=true to debug deferred tools.

    The helper only ``setdefault``s, so an explicit upstream value wins.
    """
    env = build_agent_subprocess_env({"ENABLE_TOOL_SEARCH": "true"}, "/cwd")
    assert env["ENABLE_TOOL_SEARCH"] == "true"


def test_returns_new_dict_not_alias_of_parent() -> None:
    parent = {"PATH": "/usr/bin"}
    env = build_agent_subprocess_env(parent, "/cwd")
    env["TOAD_CWD"] = "/mutated"
    assert "TOAD_CWD" not in parent
