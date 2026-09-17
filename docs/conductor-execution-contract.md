# Conductor execution contract

The Conductor is the top-level agent that canon-tui spawns inside a
`canon run <path>` session. It is allowed to **execute deterministic
infrastructure scripts directly** — it does not delegate them. Concretely:

- Canon scripts under `${DEGA_CORE_HOME}/scripts/` (`canon-scaffold.sh`,
  `canon-runner.sh`, `canon-live-readiness.sh`, `canon.sh`, ...).
- `canon-cli` with any subcommand (e.g. `canon-cli wallet ensure --pretty`).
- Package-manager installs (`pnpm install`, `npm install`).
- Read-only inspection commands (`ls`, `cat`, `grep`, `git status`,
  `gh pr list`, ...) needed to gather session state.
- Bash blocks defined inline in slash-command files under
  `~/.claude/commands/` or `.claude/commands/`.

**Code authoring still goes through delegation** — subagents and the
orchestrator handle file edits, test runs, and project source changes.

## Environment contract

When canon-tui spawns the agent subprocess it sets:

| Variable    | Meaning                                                    |
| ----------- | ---------------------------------------------------------- |
| `TOAD_CWD`  | Absolute path of the project root canon-tui is anchored to |
| `CANON_TUI` | `"1"` — signals slash-command TUI detection that we are it |

`CANON_TUI=1` is the trigger the `/canon-start` flow keys off. Without it
the Conductor falls back to a degraded "delegation-only" persona that has
been observed fabricating shell output instead of running scaffolding
scripts. The regression test `tests/acp/test_agent_subprocess_env.py`
pins this contract.

## Reporting a fabricated-output bug

If the agent reports work it did not actually do — wallet addresses that
do not match `~/.degacore/bin/canon-cli wallet info --pretty`, scaffold
file lists that do not match `ls -la`, claims of "templates fetched" when
nothing landed — that is a tool-relay or persona-conflict bug.

To file it, reproduce with the smoking-gun diagnostic from the handoff:

1. In a fresh empty directory, run `canon run .`.
2. Ask the agent in chat: `Run "ls -la" and "cat .canon/wallet.env" and
   quote both verbatim.`
3. From a separate terminal in the same directory, run the same two
   commands.
4. If the two transcripts disagree, the bug is live. Attach both
   transcripts (agent claim vs. real shell output) to the issue.

The end-to-end smoking-gun and root-cause analysis live in the
[`canon-tui-agent-hallucination-handoff.md`](https://github.com/DEGAorg/claude-code-config/blob/develop/docs/reviews/canon-tui-agent-hallucination-handoff.md)
doc under `DEGAorg/claude-code-config`. File the canon-tui-side issue on
`DEGAorg/canon` with a link to that handoff.
