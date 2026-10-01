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
| Vault lifecycle (create, unlock, lock, change password) | core/vault_service.py, core/vault_disk.py, core/tasks.py, core/password_policy.py, errors.py, core/serialization.py | crypto/ signatures, storage/vault_file.py signatures, tests/test_vault_service.py, test_vault_disk.py, test_password_policy.py |
| Accounts, games, search, duplicates | docs/DATA_MODEL.md, core/models.py, core/game_template.py, the relevant service (account_service, game_service or search), core/store.py, core/validation.py | core/text_validation.py, matching test file, tests/conftest.py (FakeStore) |
| Data model or schema change | docs/DATA_MODEL.md, core/models.py, core/game_template.py, core/serialization.py, core/template_codec.py, core/migrations.py, tests/test_serialization.py, tests/test_migrations.py | grep ui/ for the field to see where it is displayed |
| A UI screen or dialog | that ui file, the widgets it uses, ui/messages.py, ui/safe_text.py, ui/file_pickers.py, ui/theme.py, and signatures of the services it calls (main window: also ui/accounts_view.py) | ui/app_controller.py (screen flow), ui/qt_adapters.py, tests/ui_support.py, matching tests/ui file |
| App startup, demo mode | app.py, demo.py, ui/app_controller.py | config/settings.py, config/logging_setup.py, tests/test_demo.py |
| Game templates, Game setup | docs/DATA_MODEL.md, core/game_template.py, core/template_validation.py, ui/game_setup_dialog.py | ui/widgets/ladder_editor.py, extra_fields_editor.py, account_form.py, tests/test_templates.py, tests/ui/test_game_setup.py |
| Quick Add, batch mode, paste assist | ui/quick_add_dialog.py, core/entry_session.py, core/paste_assist.py, account_service signatures, core/validation.py signatures | tests/test_paste_assist.py, test_entry_session.py |
| Clipboard, auto-lock, session lock | security/*, ui/session_guard.py, ui/qt_adapters.py, ui/copy_actions.py | tests/test_clipboard.py, test_autolock.py, tests/ui/test_phase5_ui.py |
| Backups, export | core/backup.py, core/exporter.py, storage/vault_file.py, ui/backup_dialog.py, ui/export_dialog.py | docs/VAULT_FORMAT.md, ui/app_controller.py (wiring) |
| Password generator | core/generator.py, ui/generator_dialog.py | tests/test_generator.py |
| Settings, paths, logging | config/*, ui/settings_dialog.py | ui/app_controller.py (`_open_settings`), ui/session_guard.py (apply_settings) |
| Packaging, dependencies | packaging/, pyproject.toml, requirements*.txt | |
| A failing test or bug | the failing test file and the module it tests | modules that one calls |

### Keeping the map accurate
When you add, rename, move or delete a file, or change a public function signature, update
the file tree (§3.2) and, if needed, the routing table **in the same change**. A stale map is
worse than none.

---

## 1. Purpose and use case

VaultKeeper is a **local-only desktop password manager** for a gamer with a large
number of accounts across several games (Valorant, Marvel Rivals, Overwatch and others). It is a password manager
**organized around games**.

- Python 3.11+, PyQt5, **fully offline**. The app makes NO network calls, ever.
- One encrypted vault file on the user's PC. Reopen, enter the master password, and everything comes back.
- Windows first. Stay cross-platform where it costs nothing.
- Many accounts will be entered **by hand**, so fast keyboard-only entry is a top priority.
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
- Backups work (Phase 5). The user should choose a backup folder (File -> Backups...) before
  entering real accounts; the app shows a "backups are off" banner until they do.

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
   a pure *prepare* step (inputs snapshotted on the caller's thread) runs on the runner, and the *commit* step updates state on the UI
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
  README.md                        GitHub front page: features, setup, shortcuts, security, FAQ
  LICENSE                          MIT, copyright BigH
  requirements.txt                 pinned runtime deps
  requirements-dev.txt             pinned dev deps (pytest, pytest-qt, ruff, pyinstaller)
  pyproject.toml                   package metadata (src layout), pytest + ruff config
  .gitignore                       *.vault, backups/, .env, logs, build output
  docs/
    VAULT_FORMAT.md                byte layout, KDF defaults + rationale, bounds, atomic save
    DATA_MODEL.md                  fields, game templates, search, paste assist, duplicates, schema history
    images/                        README screenshots (demo mode, fake data only) + icon.png
  scripts/
    recover_vault.py               standalone decrypt-to-stdout (cryptography + argon2-cffi only)
  packaging/
    vaultkeeper.spec          (P)  PyInstaller spec (phase 8)
    icon_source_32px.ico           the user's 32px icon: app_icon.ico is built from it (crisp
                                   pixel upscale to 16-256px; the app uses only the .ico)
    icon_source.jpg                the user's 1920px icon art, used only for docs/images/icon.png
                                   (README). Third-party art, not MIT: see README
  src/vaultkeeper/
    __init__.py                    version string only
    __main__.py                    `python -m vaultkeeper` -> main.main()
    main.py                        entry point only -> app.run()
    app.py                         bootstrap: args (--demo), logging, settings, QApplication, cleanup
    demo.py                        throwaway temp-folder demo vault with fake accounts (--demo)
    errors.py                      custom exception hierarchy
    config/
      constants.py                 statuses, per-game rank/region presets, defaults, limits
      settings.py                  load/save non-secret settings JSON (incl. window geometry,
                                   last backup success/failure times, last-saved time per vault);
                                   SettingsFile = current settings + update-and-save
      paths.py                     app-data dir and default file locations
      logging_setup.py             logging config + redaction filter (defense in depth); exception
                                   hooks log type/location, then call an argument-less on_error
    core/
      models.py                    dataclasses: Account (+ extra values), Game (+ template), Rank, VaultData
      game_template.py             GameTemplate/TierDef/CustomField, starters from presets
      template_codec.py            GameTemplate <-> JSON dict (strict structure checks)
      template_validation.py       clean_template (Game setup) + clean_extra (extra field values)
      migrations.py                migrate_v1_to_v2 (preset key -> template, accounts get extra)
      serialization.py             VaultData <-> JSON dict, structure validation, runs migrations
      text_validation.py           generic text/secret/email/URL/uuid checks (clean_* helpers;
                                   identity=True rejects Unicode Cf), strip_format_characters
      validation.py                field rules (names, tags, labels, presets, ranks, TOTP) + validate_account;
                                   split_name_and_tag (name#tag typed in the name, tag empty)
      store.py                     VaultStore protocol + apply_change (save or roll back in memory)
      password_policy.py           master password rules (min 12, measured without padding or
                                   invisible characters) + strength hint
      tasks.py                     TaskRunner protocol + InlineTaskRunner
      vault_service.py             create/unlock/lock/save/change password; backup-safe save after
                                   .bak; on_saved listeners (backups)
      vault_disk.py                file on disk vs session: digest, verifier, quarantine_target
                                   (damaged -> .damaged copy; changed elsewhere -> VaultConflictError);
                                   went_back_in_time / remember_saved_at (SEC-M3); shared_folder_risk
      account_service.py           account CRUD + duplicate detection (warning only)
      game_service.py              add (starter/template) / rename / set_template (never blocked) / delete
      search.py                    AccountFilter, free-text search (never secrets), facets, rank sort key
      backup.py                    rotating backups (byte copies of the encrypted vault), keep N;
                                   prepare (UI thread) / run_backup_job (worker) / finish;
                                   after a password change: back up now, find old-password backups (salt)
      exporter.py                  encrypted export (own password, file kind EXPORT, .vault)
      entry_session.py             Quick Add batch state: sticky game/region/status + counter,
                                   starting_game_id (sidebar game first, else last batch game)
      paste_assist.py              paste block -> field suggestions (pure, never saves)
      generator.py                 password generator (secrets only)
    crypto/
      kdf.py                       Argon2id derivation + param bounds
      cipher.py                    AES-256-GCM via cryptography's AESGCM
      header.py                    header dataclass, pack/unpack, version checks
      envelope.py                  seal/open: header (as AAD) + nonce + ciphertext
    storage/
      vault_file.py                atomic write, verify-before-replace, .bak retention, .damaged
                                   quarantine, write_bytes_atomic / copy_file_verified (backups, exports);
                                   temp files created exclusively (O_EXCL); folder_may_be_shared
    security/
      clipboard.py                 ClipboardGuard: copy + auto-clear only if unchanged
      autolock.py                  InactivityTracker: timeout, Quick Add override (injected clock)
    ui/
      qt_adapters.py               QtTaskRunner, QtClipboardBackend (Win+V exclusion), qt_schedule,
                                   ActivityFilter, SessionLockWatcher (Windows lock via ctypes),
                                   VaultInstanceLock (QLockFile <vault>.lock, stale after a crash),
                                   set_capture_excluded + CaptureFilter (Windows display affinity)
      session_guard.py             ClipboardGuard + auto-lock wiring; emits lock_needed(reason);
                                   applies the screen-capture exclusion setting
      copy_actions.py              copy actions (Ctrl+B/C/E on the table) + right-click menu
      backup_dialog.py             backup folder / keep N / interval + Backup now;
                                   after_password_change (offer to delete old-password backups);
                                   typed folder applied after a 400 ms pause, full paths only
      export_dialog.py             encrypted export (own password; cancel writes nothing)
      app_controller.py            screen flow: welcome -> create/unlock -> main; lock (closes dialogs); quit;
                                   backups on their own runner (quit waits <= 15 s for one);
                                   holds the vault's instance lock from the unlock prompt until quit
      branding.py                  app icon (all .ico sizes) on every window, Windows taskbar
                                   AppUserModelID, no "?" help button on dialogs
      theme.py                     Fusion + dark palette + styles/dark.qss (fallback: palette
                                   only), shared label styles
      welcome_dialog.py            create new vault / open existing file
      main_window.py               actions, backup banners (opened from .bak, backups off, last
                                   backup failed), status bar, delete; hosts AccountsPanel
      main_menus.py                toolbar + File/Games/Tools menus built from the window's actions
      accounts_view.py             AccountsPanel: game sidebar | search bar over sortable table;
                                   reveal_timer ("Show passwords" switches itself off)
      unlock_dialog.py             master password, busy state, explicit "Try the backup copy",
                                   small "Open a different vault file..." link (restore / moved vault);
                                   check_last_saved/record_last_saved ("Last saved", older-file warning)
      create_vault_dialog.py       location + master password + confirm + strength hint
      change_password_dialog.py    change master password (KDF off-thread, closable while busy)
      account_dialog.py            add/edit: AccountForm + live duplicate warning + unsaved-changes
                                   prompt (force_close() skips it on lock)
      game_setup_dialog.py         Game setup: list + editor (starter, ranks, regions, fields, extras);
                                   asks before discarding unsaved edits (switch game, Close, Esc)
      quick_add_dialog.py          Quick Add (AccountDialog subclass): Enter = save & next,
                                   batch values, counter, paste box, Ctrl+Enter anywhere
      settings_dialog.py           File -> Settings (Ctrl+,): auto-lock/Quick Add timeouts, clipboard
                                   seconds, lock switches, show-passwords seconds, screen-capture
                                   exclusion, restore defaults, Backups... button
      generator_dialog.py          password generator (copy or "use" into the form)
      file_pickers.py              choose_folder / choose_save_file / choose_open_file: Qt's own
                                   (non-native) dialog, so auto-lock sees activity and lock
                                   closes it
      safe_text.py                 plain_label / message_box (Qt.PlainText: user data is never
                                   rendered as HTML), link_label for fixed app text only
      messages.py                  generic error texts (error_text, FIELD_LABELS = on-screen field
                                   names) + confirm/error/warning boxes + run_modal (exec_ then
                                   deleteLater: closed dialogs never linger)
      error_dialog.py              ErrorReporter: "Something went wrong" notice for uncaught errors
                                   (queued, any thread, one at a time, Open log folder)
      widgets/
        account_table.py           table model (passwords masked, extra columns, never secret) + proxy
        game_sidebar.py            "All games" + games with counts
        search_bar.py              free text + status/rank/region/label dropdowns -> AccountFilter
        account_form.py            form built from the game template (hidden fields, extra fields)
        ladder_editor.py           rank list editor: tiers + divisions, order, division style
        add_rank_dialog.py         quick add: rank name, has divisions? how many (1-10); Enter = next
        extra_fields_editor.py     extra fields editor: label, type, dropdown options (ids kept)
        rank_picker.py             RankPicker (tier + division) and RegionPicker, driven by the game
                                   template; values not in the list shown marked, never dropped
        secret_field.py            masked edit with show/hide; clear() also wipes undo history
                                   (copying is done from the table)
        strength_meter.py          live master-password strength bar + suggestions
      styles/
        dark.qss                   dark theme (ASCII, no url()/images; package data)
      assets/
        app_icon.ico               16-256px icon built from icon_source_32px.ico (package data)
  tests/
    conftest.py                    fast KDF params, network block (autouse), FakeStore, fixtures
    ui_support.py                  pytest plugin: off-screen Qt, QtTaskRunner, Gate (blocking KDF),
                                   SessionGuard shutdown + gc after each test, default stubs for
                                   messages.confirm/show_error/show_warning
    fake_data.py                   obviously fake games/accounts
    test_architecture.py           AST scan: no PyQt5 in headless layers, no forbidden calls/imports,
                                   labels/message boxes only via ui/safe_text.py, dialogs
                                   only via messages.run_modal, file pickers only via
                                   ui/file_pickers.py
    test_no_network.py             flows run with sockets blocked
    test_models.py                 model invariants, repr hides secrets
    test_serialization.py          round trip, schema version, malformed input
    test_text_validation.py        limits, control/bidi chars, secrets untouched, email, URL
                                   (Cf in identity fields: tests/test_validation.py)
    test_validation.py             field rules, presets, ranks, whole-account validation
    test_constants.py              preset consistency (divisions, tiers, regions)
    test_settings.py               load/save, defaults, corrupt file handling, paths, geometry,
                                   SettingsFile
    test_logging_setup.py          redaction, exceptions logged without messages, on_error notice
    test_header.py, test_kdf.py, test_cipher.py, test_envelope.py, test_vault_file.py
    test_vault_service.py, test_password_policy.py, test_recover_script.py
    test_vault_disk.py             save refused if the file changed on disk (second instance)
    test_accounts.py, test_games.py, test_search.py
    test_demo.py                   demo stays in temp, fake data only, cleaned up (even with open logs)
    test_templates.py              templates: presets, codec, validation, extra values, secret search
    test_migrations.py             schema v1 -> v2 (incl. a real encrypted v1 vault)
    test_backup.py, test_exporter.py, test_clipboard.py, test_autolock.py, test_generator.py
    test_entry_session.py, test_paste_assist.py
    ui/                            pytest-qt: test_qt_adapters, test_unlock_dialog (never-silent
                                   backup, no freeze, closable while busy), test_create_vault_dialog,
                                   test_change_password_dialog, test_main_window (real demo vault),
                                   test_account_dialog, test_game_setup, test_pickers (+ game switching),
                                   test_shell (welcome, controller lock/demo details),
                                   test_phase5_ui (copy, auto-lock, generator, backups, export),
                                   test_backup_async (slow folder: no freeze, lock, queue, quit),
                                   test_backup_ui (backups after a password change, failure
                                   banner until a backup works, last successful backup),
                                   test_quick_add (save & next, batch, paste, keys, timeout),
                                   test_theme (stylesheet loads, offline, palette fallback),
                                   test_branding (icon, titles, no "?", window hidden while locked),
                                   test_settings_dialog (values, defaults, save + apply live),
                                   test_window_geometry (saved on lock/quit, restored at start),
                                   test_error_dialog (notice, threads, field labels complete),
                                   test_plain_text (HTML-looking user data shown literally),
                                   test_account_form (name#tag split on focus-out),
                                   test_cleanup (menus, boxes, dialogs deleted after use),
                                   test_last_saved ("Last saved" on unlock, older-file warning,
                                   where a damaged copy was kept),
                                   test_reveal_and_capture (Show passwords timeout, capture),
                                   test_dialog_paths (full paths, unreadable folders, debounce),
                                   test_file_pickers (non-native, closed on lock, activity),
                                   test_secret_field (clear() wipes undo in all password dialogs)
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
  pytest, pytest-qt, PyInstaller, ruff. (pyotp is pinned but unused since TOTP was skipped;
  remove it only with the user's OK.)
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
11. Secrets (`password`, `email_password`, `totp_secret`, secret extra fields) are masked by
    default, never searched or shown as table columns, left out of
    `repr()`, auto-cleared from the clipboard and never logged. Clipboard copies are excluded from
    Windows Clipboard History and cloud sync where Qt allows.
12. Argon2 never runs on the UI thread.
13. No pickle/eval/exec/shell=True. Validate all input. Pin all dependency versions.

## 7. Vault format (summary → `docs/VAULT_FORMAT.md`)
Binary header (magic `VKVAULT\0`, format version, file kind vault/export, Argon2id params,
salt, cipher id, nonce, ciphertext length) + AES-256-GCM ciphertext of a UTF-8 JSON payload
with `schema_version` (currently 2). Key = Argon2id over the NFC-normalized UTF-8 password.
KDF defaults t=4, m=512 MiB, p=4 (about 0.3 s on the dev PC; target under ~1 s on a modest
PC). Backups are byte copies; exports use file kind 2. Any format change must update
`docs/VAULT_FORMAT.md`, `scripts/recover_vault.py` and `tests/test_recover_script.py` together.

## 8. Data model (summary → `docs/DATA_MODEL.md`)
`Account` (game-linked by `game_id`, name + optional tag, login, secrets, email fields, region,
two-part rank, status, tags, notes, extra field values, timestamps) and `Game` (name + its own
editable template: ranks, regions, shown fields, extra fields). Editing a template never deletes
account data. Duplicate check is a warning only: same game and the same login or name#tag.

---

## 9. Conventions and error handling
- `snake_case` modules/functions, `PascalCase` classes, `UPPER_SNAKE` constants. Qt classes end
  in `Widget`/`Dialog`/`Window`. Services are `XxxService`.
- `pathlib.Path`, timezone-aware UTC `datetime`, constants in `config/constants.py`, absolute
  `vaultkeeper.` imports.
- All exceptions inherit `vaultkeeper.errors.VaultKeeperError`: `VaultFormatError`,
  `VaultAuthError` (wrong password **or** tamper, deliberately the same), `VaultLockedError`,
  `VaultIOError`, `ValidationError` (field name, never the value), `WeakPasswordError`,
  `NotFoundError`, `DuplicateGameError`, `GameInUseError`, `VaultConflictError` (file changed
  on disk since it was loaded; save refused), `KeyDerivationError` (Argon2 failed, e.g. low
  memory; friendly fixed message).
- Translate library exceptions at layer boundaries. Use `from None` when chaining could leak data.
- The UI shows generic text via `ui/messages.py`. Unexpected errors go to a top-level hook
  that logs type and location only, then `ui/error_dialog.py` shows a generic notice (the
  app keeps running).

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
7. ~~TOTP~~ skipped by the user (2026-10-01).
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
  (currently: Marvel Rivals regions). Presets are now only STARTERS for game templates (4d).
- Riot ID = name + optional tag. Login URL is copy-only (no "open in browser").
- Deleting a game with accounts is blocked. Export uses a separate password (import later).
- Backups: after a save (max one per 10 min) plus on lock/exit if changed. Keep the last 10.
- Backups run off the UI thread (CR-L6): the vault bytes are read on the UI thread (never
  holding the file open during a save), the backup folder work runs on a separate runner
  (not cancelled by lock: only ciphertext, result still recorded). One at a time; a request
  while busy follows. Quit waits up to 15 s, then makes the exit backup synchronously.
  Backups dialog "Backup now" and the post-password-change backup stay synchronous (the
  user waits for their result). Controller tests that need sync backups pass
  `backup_runner=InlineTaskRunner()`.
- After a master-password change (CR-M1/SEC-M1): `.bak` is re-saved under the new password,
  a backup is made at once, and the user is offered to delete backups that still open with the
  old password (found by header salt; only offered once a new-password backup exists).
- Closed dialogs, message boxes and context menus are deleted after use (CR-M4): every
  dialog runs through `messages.run_modal` (architecture test), the context menu deletes
  itself and drops its "Copy <secret field>" actions. Test fakes need a no-op
  `deleteLater`.
- Temp files (vault, .bak staging, settings) are created exclusively (SEC-Low7). The create
  and unlock dialogs show a warning (never a block) if other users may be able to change
  files in the vault's folder: on Windows a drive root, one level below it (e.g. C:\Vaults)
  or the Public folder; elsewhere a group/world-writable folder.
- "Show passwords" switches itself off after `show_passwords_seconds` (default 30 s, 5-600)
  and on lock (SEC-Low6). Optional `exclude_from_capture` (default off, Windows only, a
  no-op elsewhere): every top-level window gets SetWindowDisplayAffinity(WDA_EXCLUDEFROM
  CAPTURE) via an app-wide filter; applied live from the Settings dialog.
- Rollback notice (SEC-M3): after unlock the status bar shows "Last saved: <time>". Settings
  keep the last `updated_at` seen per vault path (timestamps only, max 20 vaults). If a vault
  opens OLDER than that (not when opened from `.bak`), a warning says it may be an old copy
  put back; it warns once, then the file becomes the new reference. Recorded at unlock and
  after every save.
- Two running copies (SEC-M2): the controller takes `<vault>.lock` (QLockFile, stale only when
  the owner process is gone) before the unlock prompt and keeps it until quit; a second copy
  gets "already open" and the welcome screen. Backstop: a save is refused
  (VaultConflictError) if the file changed on disk since it was read or written (SHA-256).
- Backup failures (CR-H2) are logged by error type only and shown as a banner ("Last backup
  failed at <time>") until a backup succeeds. The last success/failure times are kept in
  settings, so a failure at lock or exit shows after the next unlock.
- Paste assist also reads `user:`/`pass:` style lines. It never saves automatically.
- Defaults: auto-lock 5 min, Quick Add inactivity 15 min, lock on minimize and on Windows
  session lock, clipboard clear 15 s. All configurable.
- TOTP: SKIPPED (user decision, 2026-10-01). `Account.totp_secret` stays in the model and
  schema (validated, never shown in the UI). Don't build TOTP unless the user asks again.
- Settings JSON lives in `%APPDATA%\VaultKeeper\` and holds no secrets.
- Commit after each approved phase, with plain messages. Commits use the GitHub noreply
  address (repo-local `user.email`); earlier commits are left as they are.
- Rank division is optional (a tier can be stored without one). Loading a vault checks
  structure only, not presets, so preset changes never stop an old vault from opening.
- An account needs at least one identifier: login username, in-game name or email.
- Identity fields (name, tag, login, emails, email URL, game name) reject Unicode Cf
  (SEC-Low3). ZWJ is NOT allowed there (user told 2026-10-01): no game needs multi-part emoji
  in names, and it would let look-alike duplicates through. Notes and labels allow Cf.
- `name#tag` typed into the name with the tag empty is split (CR-M3): in core on save, and
  in the form on focus-out. If the tag is filled in too, the name's '#' is still an error.
- `pyproject.toml` reads dependencies from `requirements.txt` (single source of pins).
- The master password is NFC-normalized before the KDF (the app and the recovery script agree).
- Master password policy: ≥12 chars, ≥5 distinct chars, not on a small common-password list.
  Measured after NFC without Unicode Cf characters and surrounding whitespace (SEC-Low1);
  the key still uses the password exactly as typed (NFC only). Never checked at unlock.
- Every service change saves immediately and rolls back in memory if the save fails.
- Free-text search covers notes but never secrets. Tag filters require ALL selected labels.
- Phase 4 backup UX: show "Try the backup copy" only when a `.bak` exists, worded as "only if
  you're sure the password is right". It never opens automatically.
- Exports always use the `.vault` extension (gitignored, like `exports/`).
- After unlocking from `.bak`, the next save copies the main file to `<vault>.damaged-<time>`
  (never moves it, so a failed save can't leave the vault missing) and leaves `.bak`
  untouched (a damaged file never overwrites the good backup). The same happens if the main
  file stops decrypting with the session key while unlocked. The user is then told once
  where the damaged copy was kept (full path; CR-L7).
- One vault is the normal case. "Create a new vault" is only offered on the first-run Welcome
  screen. The unlock screen has a small "Open a different vault file..." link (for restoring a
  backup or a moved vault) that opens a file picker directly.
- Lock closes every open dialog (drafts discarded via `force_close()`, no prompt), cancels
  pending work, clears the window.
- Account dialog: rank/region are preset dropdowns (free text for custom games). A stored
  value not in the preset is shown marked "(not in this game's list)" rather than dropped,
  but only for the account's own stored game (CR-M2): switching the form to another game
  resets a rank/region that game doesn't list; switching back brings the stored value back.
  After saving, the edited/new row stays selected.
- Per-game templates (4d): every game, built-ins included, has editable ranks (tiers + 0-10
  divisions, entered as "has divisions? how many?"), regions, shown standard fields and
  extra fields (text/number/dropdown/secret).
  Template edits are never blocked and never delete data (kept values marked "not in this
  game's list"). This replaced "block a preset change if accounts become invalid".
- Minimum account = a game + one of username / in-game name / email. Password, email and
  everything else are optional (tested: username + password only).
- No silent default game: adding from "All games" starts on "Choose a game..." (rank and
  region disabled until chosen); a selected sidebar game is pre-filled.
- UI tests stub `messages.confirm`/`show_error` by default (`tests/ui_support.py`): a real
  modal box left open at teardown crashes Qt.
- Game setup asks "Discard changes?" before switching games or closing with unsaved edits
  (CR-L4); No keeps the edited game selected. force_close() (lock) never asks.
- Delete key only deletes while the account table has focus. Edit has no keyboard shortcut
  (rows open on double-click/Enter in 4c) so Enter in text fields is never hijacked.
- Copy shortcuts follow KeePass (Ctrl+B username, Ctrl+C password) plus Ctrl+E email; they
  only act while the table has focus. Status messages name what was copied, never the value.
  Copies carry the Windows formats that exclude them from Clipboard History/cloud sync.
- Auto-lock: inactivity (default 5 min), minimize, Windows session lock (WTS notification).
  Locking clears our clipboard copy and backs up if anything changed.
- Backups are byte copies of the encrypted vault (same master password), named
  `<vault>-backup-YYYYMMDD-HHMMSS[-N].vault`; rotation only touches this vault's backups and
  orders them by parsed timestamp + counter (never by file name; CR-L1). A
  "backups are off" banner shows until a folder is chosen. Demo backups stay in the demo folder.
- A cancelled export writes nothing (checked after the KDF, before writing).
- Backup folder and export file must be full (absolute) paths (CR-L3). Folders that can't be
  read give a VaultIOError / "Can't read this folder", never the crash notice. The Backups
  dialog lists a typed folder only after a 400 ms pause (Browse, Save and Backup now apply
  at once); Cancel restores the previous values exactly.
- UI tests: `QApplication.quit` is a no-op (`tests/ui_support.py`); a controller quitting
  at teardown used to stop event delivery for later tests.
- Quick Add opens on the game selected in the sidebar; with "All games" it opens on the last
  batch game (`EntrySession.starting_game_id`).
- Quick Add (Ctrl+Shift+N): Enter saves and starts a fresh form (Ctrl+Enter also works in
  Notes/paste box); Esc closes (asks if anything is typed). Game, region and status stick
  between entries; the "N added this session" counter resets on lock. While it's open the
  auto-lock timeout is the Quick Add one (default 15 min).
- Paste assist: labeled lines win (user:/pass:/email:/riot id:/region:/rank:/status: and
  extra-field labels); login/password values are never scanned by other rules; unlabeled
  text: @ -> email, name#tag, rank words (+ short forms like plat/imm/t500) and regions of
  the selected game, "banned" -> status + note. It fills EMPTY fields only and never saves.
- Branding (user, 2026-10-01): windows show "Account Manager - By BigH" (`WINDOW_TITLE`)
  and the user's icon, and dialogs have no "?" help button. `APP_NAME`/`APP_DIR_NAME` stay "VaultKeeper" internally (settings
  folder, logs, default paths) so existing data is found.
- The main window is hidden whenever the vault is locked: welcome/create/unlock dialogs are
  parentless (own taskbar button), `setQuitOnLastWindowClosed(False)` so the controller
  decides when to quit. Locked by minimizing -> the unlock prompt starts minimized.
- Settings dialog (8b): saved and applied at once (SessionGuard.apply_settings), merged into
  the current settings so Backups changes made meanwhile are kept. If saving fails the values
  still apply and the status bar says so. The Windows-lock watcher is always registered and
  the setting is checked when it fires, so toggling it needs no restart.
- Window geometry (8c): `Settings.window_geometry` = Qt saveGeometry() as base64 (validated:
  base64 chars, <= 2048). Saved on lock and quit only if the window is visible; restored when
  the controller builds the window (Qt pulls it back on screen; maximized is kept). Settings
  version stays 1: the field has a default, so old files load.
- Error notice (8d): uncaught errors are logged (type/location) and show "Something went
  wrong" with the log folder; the app keeps running (every change is already saved). The
  notice never receives the exception. Validation messages use on-screen labels
  (`FIELD_LABELS`; a test checks every core field name has one).
- UI tests: every SessionGuard is shut down and `gc.collect()` runs after each test
  (`tests/ui_support.py`). Without it, guards' app-wide event filters were deleted by the GC
  mid-event in a later test: a Windows access violation (seen in 8d).
- File pickers are Qt's own dialogs, not the native Windows ones (CR-L5, 2026-10-01): a native
  picker runs its own message loop, so auto-lock didn't see activity in it and lock couldn't
  close it. Cost: they look like the app (dark theme) rather than Explorer.
- Spin boxes are left unstyled in dark.qss (QSS can't draw arrows without image files).
- User data is never rendered as HTML (SEC-H1): labels and message boxes come from
  `ui/safe_text.py` (Qt.PlainText), form-row labels with user text use `plain_label`, and
  tooltips are fixed text. `test_architecture.py` enforces it.
- Demo master password is `test` (user, 2026-10-01). The throwaway demo vault is the only one
  created without the password policy (`VaultService.create(..., check_policy=False)`, only
  allowed in demo.py: architecture test). Changing it inside the demo still needs a strong one.
- `--demo` uses a fresh `vaultkeeper-demo-*` folder in the system temp dir (vault, settings,
  logs), deleted on exit; leftovers are swept at the next demo start. Real settings untouched.

### Status
- [x] Step 0: CLAUDE.md + plan approved
- [x] Phase 1: Scaffold, config, models
- [x] Phase 2: Crypto, storage, vault service, recovery script
- [x] Phase 3: Account/game services, search (validation later split into
      text_validation.py + validation.py)
- [x] Phase 4: Core UI
  - [x] 4a: foundation, welcome, create, unlock (+ backup offer/banner), task runner, shell, --demo
  - [x] 4b: full main window (sidebar, search, table, lock, change master password)
  - [x] 4c: account dialog, game manager (replaced by Game setup in 4d)
  - [x] 4d: per-game templates (custom ranks/regions/fields/extra fields), Game setup, schema v2
- [x] Phase 5: Clipboard, auto-lock, generator, export, backups
- [x] Phase 6: Quick Add, batch mode, paste assist (pushed with the docs update)
- [-] Phase 7: TOTP (skipped by the user)
- [ ] Phase 8: Polish + packaging (IN PROGRESS)
  - [x] 8a: dark theme (dark.qss loaded by theme.py)
  - [x] 8a+: branding (title, icon, taskbar id), main window hidden while locked
  - [x] 8b: settings dialog  - [x] 8c: window geometry  - [x] 8d: error dialog
  - [ ] 8e: .exe (after the review fixes below). Decided: PyInstaller one-folder build,
        windowed (`app.py` already guards prints when stdout is None), bundle dark.qss and
        the icon from `ui/assets/`, spec in `packaging/vaultkeeper.spec`. Antivirus false
        positives: mention, don't work around.
- [ ] Review fixes (CR = code review, SEC = security audit), started 2026-10-01: IN PROGRESS

### Review fixes: handoff (read this when continuing in a fresh session)
Work rules the user set: fix in the order below, ONE COMMIT PER FIX. For each fix: check
whether it's already done; write the failing test first and confirm it fails for the RIGHT
reason; fix; run the relevant tests, then the full suite + ruff; `git status` +
`git diff --cached --stat` (nothing sensitive staged); commit locally with a plain message,
no attribution. Update the map/routing/docs in the same commit. STOP after each group:
summarise, ask "I think this is a good point to push. Can I push to GitHub?" with the commit
list, and wait (push only on a yes in that turn). No vault format change expected: if one
is needed, stop and ask. If a fix is bigger or riskier than expected, stop and say so. If
you disagree with a finding, say so with evidence instead of changing code. If context gets
long: finish the group, ask for the push, and tell the user to continue with "continue from
Group N". `docs/DECISIONS.md` doesn't exist yet (step 31 creates it).

Group 1 (done, pushed):
- [x] 1 SEC-H1 user data never rendered as HTML (`ui/safe_text.py`, architecture rule)
- [x] 2 SEC-H2 SecretField.clear() wipes undo history
- [x] 3 SEC-Low2 paste assist keeps secret values exactly as pasted (no NFC)

Group 2 (done, pushed with this CLAUDE.md update):
- [x] 4 CR-H1/SEC-Low8 quarantine copies the damaged main file, never moves it
- [x] 5 CR-L2 a main file that no longer decrypts never becomes `.bak`
- [x] 6 CR-M1/SEC-M1 after a password change: `.bak` re-saved, backup now, offer to delete
      old-password backups (found by header salt)
- [x] 7 CR-H2 backup failures logged (type only) + banner until a backup works; status
      times in settings; Backups dialog shows last success
- [x] 8 SEC-M2 instance lock (`VaultInstanceLock`, QLockFile) + save refused if the file
      changed on disk (`core/vault_disk.py`, VaultConflictError)

Group 3 (done, pushed): entry workflow and lock rule
- [x] 9 CR-M2 switching game on the account form resets rank/region not in the new game's
      list; "not in list" values are kept only for the account's own stored game
- [x] 10 CR-M3 Tag empty + Name contains name#tag -> split with split_tagged_id (focus-out
      or save)
- [x] 11 CR-M4 deleteLater() on context menus after exec_() (copy_actions.py) and on the
      QMessageBox in messages.py (nothing holding secrets survives a lock); test menus deleted
- [x] 12 CR-L1 backup rotation sorts by parsed timestamp + counter, not file name
      (same-second backups)
- [x] 13 SEC-M3 show "Last saved: <updated_at>" on unlock; keep last-seen updated_at per
      vault path in settings (timestamp only); warn if the vault goes backwards in time

Group 4 (done, pushed): input and key-derivation hardening
- [x] 14 SEC-Low1 password_policy: NFC first, strip surrounding whitespace and Unicode Cf
      before length/common-list checks (tests: decomposed chars, trailing space, ZWSP)
- [x] 15 SEC-Low3 reject Unicode Cf in names, logins, identity fields (ZWJ only if needed
      for emoji: tell the user); tests for LRM, RLM, ZWSP, word joiner, soft hyphen, tag chars
- [x] 16 SEC-Low4/5 Argon2 HashingError (e.g. low memory) -> clear VaultKeeperError; lone
      surrogates (UnicodeEncodeError) in kdf.py -> VaultAuthError without echoing the char
- [x] 17 SEC-Low7 temp files opened exclusively (O_EXCL, no symlink following) in
      vault_file.py and the settings writer; warn (don't block) at create/open if the folder
      looks writable by other users (e.g. directly under C:\)
- [x] 18 SEC-Low6 "Show passwords" switches off after a configurable timeout (default 30 s)
      and on lock; optional setting (off, Windows only, tested no-op elsewhere) for
      SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)

Group 5 (done, pushed): small and deferred items
- [x] 19 CR-L3 full paths required in backup/export dialogs; unreadable folders handled
      without "Something went wrong"; don't list the folder on every keystroke (debounce or
      on confirm)
- [x] 20 CR-L7 tell the user where the .damaged copy was saved (`last_damaged_copy`)
- [x] 21 CR-L4 game setup warns before discarding unsaved edits (switching game, Close)
- [x] 22 CR-L6 backups off the UI thread via the injected TaskRunner; keep the failure
      banner; lock waits for or safely cancels a running backup
- [x] 23 CR-L8 `_prepare_change` must not read `self._session` on the worker thread: pass
      what it needs as arguments (it also copies `disk_digest` now)
- [x] 24 CR-L9 directory fsync failure after a successful replace: don't report "could not
      save" or undo the change; log the type and carry on
- [x] 25 CR-L5 native file pickers aren't counted as activity / not closed by
      close_dialogs: try Qt's non-native dialogs; switch if reasonable, else report options

Group 6 (in progress): cleanup (one commit each)
- [x] 26 remove dead code: clean_preset_key, split_tagged_id (only if unused after 10),
      PasteSuggestions.describe, ClipboardGuard.holds_copy, AccountFilter.is_empty,
      InactivityTracker.enabled, AccountForm._current_game. Report whether kdf_needs_upgrade
      is used (propose an upgrade prompt, don't build) and whether pyotp is still needed
      DONE: removed all but split_tagged_id (used by split_name_and_tag). Reported to the
      user: kdf_needs_upgrade unused by the UI (upgrade prompt proposed, not built); pyotp
      unused (removal awaits the user's OK).
- [x] 27 make `_BIDI_CONTROLS` public (now `BIDI_CONTROLS`), update importers
- [x] 28 Quick Add opens on the sidebar's selected game, else the last batch game
- [ ] 29 cache the template-to-preset conversion in account_table.py
- [ ] 30 split tests/test_vault_service.py and tests/ui/test_phase5_ui.py under ~300 lines;
      also split `ui/app_controller.py` (394 lines: move backup/export wiring out),
      `core/backup.py` (306: e.g. old-password helpers out) and
      `core/vault_service.py` (319); flag `ui/main_window.py` (~300)
- [ ] 31 move the §13 decision log to docs/DECISIONS.md with a pointer; add known/deferred:
      SEC-M4 (Qt 5.15.2 CVEs, plan PyQt6) and SEC-Low9 (log tracebacks contain full paths);
      README note that log files shouldn't be shared
- [ ] 32 add any missing tests the reviews listed that aren't covered above
- [ ] Final: whole suite + ruff, summarise all commits, ask for the final push

Open items to mention to the user: confirm by hand that copied passwords don't appear in
Win+V clipboard history, and that a second copy of the app says "already open" on the real
vault (demo mode uses a fresh temp folder each time, so it can't show this).

### Practical notes for future sessions
- The file-writing tool can turn `\uXXXX`/`\x..` escapes into raw characters: write such
  characters with `chr(...)`, and run the tests (ASCII check) after writing.
- Long multi-line patches through bash heredocs sometimes fail to parse: write a small
  patch script to the scratchpad and run it instead. In heredoc'd Python, a `\n` escape inside a
  string can still end up as a real newline: use the Edit tool for lines with escapes.
- Tests: never call `monkeypatch.undo()`. It also lifts the autouse network block (same
  monkeypatch instance); use `with monkeypatch.context() as patch:` instead.
- UI tests capture message boxes via `messages.confirm`/`messages.show_error` (stubbed by
  default): call them through the `messages` module so the stub applies.
- Run the app with fake data: `.venv\Scripts\python -m vaultkeeper --demo`
  (password `test`).
