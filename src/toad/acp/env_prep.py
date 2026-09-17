"""Build the env passed to ``claude-code-acp`` and its child ``claude``.

Lives in its own module so the helper can be imported without pulling
in the full ``toad.acp.agent`` graph (which has a known circular import
with ``toad.acp.messages``). Tests can target this module directly
without spinning up the rest of the package.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

# Env vars Claude Code sets in its own session and that leak into any
# child process started from a Claude Code terminal (including a child
# shell of one). When canon-tui spawns ``claude-code-acp`` it must strip
# these so the inner ``claude`` process does not detect a parent session
# and refuse to start ("Claude Code cannot be launched inside another
# Claude Code session"). Failing to strip causes the ACP ``session/new``
# call to close with ``Query closed before response received`` and the
# TUI never reaches Ready, so the user sees "Agent is not ready" on
# every keystroke.
PARENT_CLAUDE_CODE_ENV_VARS: tuple[str, ...] = (
    "CLAUDECODE",
    "CLAUDE_CODE_ENTRYPOINT",
    "CLAUDE_CODE_EXECPATH",
    "CLAUDE_CODE_SESSION_ID",
)


def build_agent_subprocess_env(
    parent_env: Mapping[str, str] | "os._Environ[str]",
    cwd: str,
) -> dict[str, str]:
    """Build the env for the ``claude-code-acp`` subprocess.

    Starts from the parent process env, sets ``TOAD_CWD`` so the adapter
    knows the project root, eager-loads MCP tools by defaulting
    ``ENABLE_TOOL_SEARCH=false`` (see
    ``docs/canon-tui-fabrication-problem.md``), and strips the parent
    Claude Code session vars listed in ``PARENT_CLAUDE_CODE_ENV_VARS``.

    Args:
        parent_env: The current process env (typically ``os.environ``).
        cwd: Absolute path written into ``TOAD_CWD``.

    Returns:
        A new dict suitable for ``asyncio.create_subprocess_shell(env=...)``.
        ``ENABLE_TOOL_SEARCH`` is preserved if already set in the parent,
        so an operator can opt back into deferred-tool mode for debugging.
    """
    env = dict(parent_env)
    env["TOAD_CWD"] = cwd
    env.setdefault("ENABLE_TOOL_SEARCH", "false")
    for var in PARENT_CLAUDE_CODE_ENV_VARS:
        env.pop(var, None)
    return env
