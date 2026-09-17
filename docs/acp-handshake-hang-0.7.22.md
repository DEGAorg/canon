# ACP handshake hang at "Initializing…" (0.7.22)

Status: diagnosed, not yet fixed. Affects current `main`.

## Symptom

Launching an ACP agent (Claude Code, Gemini CLI, etc.) hangs at `Initializing…`
forever. No Conductor panels, no input, no visible error. Only exit is Ctrl+C.

The handshake log (`~/.local/state/toad/logs/<Agent>_*.txt`) shows:

```
[client] {'jsonrpc': '2.0', 'method': 'initialize', ...}
[agent]  {"jsonrpc":"2.0","id":1,"result": ...}
[client] None        # session/new is built but never sent
```

`initialize` succeeds, the adapter replies, then silence — `session/new` never
goes out and `AgentReady` is never posted.

## Root cause

Two independent flaws combine into a silent hang.

1. **Latent bug — `src/toad/jsonrpc.py:491`**

   ```python
   for parameter_name, arg in kwargs:   # iterates dict KEYS, not (key, value)
       call_parameters[parameter_name] = arg
   ```

   Iterating a dict yields its keys (strings). Unpacking the 5-char string
   `'_meta'` into `(parameter_name, arg)` raises
   `ValueError: too many values to unpack (expected 2)`.

   Introduced in the original ACP integration (`23484d6`). Dormant because no
   ACP call passed a keyword argument.

2. **Silent swallow — `src/toad/acp/agent.py:620-657`**

   `run()` catches only `jsonrpc.APIError`. The `ValueError` from (1) escapes
   into the asyncio task, which is never inspected for exceptions. The task
   dies, `AgentReady()` is never posted, and the TUI sits at `Initializing…`
   with no error.

## Why it started firing now (regression, not WSL-specific)

The report that surfaced this was written on WSL2, but the cause is pure Python
and platform-independent.

The trigger was added in **`8e982d2`** ("fix(acp): inject conductor +
agent_context at system-prompt level via _meta"), which made
`acp_new_session()` call:

```python
# src/toad/acp/agent.py:756
session_new_response = api.session_new(
    str(self.project_root_path),
    [],
    _meta=session_meta,   # <-- always passed as a keyword
)
```

`_meta=` is passed on every `session/new` (even when `session_meta` is `None`),
so `kwargs = {'_meta': ...}` always reaches `jsonrpc.py:491`. **Every new ACP
session on current `main` hangs, on every platform.** `tools/verify-tui.py`
renders widgets headless and does not exercise a live handshake, so it did not
catch this.

Any other ACP method called with keyword arguments (e.g. `session/cancel` with
`_meta=`) is affected the same way.

## Fix

1. **Root fix (required), `jsonrpc.py:491`:**

   ```diff
   - for parameter_name, arg in kwargs:
   + for parameter_name, arg in kwargs.items():
   ```

2. **Robustness (recommended), `agent.py:run()`** — add a general handler so a
   future internal error surfaces instead of hanging:

   ```python
   except jsonrpc.APIError as error:
       ...
       self.post_message(AgentFail(reason, details))
   except Exception as exc:
       import traceback
       self.log(f"[error] uncaught in run(): {type(exc).__name__}: {exc}")
       self.log(f"[error] {traceback.format_exc()}")
       self.post_message(AgentFail("Internal error", str(exc)))
   ```

## Verification (manual, until a handshake test exists)

After the fix, relaunch an ACP agent. Expected log:

```
[client] {'jsonrpc': '2.0', 'method': 'initialize', ...}
[agent]  {"jsonrpc":"2.0","id":1,"result": ...}
[client] {'jsonrpc': '2.0', 'method': 'session/new', ...}
```

TUI loads to the Conductor; `/canon-start` is usable.

Worth adding a regression test that calls a `@method`-decorated ACP API with a
keyword argument and asserts the call is built without raising.

## Credit

Diagnosed by carlossampson60 (with Claude.ai / Claude Code) on WSL2, 2026-05-29.
Source report: `docs/ref/Informe Técnico - Resolución Bug Canon TUI ACP Handshake.docx`.
