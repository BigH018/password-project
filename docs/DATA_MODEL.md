# Data model (schema_version 2)

Reference for `core/models.py`, `core/game_template.py`, `core/serialization.py`,
`core/migrations.py`, `core/validation.py`, `core/template_validation.py` and `config/constants.py`.

## Account

| Field            | Type                     | Notes                                                  |
|------------------|--------------------------|--------------------------------------------------------|
| id               | str (uuid4)              | immutable                                              |
| game_id          | str (uuid4)              | must reference an existing Game                        |
| display_name     | str                      | in-game name (Riot ID name part)                       |
| tag              | str \| None              | part after `#` (Riot tag / BattleTag number)           |
| login_username   | str                      |                                                        |
| password         | str                      | **secret**                                             |
| email            | str                      |                                                        |
| email_password   | str \| None              | **secret**                                             |
| email_login_url  | str \| None              | http/https only, copy-only in the UI                   |
| region           | str \| None              | from the game's region list                            |
| rank             | Rank                     | see below                                              |
| status           | str                      | `active` \| `banned` \| `locked` \| `retired`          |
| recovery_email   | str \| None              |                                                        |
| totp_secret      | str \| None              | **secret**, base32; not shown (TOTP was skipped)       |
| tags             | tuple[str]               | labels; trimmed, de-duplicated case-insensitively      |
| notes            | str                      | free-form                                              |
| extra            | tuple[(field_id, value)] | values of the game's extra fields, sorted by id        |
| created_at       | str                      | ISO-8601 UTC                                           |
| updated_at       | str                      | ISO-8601 UTC                                           |

Secret fields (and `extra`) use `field(repr=False)`. `Account.__repr__` shows only `id` and
`game_id`.

Account-level rules (`validate_account`):
- At least one identifier: `login_username`, `display_name` or `email`.
- `display_name` must not contain `#`. A `tag` needs a `display_name`. If the tag is empty,
  `name#tag` typed into the name is split at the last `#` before validation.
- Secrets are never stripped or normalized. Other text is NFC-normalized and stripped.

Length limits live in `config/constants.py` and `core/game_template.py`. Character rules live
in `core/text_validation.py` (control characters are rejected, except newlines in notes).

## Rank

`Rank(tier: str | None, division: int | None)`
- `tier=None` means Unranked, and division must be None.
- The tier must be in the game's ladder. Division is **optional**. If given, it must be one of
  the tier's divisions. Tiers with 0 divisions must have None.

## Game and its template

| Field    | Type         | Notes                                     |
|----------|--------------|-------------------------------------------|
| id       | str (uuid4)  |                                           |
| name     | str          | unique case-insensitively                 |
| template | GameTemplate | ranks, regions, fields (below)            |

`GameTemplate` (`core/game_template.py`):
- `tiers`: ordered lowest first, each `TierDef(name, divisions 0-10)`.
- `best_division_is_one`: True if division 1 is the top (Overwatch, Marvel Rivals). False if
  the highest number is the top (Valorant).
- `roman_divisions`: show divisions as I/II/III.
- `regions`: ordered list.
- `hidden_fields`: optional standard fields not shown for this game. The choices are tag,
  region, rank, email_password, email_login_url and recovery_email. Name, login, password,
  email, status, labels and notes are always shown.
- `custom_fields`: extra fields, each `CustomField(id, label, kind, choices)`. `kind` is
  `text`, `number`, `choice` (dropdown with `choices`) or `secret`. Secret extra fields are
  masked, auto-cleared from the clipboard, never searched, never shown in table columns, and
  never logged. The `id` is stable, so renaming a label keeps values linked.

New games start from a **starter**: Valorant, Marvel Rivals or Overwatch (copied from the
verified presets in `config/constants.py`) or Blank. Every template is editable afterwards,
including the built-ins.

### Editing templates never deletes data
- `GameService.set_template` is never blocked by existing accounts.
- Hiding a standard field hides it in the form. The stored value is kept.
- A rank, region, dropdown option or extra field that's removed from the template stays on
  the accounts. The UI shows it marked "(not in this game's list)", for the account's own
  game only: switching the form to another game resets a rank or region that game doesn't
  list (switching back shows the stored value again).
- When an account is **edited in the same game**, kept values are accepted if unchanged.
  Changing a value to something outside the template is rejected.
- **Moving** an account to another game validates it fully against the new template. Extra
  values the new game doesn't have are dropped, and the dialog warns with the count first.
- Deleting a game is blocked (`GameInUseError`) while any account references it.

## Loading vs editing

Loading a vault checks **structure only** (`core/serialization.py`, `core/template_codec.py`).
Template rules (tier, division, region, extra values) are checked when an account is
**edited**. A template change can never stop a vault from opening.

## Search (`core/search.py`)

- Filter criteria combine with AND. Status, tier and region match any value in their set.
  Tags require ALL selected labels. Unranked is matched with `UNRANKED` (None).
- Free text: every word must appear (ignoring case) in name, tag, Riot ID, login, email,
  recovery email, notes, region, status, rank tier/division, labels, or a **non-secret**
  extra field. Extra fields are only searched when their ids are passed as `searchable_ids`
  (the UI passes `template.searchable_field_ids`). **Secrets are never searched.**
- Dropdown choices (`facets`): with one game selected, its ladder/regions in order, then any
  kept values not in it.
- Rank order: Unranked < ladder tiers (no division < lowest division … highest) < tiers not
  in the ladder (alphabetical).

## Paste assist (`core/paste_assist.py`)

Turns one pasted block into suggestions for the selected game. It never saves.
- Labeled lines first: `user:`/`login:`, `pass:`/`password:`, `email:`, `email pass:`,
  `recovery:`, `riot id:`/`ign:`/`name:`, `tag:`, `region:`, `rank:`, `status:`,
  `notes:`, and any extra field's label.
- Values of login/password lines are never scanned by the other rules.
- Password, email password and secret extra-field values are kept exactly as pasted (no
  Unicode normalization, like every secret). Labels and all other values are NFC-normalized.
- Unlabeled text: first `@` token -> email (a second -> recovery email); `name#tag`
  (no spaces; use `ign:` for names with spaces); a tier from the game's ladder or a known
  short form, plus a valid division; a region of the game (codes like EU/NA map to the
  game's names); `banned` -> status banned plus a note.
- Quick Add fills only EMPTY fields (status and notes are applied too) and shows what it
  filled, never the values.

## Duplicate rule

This is a non-blocking warning. Inside the same game, two accounts are duplicates if either of
these matches after trimming and case-folding:
- `login_username`, or
- `display_name#tag` (only when both have a display name; a missing tag counts as empty).

## Schema history
- **v1** (Phases 1–4c): games had a `preset` key (`valorant`, `marvel_rivals`, `overwatch`,
  `custom`). Custom games had free-text rank and region.
- **v2** (Phase 4d): games carry a full `template`, and accounts have `extra`.
  `migrate_v1_to_v2` copies built-in presets into templates. Custom games get a ladder and
  region list built from the distinct values their accounts already use. Account data is
  never changed.
