# Canon-TUI Fabrication — Fix

Canon TUI sets `ENABLE_TOOL_SEARCH=false` in the environment of the
`claude-code-acp` subprocess. The Claude Agent SDK reads this from
`process.env` and selects `standard` tool mode, which eager-loads the
ACP-namespaced filesystem and shell tools instead of deferring them
behind `ToolSearch`. With those tools always available, the agent
cannot "skip discovery" and fall back to narration. See
[`canon-tui-fabrication-problem.md`](canon-tui-fabrication-problem.md)
for the full chain.

## Where the fix lives

`src/toad/acp/agent.py`, in `_run_agent` just before the subprocess
spawn:

```python
PIPE = asyncio.subprocess.PIPE
env = os.environ.copy()
env["TOAD_CWD"] = str(Path("./").absolute())
# Force the Claude Agent SDK into "standard" tool mode so the
# ACP-namespaced tools (Read/Write/Edit/Bash/BashOutput/KillShell
# registered by claude-code-acp's MCP server) are eager-loaded
# instead of deferred behind ToolSearch. ...
env.setdefault("ENABLE_TOOL_SEARCH", "false")
```

`setdefault` is deliberate — a user who exports
`ENABLE_TOOL_SEARCH=auto:25` (or any other valid SDK value) in their
shell still wins.

## Verifying after a Claude Code or SDK upgrade

The SDK's mode-selector logic could change in a future release. Verify
the fix still holds whenever you bump `claude-code-acp` or the
underlying SDK:

```bash
# 1. Probe in a brand-new directory.
mkdir -p /tmp/canon-fab-verify
canon /tmp/canon-fab-verify
# In chat: Write a file named probe.txt with the contents "hello".
ls /tmp/canon-fab-verify/probe.txt   # must exist
```

Repeat three times in three different fresh directories before
declaring it good — once a session has loaded the ACP tools via
ToolSearch, the bug hides. Only fresh-session passes count.

A heavier integration test:

```bash
mkdir -p /tmp/canon-fab-verify-canon-start
canon /tmp/canon-fab-verify-canon-start
# In chat: /canon-start
# Then verify the scaffold landed:
find /tmp/canon-fab-verify-canon-start -mindepth 1 | wc -l
# Expect roughly the baseline entry count for the canon-start scaffold.
```

## If the symptom returns

Try, in order:

1. Confirm the env is actually reaching the subprocess:
   ```python
   # Temporary log in src/toad/acp/agent.py before create_subprocess_shell
   self.log(f"[spawn-env] ENABLE_TOOL_SEARCH={env.get('ENABLE_TOOL_SEARCH')!r}")
   ```
   Look in `$XDG_STATE_HOME/toad/logs/Claude_Code_*.txt` for the line.
2. Try `env["ENABLE_TOOL_SEARCH"] = "auto:100"` — this forces the
   explicit `q===100 → standard` branch in the SDK's selector. Useful
   if the falsy-string branch changes.
3. Inspect the SDK's selector directly:
   ```bash
   SDK="$HOME/.npm-global/lib/node_modules/@zed-industries/claude-code-acp/node_modules/@anthropic-ai/claude-agent-sdk"
   grep -aoE '.{80}ENABLE_TOOL_SEARCH.{120}' "$SDK/cli.js" | head
   ```
   The returned string values (`tst`, `tst-auto`, `standard`,
   `mcp-cli`) drive whether ToolSearch is wired in.
4. As a last resort, patch `claude-code-acp`'s `mcp-server.js` to
   declare the ACP tools as eager when the MCP SDK supports it, or
   open an upstream issue with `zed-industries/claude-code-acp`
   requesting a knob.

## Why we set this in the spawn env instead of upstream

The cheapest stable surface we control is the subprocess env. Patching
`claude-code-acp` or the SDK requires a release on their side; setting
the env keeps the fix in this repo, reversible, and easy to remove
once an upstream change makes it unnecessary.
