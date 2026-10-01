# CLAUDE.md — VaultKeeper

This is the permanent rulebook for every session. It loads automatically, so keep it lean:
only rules that apply to every task belong here, and reference material goes in `docs/`.
If a request conflicts with these rules, say so before acting.

---

## 0. Session start and task routing

### How to start every session
1. Read CLAUDE.md (it loads automatically). The file tree in §3.2 is your map of the project.
   It is accurate, so do NOT scan the repo or open every file to "get oriented".
2. Check §13 Status to see which phase we are in and what is built.
3. Classify the task with the routing table below. Read ONLY the files listed for that task
   type, plus anything those files directly need.
4. If a task doesn't fit the table, pick the closest row and use grep/glob to find what else
   is relevant. Do not read whole directories.

### Reading budget rules
- Read only what the task needs. A UI task does not need `crypto/`, and a crypto task does not need `ui/`.
- To use a service from another layer, read its public signatures only (grep for `def ` and
  `class `, or read the top of the file). Don't read internals unless you're changing them.
- Prefer grep for a symbol over opening a whole file. For a large file, read only the relevant range.
- Do not re-read a file that is already in this conversation unless it has changed.
- When you work on a module, read its matching test file. When you finish, run the relevant
  tests first, then the full suite before declaring done.
- Never open real data (§2), and never open vault files, backups or logs.

### Task routing table
Paths are relative to `src/vaultkeeper/` unless they start with `docs/`, `tests/`, `scripts/` or `packaging/`.

| Task type | Read first | Read only if needed |
|---|---|---|
| Crypto, KDF, vault format | docs/VAULT_FORMAT.md, crypto/*, storage/vault_file.py, errors.py | scripts/recover_vault.py (must stay in sync with the format); tests/test_header, test_kdf, test_cipher, test_envelope, test_vault_file, test_recover_script |
| Vault lifecycle (create, unlock, lock, change password) | core/vault_service.py, core/tasks.py, core/password_policy.py, errors.py, core/serialization.py | crypto/ signatures, storage/vault_file.py signatures, tests/test_vault_service.py, test_password_policy.py |
| Accounts, games, search, duplicates | docs/DATA_MODEL.md, core/models.py, the relevant service (account_service, game_service or search), core/store.py, core/validation.py | core/text_validation.py, matching test file, tests/conftest.py (FakeStore) |
| Data model or schema change | docs/DATA_MODEL.md, core/models.py, core/serialization.py, config/constants.py, tests/test_serialization.py | grep ui/ for the field to see where it is displayed |
| A UI screen or dialog | that ui file, the widgets it uses, ui/messages.py, ui/theme.py, and signatures of the services it calls | ui/app_controller.py (screen flow), ui/qt_adapters.py, tests/ui_support.py, matching tests/ui file |
| App startup, demo mode | app.py, demo.py, ui/app_controller.py | config/settings.py, config/logging_setup.py, tests/test_demo.py |
| Quick Add, batch mode, paste assist | ui/quick_add_dialog.py, core/entry_session.py, core/paste_assist.py, account_service signatures, core/validation.py signatures | tests/test_paste_assist.py, test_entry_session.py |
| Clipboard, auto-lock, session lock | security/*, ui/qt_adapters.py | tests/test_clipboard.py, test_autolock.py |
| Backups, export | core/backup.py, core/exporter.py, storage/vault_file.py | docs/VAULT_FORMAT.md |
| Password generator, TOTP | core/generator.py or core/totp.py, and the matching dialog | matching test file |
| Settings, paths, logging | config/*, ui/settings_dialog.py | |
| Packaging, dependencies | packaging/, pyproject.toml, requirements*.txt | |
| A failing test or bug | the failing test file and the module it tests | modules that one calls |

### Keeping the map accurate
When you add, rename, move or delete a file, or change a public function signature, update
the file tree (§3.2) and, if needed, the routing table **in the same change**. A stale map is
worse than none.

---

## 1. Purpose and use case

VaultKeeper is a **local-only desktop password manager** for a gamer with 150+ alt accounts
(~70 Valorant, ~30 Marvel Rivals, ~20 Overwatch, plus others). It is a password manager
**organized around games**.

- Python 3.11+, PyQt5, **fully offline**. The app makes NO network calls, ever.
- One encrypted vault file on the user's PC. Reopen, enter the master password, and everything comes back.
- Windows first. Stay cross-platform where it costs nothing.
- ~150 accounts will be entered **by hand**, so fast keyboard-only entry is a top priority.
- **Out of scope:** auto-typing into launchers, importers or parsers for old text files,
  plaintext export of any kind, sync/cloud, or anything that needs a network.

---

## 2. Absolute rules about real data

- **NEVER open, read, request, copy or paste real credential files**: the user's old text
  files, real vault files, backups, exports. If a path could hold real data (`*.vault`, `*.txt`
  in Documents/Desktop, `backups/`), don't touch it. Ask instead.
- **Never ask for real credentials**, not even one for testing.
- Fake data only: `player1@example.test`, `FakePlayer#TEST`, `Fake-Passw0rd-1!`, etc.
- Never commit `*.vault`, backups, exports, `.env`, logs or anything in `backups/`.
- **Do not enter real accounts until backups work (end of Phase 5).**

---

## 3. Architecture

### 3.1 Layers and dependency direction
```
ui ──► core ──► crypto, storage
│        └────► config, errors          (leaf modules: stdlib only)
└──► security ──► config, errors       (headless; Qt parts injected from ui)
crypto, storage ──► config, errors     (every layer may use the leaves)
app.py / main.py wire everything together. demo.py may use core (+ crypto for KdfParams).
scripts/recover_vault.py is standalone: it must NOT import vaultkeeper.
```
1. Dependencies flow one way: `ui -> core -> crypto/storage`. Lower layers never import higher ones.
   `tests/test_architecture.py` enforces this (its `ALLOWED_INTERNAL` table is the source of truth).
2. **`core`, `crypto`, `storage`, `security`, `config` and `errors` never import PyQt5.**
   Qt pieces (QClipboard, QTimer, worker threads, event filters, Windows session-lock
   notification) live in `ui/qt_adapters.py` and are injected through small Protocols.
3. `crypto` and `storage` deal in bytes and headers. They know nothing about accounts or games.
4. `ui` holds NO business or crypto logic. If a UI file decides a business rule, move it to `core`.
5. Slow work (Argon2) runs through an injected `TaskRunner` (`core/vault_service.py`):
   a pure *prepare* step runs on the runner, and the *commit* step updates state on the UI
   thread. Tests use `InlineTaskRunner` (`core/tasks.py`). The UI supplies `QtTaskRunner`
   (`ui/qt_adapters.py`): daemon threads so a hung KDF never blocks quitting, and
   `cancel_pending()` discards results when the user closes a dialog mid-work.
6. Constructor injection for collaborators (clock, executor, paths, KDF params, clipboard
   backend, scheduler). No module-level singletons holding state.

### 3.2 File tree
(P) = later phase. Any file past **~300 lines** gets flagged to the user for splitting.
```
vaultkeeper/                       repo root
  CLAUDE.md                        this rulebook
  README.md                        install/run, security notes, "lost master password = lost vault"
  requirements.txt                 pinned runtime deps
  requirements-dev.txt             pinned dev deps (pytest, pytest-qt, ruff, pyinstaller)
  pyproject.toml                   package metadata (src layout), pytest + ruff config
  .gitignore                       *.vault, backups/, .env, logs, build output
  docs/
    VAULT_FORMAT.md                byte layout, KDF defaults + rationale, bounds, atomic save
    DATA_MODEL.md                  Account/Game/Rank fields, presets, duplicate rule
  scripts/
    recover_vault.py               standalone decrypt-to-stdout (cryptography + argon2-cffi only)
  packaging/
    vaultkeeper.spec          (P)  PyInstaller spec (phase 8)
  src/vaultkeeper/
    __init__.py                    version string only
    __main__.py                    `python -m vaultkeeper` -> main.main()
    main.py                        entry point only -> app.run()
    app.py                         bootstrap: args (--demo), logging, settings, QApplication, cleanup
    demo.py                        throwaway temp-folder demo vault with fake accounts (--demo)
    errors.py                      custom exception hierarchy
    config/
      constants.py                 statuses, per-game rank/region presets, defaults, limits
      settings.py                  load/save non-secret settings JSON
      paths.py                     app-data dir and default file locations
      logging_setup.py             logging config + redaction filter (defense in depth)
    core/
      models.py                    dataclasses: Account, Game, Rank, VaultData (no I/O)
      serialization.py             VaultData <-> JSON dict, schema validation, migrations
      text_validation.py           generic text/secret/email/URL/uuid checks (clean_* helpers)
      validation.py                field rules (names, tags, labels, presets, ranks, TOTP) + validate_account
      store.py                     VaultStore protocol + apply_change (save or roll back in memory)
      password_policy.py           master password rules (min 12) + strength hint
      tasks.py                     TaskRunner protocol + InlineTaskRunner
      vault_service.py             create/unlock/lock/save/change password; backup-safe save after .bak
      account_service.py           account CRUD + duplicate detection (warning only)
      game_service.py              add/rename/set preset/delete games (blocked if accounts exist)
      search.py                    AccountFilter, free-text search (never secrets), rank sort key
      backup.py               (P)  rotating encrypted backups + "backup now"
      exporter.py             (P)  encrypted export with its own password
      entry_session.py        (P)  Quick Add batch state: sticky fields + session counter
      paste_assist.py         (P)  paste block -> field suggestions (pure, never saves)
      generator.py            (P)  password generator (secrets only)
      totp.py                 (P)  TOTP code + seconds remaining
    crypto/
      kdf.py                       Argon2id derivation + param bounds
      cipher.py                    AES-256-GCM via cryptography's AESGCM
      header.py                    header dataclass, pack/unpack, version checks
      envelope.py                  seal/open: header (as AAD) + nonce + ciphertext
    storage/
      vault_file.py                atomic write, verify-before-replace, .bak retention, .damaged quarantine
    security/
      clipboard.py            (P)  ClipboardGuard: copy + auto-clear if unchanged
      autolock.py             (P)  inactivity logic, Quick Add timeout override (injected clock)
    ui/
      qt_adapters.py               QtTaskRunner (daemon threads, cancel_pending); later clipboard/timers
      app_controller.py            screen flow: welcome -> create/unlock -> main; lock; quit
      theme.py                     Fusion + dark palette, shared label styles (QSS in Phase 8)
      welcome_dialog.py            create new vault / open existing file
      main_window.py               window: menus, backup banner, status bar (4a shell; table in 4b)
      unlock_dialog.py             master password, busy state, explicit "Try the backup copy"
      create_vault_dialog.py       location + master password + confirm + strength hint
      change_password_dialog.py (P) change master password
      account_dialog.py       (P)  full add/edit form
      game_manager_dialog.py  (P)  add/rename/delete games
      quick_add_dialog.py     (P)  keyboard-first batch entry + paste box + duplicate warning
      settings_dialog.py      (P)  timeouts, backup folder, keep-N, columns
      generator_dialog.py     (P)  password generator UI
      messages.py                  generic error texts (error_text) + confirm/error boxes
      widgets/
        account_table.py      (P)  table model + sort/filter proxy, masked secrets
        game_sidebar.py       (P)  game list with counts
        search_bar.py         (P)  free text + filter dropdowns
        rank_picker.py        (P)  tier + division combos driven by the game preset
        secret_field.py            masked edit with show/hide (copy button in Phase 5)
        strength_meter.py          live master-password strength bar + suggestions
        totp_display.py       (P)  live code + countdown
      styles/
        dark.qss              (P)  dark theme
  tests/
    conftest.py                    fast KDF params, network block (autouse), FakeStore, fixtures
    ui_support.py                  pytest plugin: off-screen Qt, QtTaskRunner, Gate (blocking KDF)
    fake_data.py                   obviously fake games/accounts
    test_architecture.py           AST scan: no PyQt5 in headless layers, no forbidden calls/imports
    test_no_network.py             flows run with sockets blocked
    test_models.py                 model invariants, repr hides secrets
    test_serialization.py          round trip, schema version, malformed input
    test_text_validation.py        limits, control/bidi chars, secrets untouched, email, URL
    test_validation.py             field rules, presets, ranks, whole-account validation
    test_constants.py              preset consistency (divisions, tiers, regions)
    test_settings.py               load/save, defaults, corrupt file handling, paths
    test_logging_setup.py          redaction, exceptions logged without messages
    test_header.py, test_kdf.py, test_cipher.py, test_envelope.py, test_vault_file.py
    test_vault_service.py, test_password_policy.py, test_recover_script.py
    test_accounts.py, test_games.py, test_search.py
    test_demo.py                   demo stays in temp, fake data only, cleaned up (even with open logs)
    test_backup.py, test_exporter.py, test_clipboard.py, test_autolock.py              (P)
    test_generator.py, test_entry_session.py, test_paste_assist.py, test_totp.py      (P)
    ui/                            pytest-qt: test_qt_adapters, test_unlock_dialog (never-silent
                                   backup, no freeze, closable while busy), test_create_vault_dialog,
                                   test_shell (welcome + main window)
```

---

## 4. DO
- Type hints everywhere. Docstrings on public modules, classes and functions. Small functions.
- Dependency injection. `secrets` for randomness. `hmac.compare_digest` for secret comparisons.
- Tests for every core/crypto/storage/security module. **Run the full suite before saying done.**
- Thin UI. Validate all input (including pasted text) at the service boundary.
- PEP 8, ~100-char lines, `ruff check` clean.
- Ask the user when a decision is theirs (fields, UX, features).

## 5. DON'T
- **No custom cryptography.** **No network calls** (`socket`, `urllib`, `http`, `requests`,
  `QNetwork*`, update checks, telemetry, runtime-fetched fonts/icons).
- **No logging secrets or PII** (passwords, email passwords, TOTP secrets, usernames, emails,
  Riot IDs, notes), not even at DEBUG. Log events and IDs only.
- **No plaintext on disk**: temp files, logs, settings, crash output, exports.
- No business logic in UI files. No giant files (flag >~300 lines).
- **No new dependencies without asking.** Approved: PyQt5, argon2-cffi, cryptography, pyotp,
  pytest, pytest-qt, PyInstaller, ruff.
- No real passwords/personal data anywhere. No committing vault/backup/export files.
- No `pickle`, `marshal`, `shelve`, `eval`, `exec`, `shell=True`, `yaml.load`, `random`.
- No bare `except:`, no silent swallowing.
- **NEVER open, read, request or paste real credential files** (§2).
- No AI/Claude attribution lines in commits or PRs. Plain commit messages.
- No raw non-ASCII or control characters in `.py` files: write `\u00e9`-style escapes
  (enforced by `test_architecture.py`; blocks invisible bidi "Trojan Source" characters).
  The file-writing tool may turn escapes into real characters, so run the tests after writing.

---

## 6. Security rules (non-negotiable)
1. Crypto only via `argon2-cffi` (Argon2id) and `cryptography` (AES-256-GCM).
2. Fresh 16-byte salt at creation and on every password change. Fresh 12-byte nonce on **every** save.
3. The whole header is AEAD associated data, so any changed byte fails loudly.
4. KDF params are stored in the header (upgradable). Header bounds are checked **before** running
   Argon2: time_cost ≤ 10, memory ≤ 1 GiB. Full spec in `docs/VAULT_FORMAT.md`.
5. Versioned header + payload schema. Unknown future versions are refused.
6. Atomic save: tmp → fsync → **decrypt and parse the tmp file to verify** → keep previous as
   `.bak` → `os.replace`. A crash can never leave a broken vault.
7. Never write plaintext secrets to disk/logs/temp/crash output. The exception hook logs type
   and location only. Our exception messages never contain user data.
8. Master password: minimum 12 characters, nudge toward passphrases, show a strength hint.
9. Wrong password → one generic message ("Wrong password or the vault file is damaged") plus a
   short fixed delay. No detail leaks.
10. Lock (inactivity, minimize, Windows session lock) drops the key and all decrypted data,
    clears UI models, closes all dialogs (unsaved drafts discarded), and clears the clipboard if
    it still holds our copy. **Honest limit:** Python can't guarantee memory zeroing. The key is
    a `bytearray` overwritten best-effort, and other copies drop when references go.
11. Secrets (`password`, `email_password`, `totp_secret`) are masked by default, left out of
    `repr()`, auto-cleared from the clipboard and never logged. Clipboard copies are excluded from
    Windows Clipboard History and cloud sync where Qt allows.
12. Argon2 never runs on the UI thread.
13. No pickle/eval/exec/shell=True. Validate all input. Pin all dependency versions.

## 7. Vault format (summary → `docs/VAULT_FORMAT.md`)
Binary header (magic `VKVAULT\0`, format version, file kind vault/export, Argon2id params,
salt, cipher id, nonce, ciphertext length) + AES-256-GCM ciphertext of a UTF-8 JSON payload
with `schema_version`. Key = Argon2id over the NFC-normalized UTF-8 password. KDF defaults
t=4, m=512 MiB, p=4 (about 0.3 s on the dev PC; target under ~1 s on a modest PC). Any format change must update
`docs/VAULT_FORMAT.md`, `scripts/recover_vault.py` and `tests/test_recover_script.py` together.

## 8. Data model (summary → `docs/DATA_MODEL.md`)
`Account` (game-linked by `game_id`, name + optional tag, login, secrets, email fields, region,
two-part rank, status, tags, notes, timestamps) and `Game` (name + preset that defines rank
ladder and regions). Duplicate check is a warning only: same game and the same login or name#tag.

---

## 9. Conventions and error handling
- `snake_case` modules/functions, `PascalCase` classes, `UPPER_SNAKE` constants. Qt classes end
  in `Widget`/`Dialog`/`Window`. Services are `XxxService`.
- `pathlib.Path`, timezone-aware UTC `datetime`, constants in `config/constants.py`, absolute
  `vaultkeeper.` imports.
- All exceptions inherit `vaultkeeper.errors.VaultKeeperError`: `VaultFormatError`,
  `VaultAuthError` (wrong password **or** tamper, deliberately the same), `VaultLockedError`,
  `VaultIOError`, `ValidationError` (field name, never the value), `WeakPasswordError`,
  `NotFoundError`, `DuplicateGameError`, `GameInUseError`.
- Translate library exceptions at layer boundaries. Use `from None` when chaining could leak data.
- The UI shows generic text via `ui/messages.py`. Unexpected errors go to a top-level hook.

## 10. Testing
- pytest (+ pytest-qt for UI smoke tests). Every headless module has a matching test file.
- Autouse fixture blocks sockets. `test_architecture.py` enforces layer and forbidden-call rules.
- Fake data only (`tests/fake_data.py`). Tests use tiny KDF params. Production params are
  `@pytest.mark.slow` (excluded by default).
- Required vault tests are listed in `docs/VAULT_FORMAT.md`.

```powershell
py -3.11 -m venv .venv; .venv\Scripts\Activate.ps1
pip install -r requirements.txt -r requirements-dev.txt; pip install -e .
pytest                 # fast suite
pytest -m slow         # production KDF params
ruff check .
python -m vaultkeeper  # run the app
```

## 10a. Git and GitHub

### Commits (local)
- Commit locally at the end of each approved phase and at other sensible checkpoints. Plain
  messages, no attribution lines.
- Before EVERY commit, run `git status` and `git diff --cached --stat`. Confirm that no
  `*.vault`, `backups/`, exports, `.env`, logs, real data or build output is staged. If anything
  suspicious is staged, stop and tell the user.

### Pushes (remote): approval required every time
- NEVER run `git push` in any form (`--force`, `--tags`, new branches) without the user's explicit
  approval **in that same turn**. An earlier "yes" does not carry over.
- After a major change (finished phase or feature, security-relevant change, large refactor),
  stop and ask: "I think this is a good point to push. Can I push to GitHub?" Include a 2–3
  line summary and `git log origin/main..HEAD --oneline`.
- Push only after a yes, then report the result.
- Never force-push, rewrite published history, change the remote URL, create/delete repos or
  branches, or alter git config without asking.
- Before the FIRST push: run a secrets check over the whole history (vault files, `.env`,
  anything credential-like), confirm `.gitignore` covers `*.vault`, `backups/`, exports, logs
  and `.env`, and report the result before asking.
- The remote must be a PRIVATE repository. If that can't be confirmed, say so before the first push.

## 11. Definition of Done
- [ ] Right layer. No PyQt5 in headless packages. No logic in UI.
- [ ] Type hints and docstrings. No file >~300 lines (or flagged).
- [ ] Input validated. Custom exceptions. No bare except.
- [ ] No secrets/PII in logs, reprs, messages, temp files or disk plaintext. No network.
- [ ] No unapproved dependencies. Versions pinned.
- [ ] Tests added/updated, including failure paths. **Full suite + ruff pass**, reported honestly.
- [ ] Fake data only. No vault/backup files staged.
- [ ] **Map and routing table updated** (§0, §3.2). §13 Status updated. docs/README updated if affected.
- [ ] Staged files checked for secrets. Push only with the user's approval (§10a).
- [ ] Summary to user (built / unsure). Wait for go-ahead. Commit after approval.

## 12. Build phases (one at a time, stop after each)
1. Scaffold, config (constants with verified rank presets, settings, paths, logging), errors, models, serialization, validation.
2. Crypto + storage + vault service (+ password policy, recovery script), with thorough tests.
3. Account + game services, search/filter, duplicate detection.
4. PyQt5 UI: create/unlock (KDF off the UI thread; damaged vault → OFFER `.bak`, never silent,
   with a pytest-qt test), main window, account dialog, game grouping, search.
5. Clipboard auto-clear, auto-lock (+ session lock), password generator, **encrypted export and rotating backups**.
6. Quick Add, batch mode, paste assist.
7. TOTP (optional field).
8. Polish: dark theme, settings dialog, error handling, PyInstaller .exe.

---

## 13. Decisions & Status

### Decisions (approved)
- Repo root is the project root. Package in `src/vaultkeeper`. File extension `.vault`. The
  location is chosen at vault creation.
- AES-256-GCM. Argon2id t=4 / 512 MiB / p=4, chosen so unlock stays under ~1 s on a modest PC
  (about 0.3 s measured on the dev PC). Header bounds t ≤ 10, m ≤ 1 GiB leave room to raise it.
- Per-game presets (Valorant, Marvel Rivals, Overwatch), verified against current sources,
  with the source and date in `constants.py`. Anything unverifiable is marked UNVERIFIED there
  (currently: Marvel Rivals regions). The custom preset has free-text rank and region.
- Riot ID = name + optional tag. Login URL is copy-only (no "open in browser").
- Deleting a game with accounts is blocked. Export uses a separate password (import later).
- Backups: after a save (max one per 10 min) plus on lock/exit if changed. Keep the last 10.
- Paste assist also reads `user:`/`pass:` style lines. It never saves automatically.
- No extra fields for now (the schema is versioned).
- Defaults: auto-lock 5 min, Quick Add inactivity 15 min, lock on minimize and on Windows
  session lock, clipboard clear 15 s. All configurable.
- TOTP stays optional. The user accepts the same-vault trade-off.
- Settings JSON lives in `%APPDATA%\VaultKeeper\` and holds no secrets.
- Commit after each approved phase, with plain messages. Commits use the GitHub noreply
  address (repo-local `user.email`); earlier commits are left as they are.
- Rank division is optional (a tier can be stored without one). Loading a vault checks
  structure only, not presets, so preset changes never stop an old vault from opening.
- An account needs at least one identifier: login username, in-game name or email.
- `pyproject.toml` reads dependencies from `requirements.txt` (single source of pins).
- The master password is NFC-normalized before the KDF (the app and the recovery script agree).
- Master password policy: ≥12 chars, ≥5 distinct chars, not on a small common-password list.
- Every service change saves immediately and rolls back in memory if the save fails.
- Free-text search covers notes but never secrets. Tag filters require ALL selected labels.
- A game's preset change is blocked if any account would become invalid (message gives count).
- Phase 4 backup UX: show "Try the backup copy" only when a `.bak` exists, worded as "only if
  you're sure the password is right". It never opens automatically.
- Phase 5: exports must use the `.vault` extension or live under `exports/` (both gitignored).
- After unlocking from `.bak`, the next save renames the main file to `<vault>.damaged-<time>`
  and leaves `.bak` untouched (a damaged file never overwrites the good backup).
- `--demo` uses a fresh `vaultkeeper-demo-*` folder in the system temp dir (vault, settings,
  logs), deleted on exit; leftovers are swept at the next demo start. Real settings untouched.

### Status
- [x] Step 0: CLAUDE.md + plan approved
- [x] Phase 1: Scaffold, config, models
- [x] Phase 2: Crypto, storage, vault service, recovery script (pushed 9372fb1)
- [x] Phase 3: Account/game services, search (committed 0bc7cc3; validation split into
      text_validation.py + validation.py)
- [ ] Phase 4: Core UI
  - [x] 4a: foundation, welcome, create, unlock (+ backup offer/banner), task runner, shell, --demo
  - [ ] 4b: full main window (sidebar, search, table, lock, change master password)
  - [ ] 4c: account dialog, game manager
- [ ] Phase 5: Clipboard, auto-lock, generator, export, backups
- [ ] Phase 6: Quick Add, batch mode, paste assist
- [ ] Phase 7: TOTP
- [ ] Phase 8: Polish + packaging
