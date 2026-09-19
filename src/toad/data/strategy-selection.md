# Canon strategy-selection correction

Use the installed canon-start skill and its original workflow. This note changes
ONLY the source and selection of strategies. It does not replace the workflow.

Preserve initialization, framework setup, dependencies, wallet detection/creation,
configuration, development, tests, dry-run, and the existing explicitly requested
live preflight/onboarding. Never skip these because a downloaded package can run.
Do not use the removed `canon start` launcher or launch the package with npm as a
substitute for those phases.

For phase detection and the strategy-selection phase:
- Run `canon strategies` to discover downloaded curated packages with valid access.
  Never enumerate Core's `strategies/` examples, offer discovery/spec generation,
  or select a similar template. In particular, Arbiter is not arb-binary.
- An existing docs/strategy-<key>.md counts as a selected strategy only if its key
  appears in that verified list. Otherwise return to strategy selection after setup.
- Show only those choices and use the user's selection. Empty choices: explain
  login/access/download errors and direct the user to DEGA; never auto-activate.
- Copy the selected download into the project as editable source under
  strategies/<key>, excluding .git, node_modules, runtime logs and private env files.
  Check existing project files before replacing anything; preserve user edits.
  Read its actual documentation, config and source. Use this local copy for the
  ORIGINAL strategy/develop phases, including user-requested changes and builds.
  Do not run from the global download or treat the package as immutable.
  Downloaded packages may not
  contain Core's entry.ts/strategy.md layout: do not substitute a Core template,
  invent missing files, or pretend entry points are compatible. Preserve the
  downloaded strategy as the starting point while allowing the agent to implement
  the user's requested changes through the original development and validation steps.
  Report any unsupported integration before claiming ready.
- Record the selected package in docs/strategy-<key>.md, including its source path.
  Recheck `canon strategies` before starting or relaunching; if access cannot be
  verified, stop. This command does not consume a new activation.

Write each original phase's state update. If a sandbox blocks a required write,
request approval for that operation rather than silently continuing with stale
state. The socket panel-opening command remains best-effort; state writes do not.
Show cycle updates in sequence in the state event log. Do not insert terminal
dashboard/table redraws between cycles. Preserve structured events, their original
timestamps, and measured metrics.
