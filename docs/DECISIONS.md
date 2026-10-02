# Decisions and known issues

The approved decision log for VaultKeeper ("Account Manager - By BigH"), moved out of
`CLAUDE.md` (which keeps only the rules that apply to every task). Where a date is given, it
is when the user decided. Add new decisions here.

## Approved decisions

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
- Rank pictures (user, 2026-10-02): one optional picture per rank tier (shared by its
  divisions, even though Valorant has one per division), added by the user in Game setup
  from an .ico/.png file. Stored inside the vault (schema v3), shrunk to at most 64x64 PNG,
  so they are encrypted, backed up and move with the vault. No rank art ships with the app.
  Shown in the accounts table, the account form's rank picker and the search rank filter.
- Windows build (user, 2026-10-02): PyInstaller one-folder, `packaging/vaultkeeper.spec`.
  Two programs from one build: `Account Manager.exe` (windowed, the one to pin) and
  `Account Manager (console).exe` (console, for troubleshooting; the user deletes it once
  happy). Built to the Desktop. App icon embedded in the .exe, file details (BigH, version
  from `vaultkeeper.__version__`). No UPX, no admin rights, normal optimization level (the
  code has asserts). Not code-signed: SmartScreen "Run anyway" on first start. About
  100 MB per folder (mostly Qt).

## Known issues and deferred items

- **SEC-M4: Qt 5.15.2 has known CVEs.** The PyQt5 5.15.x wheels bundle Qt 5.15.2, which no
  longer receives open-source security fixes. Exposure here is low: the app makes no network
  calls, uses no web engine, never loads images or SVG from user data, and renders user text as
  plain text (SEC-H1). Plan: migrate to PyQt6 (Qt 6) as its own project. It is a new
  dependency, so it needs the user's OK first.
- **SEC-Low9: log tracebacks contain full file paths.** Tracebacks (for example from
  `log.exception` or the exception hook's location) include file paths, which can contain the
  Windows user name. No passwords, account data or exception messages are logged. Deferred:
  shorten paths in logged tracebacks. Until then the README asks users not to share log files
  publicly.
- **KDF upgrade prompt (not built).** `VaultService.kdf_needs_upgrade` exists but nothing in
  the UI uses it. Old vaults keep their weaker Argon2 parameters until the master password is
  changed. Proposal (needs the user's OK): after unlock, if it returns True, show a one-time
  note ("Your vault uses older, faster protection settings. Change your master password to
  upgrade them") with a button that opens Change master password. Keeping the same password
  would need a small re-encrypt-only path, because Change master password requires a
  different password today.
- **pyotp is pinned but unused** (TOTP was skipped). Remove it from `requirements.txt` only
  with the user's OK.
- **Source files over ~300 lines** (flagged, split only with the user's OK):
  `ui/app_controller.py` (394: move the backup/export wiring into its own class),
  `core/vault_service.py` (319), `core/backup.py` (306), `ui/main_window.py` (300).
- **File pickers are Qt's own dialogs** (CR-L5). Trade-off accepted: they don't look like
  Windows Explorer (no Quick Access pins, no Explorer previews).
- **Manual checks the automated tests can't do:** copied passwords don't appear in Win+V
  clipboard history; a second running copy says "already open" on the real vault; the
  "hide from screenshots" setting hides the windows from a real screenshot.
