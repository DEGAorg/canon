# Changelog

## [Unreleased]

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

> **Version note (2026-09-16):** the newest versioned section below is `0.6.12` while
> `pyproject.toml` is at `0.7.25`, so the 0.7.x line was released without changelog sections. The
> entries here were reconstructed from the git history of the DEGA/Canon work (2026-08-29 →
> 2026-09-16); earlier 0.5.x/0.6.x sections are unchanged.


### Added
- Encrypted rooms: group conversations inside the DEGA Chat panel with owner-managed invitations, accept/decline, per-recipient encryption over the existing DM transport, durable local outbox/history (`~/.canon/rooms/<pubkey>.sqlite3`), right-aligned own messages and `canon-ctl raw '{"cmd":"room",...}'` commands — 2026-09-16
- Renewable registrations: `registrationTTL` + `renewNode` in `DegaChatRegistry`, Active/Expired status with a UTC date, and a renewal that stores the signed transaction before broadcasting so a restart never buys a second period — 2026-09-16
- Opt-in chat presence (NIP-38 kind 30315 with NIP-40 expiry): off by default, 90 s signal, green dot + Online text in the contact list, `!` help for contacts whose chat key is missing — 2026-09-15
- Timed strategy access: activation consumes elements and creates a backend grant, the client caches it in `~/.canon/strategy-access.json` and blocks a new start after expiry until access is re-synchronized; archives are streamed by the authenticated backend only — 2026-09-14/16
- Real on-chain P2P chat: `openNode(username, nostrPubkey)` registry v2/v3 (one node per address, `usernameOfOwner`, reverse `usernameForPubkey`), invite-by-name, wallet-derived Nostr identity persisted in `~/.canon/chat-identity.json` — 2026-08-31/09-15
- Resident on-chain test bot (`bot.dega`) plus real-relay E2E scripts under `tools/` — 2026-09-07
- First-run onboarding: the panel autogenerates `~/.canon/dega-chat.env` (0600, idempotent) with the deployed backend URL and the Sepolia registry, leaving only the private key to the user — 2026-09-15
- DEGA right-pane plugin — host slot in canon-tui plus the `dega_panel` extension (Utility / Chat sub-tabs, element-gated access reading the `elements` aggregation shape, WhatsApp-style right-aligned own messages). Mock data; no backend wired — 2026-08-11
- Growth right-pane plugin — host slot in canon-tui plus the private `dega_growth` submodule (Overview / Discord / Telegram / Templates sub-tabs, Sheet-backed sends with mark-sent action, markdown templates) (`feat/growth-provider`) — 2026-05-08

### Changed
- DEGA chat defaults to the real on-chain backend (`DEGA_CHAT_BACKEND=chain`); `simulated` is only used by the headless layout harness — 2026-09-01
- Strategy archives are served only by the agents backend from the bundled `backend/strategies/` directory (no GCS bucket, no `DEGA_STRATEGIES_DIR` override, no public GitHub/codeload download) — 2026-09-15
- Strategy commands are selected explicitly (`build`/`dry run`/`live` metadata) instead of assuming `start`, and fees render with the token's real `decimals()` (18) rather than a hardcoded 1e8 — 2026-09-12
- Sign-in and pairing links are clickable; DEGA access wording clarified and contact creation moved into the sidebar — 2026-09-15/16
- Plan/Planning content is hidden by default; the Plan tab no longer opens automatically — 2026-09-15
- Right-pane width keybindings + agentic control (`20260505-pane-width`) — 2026-05-06

- Live updates for PlanExecutionTab — directory watch + interval backstop (`20260427-plan-tab-live-updates`) — 2026-04-27

- Canon TUI — bootstrap PlanExecutionModel + auto-open plan tab (`20260427-plan-execution-bootstrap`) — 2026-04-27

- Canon TUI view — PlanExecutionTab + dedicated section (`20260422-plan-execution-tab`) — 2026-04-23

- Canon TUI data layer — PlanExecutionModel (`20260422-plan-execution-model`) — 2026-04-22

- Clean up Canon TUI output (`clean-tui-output`) — 2026-04-08

- Auto-detect ACP adapter and skip install dialog (`auto-detect-acp`) — 2026-04-08

- Bootstrap install pattern for Canon TUI (`bootstrap-install`) — 2026-04-08

- Conductor TUI Integration (`conductor-tui-integration`) — 2026-04-07

- Horizontal Scroll for Gantt Timeline (`20260405-gantt-hscroll`) — 2026-04-05

- Live GitHub Timeline (replace static timeline.json) (`20260403-live-github-timeline`) — 2026-04-04

- Canon Builder + Automation sections for Toad TUI (`canon-sections`) — 2026-03-30

- Demo TUI Layout — Orchestrator-Aware Split Screen (`demo-tui-layout`) — 2026-03-30

### Fixed
- Chat UI: DMs are isolated per selected recipient, history from unregistered sender keys is shown, non-curve-point pubkeys are rejected before paying (the contract stores any 32-byte value and has no setter), and a bad peer no longer crashes the send worker — 2026-09-16
- Registry write gas is estimated per call (~480k for `openNode` with the reverse mapping + fee `transferFrom`) instead of a fixed 300k cap that reverted out-of-gas — 2026-09-15
- Runner hardening: stdout is drained in bounded chunks so a newline-less multi-MB line cannot accumulate or raise, and the runner state is finalized in `finally` — 2026-09-12
- Backend identity binding: `users.id` is DB-generated (`generated: "uuid"`) so account creation always returns the inserted id, emails are normalized before lookup/write, and device approval requires a session whose email matches — 2026-09-12
- Backend session cookies derive `SameSite`/`Secure` from an explicit `DEGA_COOKIE_CROSS_SITE` choice instead of proxy headers, and logout clears with the same flags — 2026-09-12

## [0.6.12] - 2026-03-13

### Fixed

- Fix broken output with Typeguard dependency

## [0.6.11] - 2026-03-13

### Added

- Added prompt message to settings

## [0.6.10] - 2026-03-13

### Fixed

- Fixed for agent that send blank text update (Mistral)

## [0.6.9] - 2026-03-11

### Fixed

- Fixed tool calls not refreshing
- Fixed tool call ordering
- Fixed anchoring behavor

### Changed

- Re-enabled experimental GC management via Textual
- The `end` key will now scroll the conversation to the end, if the cursor is already at the end of the prompt 

### Added

- Added Cursor to store

## [0.6.8] - 2026-03-03

### Fixed

- Removed gc management, due to expected memory issues

## [0.6.7] - 2026-03-02

### Fixed

- Fix for throbber crash

## [0.6.6] - 2026-03-02

### Changed

- Style tweaks for tools
- Some GC optimizations to smooth startup and scrolling

## [0.6.5] - 2026-02-27

### Added

- Added experimental OpenClaw support

## [0.6.4] - 2026-02-26

### Fixed

- Fixed large plans not appearing

### Changed

- Additional style tweaks, restore success color for terminal tools, tweaked margins for blocks

## [0.6.3]- 2026-02-25

### Changed

- Updated and improved style for Plans and Terminal tools

## [0.6.2]- 2026-02-24

### Changed

- Reverted a dubious style change on the store page

## [0.6.1] - 2026-02-24

### Changed

- New index for fuzzy searching makes searches faster for large repos

## [0.6.0] - 2026-02-16

### Added

- Added project directory switcher
- Added sessions, sessions tabs, sessions screen

### Fixed

- Fixed handling of agents that post null responses (OpenCode)

### Changed

- Added semantic styled edge to diff view

## [0.5.38] - 2026-02-01

### Fixed

- Fixed issue with agents empty thoughts breaking the block cursor

### Changed

- PathSearch and SlashCommand inputs are now overlays to avoid moving conversation content

## [0.5.37] - 2026-02-01

### Fixed

- Fixed session resume

## [0.5.36] - 2026-01-30

### Added

- Added toad.db sqlite database for non-config data
- Added Resume dialog (currently experimental, as agents don't yet support ACP)
- Added setting to disable title blink

### Fixed

- Fixed issue with empty terminal tools

## [0.5.35] - 2026-01-21

### Added

- Added GitHub CoPilot

### Changed

- The launcher hotkeys will now launch the agent immediately, and not just highlight the agent

## [0.5.34] - 2026-01-16

### Added

- Added display of slash command hints
- Added /toad:clear slash command

## [0.5.33] - 2026-01-16

### Fixed

- Fixed character level diff highlights

## [0.5.32] - 2026-01-15

### Fixed

- Fixed broken text form the input in commands

## [0.5.31] - 2026-01-14

### Changed

- Fix for diff highlights
- Minor cosmetic things

## [0.5.30] - 2026-01-14

### Fixed

- Fixed Terminals not focusing on click
- Fixed tool calls not rendered
- Fixed Kimi run command
- Fixed permissions screen not dispaying if "kind" is not set

### Added

- Added reporting of errors from acp initialize call
- Added Interrupt menu option to terminals

## [0.5.29] - 2026-01-11

### Added

- Set process title
- Additional help content

## [0.5.28] - 2026-01-11

### Fixed

- Fixed crash when running commands that clash with Content markup

## [0.5.27] - 2026-01-10

### Changed

- Updated Hugging Face Inference providers

## [0.5.26] - 2026-01-10

### Fixed

- Fixed issue with missing refreshes

### Added

- Added Target lines, and Additional lines, to settings

## [0.5.25] - 2026-01-09

### Added

- Added F1 key to toggle help panel
- Added context help to main widgets

### Changed

- Changed sidebar binding to ctrl+b

## [0.5.24] - 2026-01-08

### Added

- Added sound for permission request
- Added terminal title
- Added blinking of terminal title when asking permission
- Added an error message if the agent reports an internal error during its turn

## [0.5.23] - 2026-01-06

### Fixed

- A few style issue: tree background, status line padding

## [0.5.22] - 2026-01-06

### Fixed

- Fixes for settings combinations not taking effect

### Changed

- Restored prompt history
- The `/about` slash command has been renamed to `/toad:about`, to crate a namespace for future Toad commands

## [0.5.21] - 2026-01-05

### Changed

- Settings screen will now expand to full width when the screen is < 100 characters
- Sidebar will float if focused and "hide sidebar when not in use" setting is True
- Replace mac and linux shell settings with a single setting (you may have to update this you have changed the default)

### Fixed

- A more more defensive approach to watching directories, which may fixed stalling problem

## [0.5.20] - 2026-01-04

### Changed

- Smarter filesystem monitoring to avoid refreshes where nothing has changed

## [0.5.19] - 2026-01-04

### Added

- Added surfacing of "stop reason" from agents.
- Added `TOAD_LOG` env var (takes a path) to direct logs to a path.

## [0.5.18] - 2026-01-03

### Fixed

- Fixed footer setting

## [0.5.17] - 2026-01-03

### Fixed

- Fixed prompt settings not taking effect
- Fixed tool calls expanding but not updating the cursor

### Added

- Added atom-one-dark and atom-one-light themes

### Changed

- Allowed shell commands to be submitted prior to agent ready

## [0.5.15] - 2026-01-01

### Added

- Added pruning of very long conversations. This may be exposed in settings in the future.

### Fixed

- Fixed broken prompt with in question mode and the app blurs
- Fixed performance issue caused by timer

## [0.5.14] - 2025-12-31

### Added

- Added optional os notifications
- Added dialog to edit install commands

### Changed

- Copy to clipboard will now use system APIs if available, in addition to OSC52
- Implemented alternate approach to running the shell

## [0.5.13] - 2025-12-29

### Changed

- Simplified diff visuals
- Fixed keys in permissions screen

### Fixed

- Fixed broken shell after running terminals

## [0.5.12] - 2025-12-28

### Fixed

- Fixed eroneous suggestion on buffered input 

## [0.5.11] - 2025-12-28

### Fixed

- Fixed tree picker when project path isn't cwd

## [0.5.10] - 2025-12-28

### Added

- Added a tree view to file picker

## [0.5.9] - 2025-12-27

### Changed

- Optimized directory scanning and filtering. Seems fast enough on sane sized repos. More work require for very large repos.
- Fixed empty tool calls with terminals

## [0.5.8] - 2025-12-26

### Fixed

- Fixed broken tool calls

## [0.5.7] - 2025-12-26

### Changes

- Cursor keys can navigate between sections in the store screen
- Optimized path search
- Disabled path search in shell mode
- Typing in the conversation view will auto-focus the prompt

### Added

- Added single character switches https://github.com/DEGAorg/canon/pull/135

## [0.5.6] - 2025-12-24

### Fixed

- Fixed agent selector not focusing on run.
- Added project directory as second argument to `toad acp` rather than a switch.

## [0.5.5] - 2025-12-22

### Fixed

- Fixed column setting not taking effect

## [0.5.0] - 2025-12-18

### Added

- First release. This document will be updated for subsequent releases.

[0.6.12]: https://github.com/DEGAorg/canon/compare/v0.6.11...v0.6.12
[0.6.11]: https://github.com/DEGAorg/canon/compare/v0.6.10...v0.6.11
[0.6.10]: https://github.com/DEGAorg/canon/compare/v0.6.9...v0.6.10
[0.6.9]: https://github.com/DEGAorg/canon/compare/v0.6.8...v0.6.9
[0.6.8]: https://github.com/DEGAorg/canon/compare/v0.6.7...v0.6.8
[0.6.7]: https://github.com/DEGAorg/canon/compare/v0.6.6...v0.6.7
[0.6.6]: https://github.com/DEGAorg/canon/compare/v0.6.5...v0.6.6
[0.6.5]: https://github.com/DEGAorg/canon/compare/v0.6.4...v0.6.5
[0.6.4]: https://github.com/DEGAorg/canon/compare/v0.6.3...v0.6.4
[0.6.3]: https://github.com/DEGAorg/canon/compare/v0.6.2...v0.6.3
[0.6.2]: https://github.com/DEGAorg/canon/compare/v0.6.1...v0.6.2
[0.6.1]: https://github.com/DEGAorg/canon/compare/v0.6.0...v0.6.1
[0.6.0]: https://github.com/DEGAorg/canon/compare/v0.5.38...v0.6.0
[0.5.38]: https://github.com/DEGAorg/canon/compare/v0.5.37...v0.5.38
[0.5.37]: https://github.com/DEGAorg/canon/compare/v0.5.36...v0.5.37
[0.5.36]: https://github.com/DEGAorg/canon/compare/v0.5.35...v0.5.36
[0.5.35]: https://github.com/DEGAorg/canon/compare/v0.5.34...v0.5.35
[0.5.34]: https://github.com/DEGAorg/canon/compare/v0.5.33...v0.5.34
[0.5.33]: https://github.com/DEGAorg/canon/compare/v0.5.32...v0.5.33
[0.5.32]: https://github.com/DEGAorg/canon/compare/v0.5.31...v0.5.32
[0.5.31]: https://github.com/DEGAorg/canon/compare/v0.5.30...v0.5.31
[0.5.30]: https://github.com/DEGAorg/canon/compare/v0.5.29...v0.5.30
[0.5.29]: https://github.com/DEGAorg/canon/compare/v0.5.28...v0.5.29
[0.5.28]: https://github.com/DEGAorg/canon/compare/v0.5.27...v0.5.28
[0.5.27]: https://github.com/DEGAorg/canon/compare/v0.5.26...v0.5.27
[0.5.26]: https://github.com/DEGAorg/canon/compare/v0.5.25...v0.5.26
[0.5.24]: https://github.com/DEGAorg/canon/compare/v0.5.23...v0.5.24
[0.5.23]: https://github.com/DEGAorg/canon/compare/v0.5.22...v0.5.23
[0.5.22]: https://github.com/DEGAorg/canon/compare/v0.5.21...v0.5.22
[0.5.21]: https://github.com/DEGAorg/canon/compare/v0.5.20...v0.5.21
[0.5.20]: https://github.com/DEGAorg/canon/compare/v0.5.19...v0.5.20
[0.5.19]: https://github.com/DEGAorg/canon/compare/v0.5.18...v0.5.19
[0.5.18]: https://github.com/DEGAorg/canon/compare/v0.5.17...v0.5.18
[0.5.17]: https://github.com/DEGAorg/canon/compare/v0.5.16...v0.5.17
[0.5.16]: https://github.com/DEGAorg/canon/compare/v0.5.15...v0.5.16
[0.5.15]: https://github.com/DEGAorg/canon/compare/v0.5.14...v0.5.15
[0.5.14]: https://github.com/DEGAorg/canon/compare/v0.5.13...v0.5.14
[0.5.13]: https://github.com/DEGAorg/canon/compare/v0.5.12...v0.5.13
[0.5.12]: https://github.com/DEGAorg/canon/compare/v0.5.11...v0.5.12
[0.5.11]: https://github.com/DEGAorg/canon/compare/v0.5.10...v0.5.11
[0.5.10]: https://github.com/DEGAorg/canon/compare/v0.5.9...v0.5.10
[0.5.9]: https://github.com/DEGAorg/canon/compare/v0.5.8...v0.5.9
[0.5.8]: https://github.com/DEGAorg/canon/compare/v0.5.7...v0.5.8
[0.5.7]: https://github.com/DEGAorg/canon/compare/v0.5.6...v0.5.7
[0.5.6]: https://github.com/DEGAorg/canon/compare/v0.5.5...v0.5.6
[0.5.5]: https://github.com/DEGAorg/canon/compare/v0.5.0...v0.5.5
[0.5.0]: https://github.com/DEGAorg/canon/releases/tag/v0.5.0
