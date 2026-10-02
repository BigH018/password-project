# CLAUDE.md — VaultKeeper

This is the permanent rulebook for every session. It loads automatically, so keep it lean:
only rules that apply to every task belong here, and reference material goes in `docs/`.
If a request conflicts with these rules, say so before acting.

---

## 0. Session start and task routing

### How to start every session
1. Read CLAUDE.md (it loads automatically). The file tree in §3.2 is your map of the project.
   It is accurate, so do NOT scan the repo or open every file to "get oriented".
2. Check §12 Status to see what is built and what is next. Past decisions are in
   `docs/DECISIONS.md`: grep it when a task touches an earlier choice.
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
| Data model or schema change | docs/DATA_MODEL.md, core/models.py, core/game_template.py, core/rank_image.py, core/serialization.py, core/template_codec.py, core/migrations.py, tests/test_serialization.py, tests/test_migrations.py | grep ui/ for the field to see where it is displayed |
| A UI screen or dialog | that ui file, the widgets it uses, ui/messages.py, ui/safe_text.py, ui/file_pickers.py, ui/theme.py, and signatures of the services it calls (main window: also ui/accounts_view.py) | ui/app_controller.py (screen flow), ui/qt_adapters.py, tests/ui_support.py, matching tests/ui file |
| App startup, demo mode | app.py, demo.py, ui/app_controller.py | config/settings.py, config/logging_setup.py, tests/test_demo.py |
| Game templates, Game setup | docs/DATA_MODEL.md, core/game_template.py, core/template_validation.py, ui/game_setup_dialog.py | ui/widgets/ladder_editor.py, field_toggles.py, ui/rank_pictures.py (+ where shown: account_table.py, rank_picker.py, search_bar.py), core/rank_image.py, extra_fields_editor.py, account_form.py, tests/test_templates.py, tests/ui/test_game_setup.py, tests/ui/test_rank_pictures.py |
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
- The user should choose a backup folder (File -> Backups...) before
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
(P) = not built yet. Any file past **~300 lines** gets flagged to the user for splitting.
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
    DECISIONS.md                   approved decision log + known issues / deferred items
    images/                        README screenshots (demo mode, fake data only) + icon.png
  scripts/
    recover_vault.py               standalone decrypt-to-stdout (cryptography + argon2-cffi only)
  packaging/
    vaultkeeper.spec          (P)  PyInstaller spec (phase 8e)
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
      game_template.py             GameTemplate/TierDef (+ optional picture)/CustomField,
                                   starters from presets
      template_codec.py            GameTemplate <-> JSON dict (strict structure checks)
      template_validation.py       clean_template (Game setup) + clean_extra (extra field values)
      migrations.py                migrate_v1_to_v2 (preset key -> template, accounts get extra),
                                   migrate_v2_to_v3 (ranks get image: null)
      rank_image.py                rank pictures: small-PNG check (<= 64x64, 24 KB, no Qt) +
                                   base64 text form stored in the template
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
      game_setup_dialog.py         Game setup: game list + editor (name, starter) with tabs Ranks and
                                   Fields and regions (live counts in tab/box titles);
                                   asks before discarding unsaved edits (switch game, Close, Esc)
      quick_add_dialog.py          Quick Add (AccountDialog subclass): Enter = save & next,
                                   batch values, counter, paste box, Ctrl+Enter anywhere
      settings_dialog.py           File -> Settings (Ctrl+,): auto-lock/Quick Add timeouts, clipboard
                                   seconds, lock switches, show-passwords seconds, screen-capture
                                   exclusion, restore defaults, Backups... button
      generator_dialog.py          password generator (copy or "use" into the form)
      file_pickers.py              choose_folder / choose_save_file / choose_open_file /
                                   choose_image_file (.ico/.png): Qt's own
                                   (non-native) dialog, so auto-lock sees activity and lock
                                   closes it
      rank_pictures.py             rank pictures: .ico/.png file -> PNG <= 64x64 (largest .ico
                                   frame, PNG/ICO only, <= 5 MB), picture_icon/pixmap,
                                   tier_icons(template) (rank name -> icon, for display),
                                   PicturePicker (remembers the folder, error box if unusable)
      safe_text.py                 plain_label / message_box (Qt.PlainText: user data is never
                                   rendered as HTML), link_label for fixed app text only
      messages.py                  generic error texts (error_text, FIELD_LABELS = on-screen field
                                   names) + confirm/error/warning boxes + run_modal (exec_ then
                                   deleteLater: closed dialogs never linger)
      error_dialog.py              ErrorReporter: "Something went wrong" notice for uncaught errors
                                   (queued, any thread, one at a time, Open log folder)
      widgets/
        account_table.py           table model (passwords masked, extra columns, never secret) + proxy;
                                   rank presets + rank pictures cached per set_rows
        game_sidebar.py            "All games" + games with counts
        search_bar.py              free text + status/rank/region/label dropdowns -> AccountFilter;
                                   rank pictures only when one game is selected
        account_form.py            form built from the game template (hidden fields, extra fields)
        ladder_editor.py           rank list editor: tall table (tiers + divisions + pictures),
                                   actions + picture preview on the right, division style
        field_toggles.py           Game setup checkboxes: which optional standard fields show
        add_rank_dialog.py         quick add: rank name, has divisions? how many (1-10), optional
                                   picture; Enter = next
        extra_fields_editor.py     extra fields editor: label, type, dropdown options (ids kept)
        rank_picker.py             RankPicker (tier + division) and RegionPicker, driven by the game
                                   template (with rank pictures); values not in the list shown
                                   marked, never dropped
        secret_field.py            masked edit with show/hide; clear() also wipes undo history
                                   (copying is done from the table)
        strength_meter.py          live master-password strength bar + suggestions
      styles/
        dark.qss                   dark theme (ASCII, no url()/images; package data)
      assets/
        app_icon.ico               16-256px icon built from icon_source_32px.ico (package data)
  tests/
    conftest.py                    fast KDF params, network block (autouse), FakeStore, fixtures;
                                   registers ui_support, backup_helpers, vault_file_helpers
    *_helpers.py                   shared helpers/fixtures of split test files (no tests):
                                   vault_service_helpers, vault_file_helpers, backup_helpers
    ui_support.py                  pytest plugin: off-screen Qt, QtTaskRunner, Gate (blocking KDF),
                                   SessionGuard shutdown + gc after each test, default stubs for
                                   messages.confirm/show_error/show_warning
    fake_data.py                   obviously fake games/accounts, tiny_png() test picture
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
    test_header.py, test_kdf.py, test_cipher.py, test_envelope.py
    test_vault_file.py             atomic save, .bak, quarantine; test_vault_file_safety.py:
                                   exclusive temp files, shared folder, directory sync
    test_vault_service.py          create/unlock/crypto/lock/async; _saving.py: .bak, damaged
                                   files, failed saves; _password.py: password change
    test_password_policy.py, test_recover_script.py
    test_vault_disk.py             save refused if the file changed on disk (second instance)
    test_accounts.py, test_games.py, test_search.py
    test_demo.py                   demo stays in temp, fake data only, cleaned up (even with open logs)
    test_templates.py              templates: presets, codec, validation, extra values, secret search
    test_migrations.py             schema v1 -> v2 -> v3 (incl. a real encrypted v1 vault)
    test_rank_image.py             rank picture PNG check, base64 round trip
    test_backup.py                 copies, rotation, paths; test_backup_status.py: failures,
                                   password-change helpers, prepare/run/finish
    test_exporter.py, test_clipboard.py, test_autolock.py, test_generator.py
    test_entry_session.py, test_paste_assist.py
    ui/                            pytest-qt: test_qt_adapters, test_unlock_dialog (never-silent
                                   backup, no freeze, closable while busy), test_create_vault_dialog,
                                   test_change_password_dialog, test_main_window (real demo vault),
                                   test_account_dialog, test_game_setup, test_pickers (+ game switching),
                                   test_shell (welcome, controller lock/demo details),
                                   test_phase5_ui (copy, auto-lock, generator, backups-off banner),
                                   test_backup_export_ui (Backups/export dialogs, lock path),
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
                                   test_account_table (rank preset built once per game),
                                   test_secret_field (clear() wipes undo in all password dialogs),
                                   test_rank_pictures (file -> picture, set/remove, add form, save),
                                   test_rank_pictures_shown (table, rank picker, search filter),
                                   test_game_setup_layout (tabs + counts, field toggles, preview)
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
with `schema_version` (currently 3). Key = Argon2id over the NFC-normalized UTF-8 password.
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
- [ ] **Map and routing table updated** (§0, §3.2). §12 Status updated. docs/README updated if affected.
- [ ] Staged files checked for secrets. Push only with the user's approval (§10a).
- [ ] Summary to user (built / unsure). Wait for go-ahead. Commit after approval.

## 12. Status
Phases 1-6 are done and pushed: core, crypto/storage, services, UI, clipboard/auto-lock,
backups/export, Quick Add. Phase 7 (TOTP) was skipped by the user. The code review and security
audit fixes (32 items, 2026-10-01) are all done and pushed. Past decisions, known issues and
deferred items (including manual checks only the user can do) are in `docs/DECISIONS.md`:
grep it when a task touches an earlier choice, and record new decisions there.

- [ ] **Phase 8e: .exe (next).** Decided: PyInstaller one-folder build, windowed (`app.py`
      already guards prints when stdout is None), bundle dark.qss and the icon from
      `ui/assets/`, spec in `packaging/vaultkeeper.spec`. Antivirus false positives: mention,
      don't work around. Bundle Qt's `imageformats/qico.dll` (rank pictures from .ico files)
      and check it works in the built .exe.

### Work rules for a list of tasks or fixes
Do them in the agreed order, ONE COMMIT PER TASK. For each one: check whether it's already
done; for a bug, write the failing test first and confirm it fails for the RIGHT reason; make
the change; run the relevant tests, then the full suite + ruff; `git status` +
`git diff --cached --stat` (nothing sensitive staged); commit locally with a plain message.
Update the map/routing/docs in the same commit. If a task is bigger or riskier than expected,
or needs a vault format change, stop and ask. If you disagree with a request, say so with
evidence instead of changing code. After a group of tasks, summarise and ask to push (§10a).

### Practical notes
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
