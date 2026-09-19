# Canon-TUI Fabrication — Root Cause

When the agent inside Canon TUI reported file edits or shell commands
that never actually ran on disk, the cause was that the
ACP-namespaced filesystem and shell tools were being deferred behind
the Claude Agent SDK's `ToolSearch` tool. The agent occasionally
skipped the discovery step and narrated a plausible result instead of
invoking the tool.

> Symptom signature: the chat reads "wrote `probe.txt`", "scaffolded
> the project", or "wallet created at 0x…", but `ls` on the target
> directory comes back empty. Plain `claude` from the terminal — same
> binary, same auth — works fine on the same prompt.

## Mechanism

```
Canon TUI (Python)
  └─ spawns `claude-code-acp` subprocess (Node)
       └─ creates an in-process MCP server named "acp"
            ├─ registers tools: read, write, edit, bash,
            │   bashOutput, killShell (mcp-server.js)
            └─ passes mcpServers["acp"] to the Claude Agent SDK
       └─ DISALLOWS Claude Code's native Read/Write/Edit/Bash/...
          via options.disallowedTools (acp-agent.js)
            ⇒ the agent can only act through the ACP-namespaced
              versions

Claude Agent SDK (@anthropic-ai/claude-agent-sdk ≥ 0.2.44)
  └─ defers all MCP tools behind `ToolSearch` by default
       ⇒ the ACP tools appear as
         "Deferred tools (available via ToolSearch before first use):
            • ACP — Read, Write, Edit, Bash, BashOutput, KillShell"

Result
  └─ to invoke `Bash` the agent must call `ToolSearch` first.
     When it skips that step it has no callable tool and narrates a
     plausible result instead — fabrication.
```

## Why plain `claude` is unaffected

Plain `claude` runs the Claude Code harness, which exposes
`Bash/Read/Write/Edit/...` as built-in (eager) tools. Canon TUI talks
to the same binary indirectly via `claude-code-acp`, which removes
the built-in versions and re-injects them as MCP-namespaced tools —
and MCP tools are the ones the SDK defers.

## How to recognize this regression

1. The agent describes work it did not actually do (filesystem
   side-effects missing on disk).
2. Plain `claude` works on the same machine, same prompt.
3. The session start banner lists tools under a "Deferred tools" or
   "available via ToolSearch" header (look for the `ACP —` prefix).

## Minimal reproducer

```bash
mkdir -p /tmp/canon-fabrication-probe
canon /tmp/canon-fabrication-probe
# In chat: Write a file named probe.txt with the contents "hello"
ls /tmp/canon-fabrication-probe/probe.txt   # expect: file exists
```

Run the probe in a fresh directory each time — once a session has
gone through `ToolSearch` for a tool, subsequent calls succeed
regardless. The bug only shows at session start.

## Related upstream tracking

- [anthropics/claude-code#31002](https://github.com/anthropics/claude-code/issues/31002) — system-tool deferral discussion.
- [anthropics/claude-agent-sdk-python#525](https://github.com/anthropics/claude-agent-sdk-python/issues/525) — ToolSearch / deferred-loading SDK controls.
- The TypeScript SDK reads `ENABLE_TOOL_SEARCH` from `process.env` and
  routes it through a mode selector (`tst`, `tst-auto`, `standard`,
  `mcp-cli`). Setting the env to a falsy string forces `standard` mode
  — no ToolSearch indirection — which is the fix we ship.

## See also

- [`canon-tui-fabrication-solution.md`](canon-tui-fabrication-solution.md) — the fix and how to verify it.
