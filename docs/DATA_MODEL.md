# Data model (schema_version 1)

Reference for `core/models.py`, `core/serialization.py`, `core/validation.py` and `config/constants.py`.

## Account

| Field            | Type                 | Notes                                                      |
|------------------|----------------------|------------------------------------------------------------|
| id               | str (uuid4)          | immutable                                                  |
| game_id          | str (uuid4)          | must reference an existing Game                            |
| display_name     | str                  | in-game name (Riot ID name part)                           |
| tag              | str \| None          | part after `#` (Riot tag / BattleTag number)               |
| login_username   | str                  |                                                            |
| password         | str                  | **secret**                                                 |
| email            | str                  |                                                            |
| email_password   | str \| None          | **secret**                                                 |
| email_login_url  | str \| None          | http/https only, copy-only in the UI                       |
| region           | str \| None          | must be in the game preset's region list                   |
| rank             | Rank                 | see below                                                  |
| status           | str                  | `active` \| `banned` \| `locked` \| `retired`              |
| recovery_email   | str \| None          |                                                            |
| totp_secret      | str \| None          | **secret**, base32 (Phase 7)                               |
| tags             | list[str]            | trimmed, de-duplicated case-insensitively                  |
| notes            | str                  | free-form                                                  |
| created_at       | str                  | ISO-8601 UTC                                               |
| updated_at       | str                  | ISO-8601 UTC                                               |

Secret fields use `field(repr=False)`. `Account.__repr__` shows only `id` and `game_id`.

Account-level rules (`validate_account`):
- At least one identifier: `login_username`, `display_name` or `email`.
- `display_name` must not contain `#`. A `tag` needs a `display_name`.
- Secrets are never stripped or normalized. Other text is NFC-normalized and stripped.

Length limits live in `config/constants.py`; character rules in `core/text_validation.py` (control characters are
rejected, except newlines in notes).

## Rank

`Rank(tier: str | None, division: int | None)`
- `tier=None` → Unranked, and division must be None.
- The tier must exist in the game preset's ladder.
- Division is **optional**. If given, it must be one of the tier's divisions from the preset
  (e.g. Overwatch 5→1). Tiers without divisions (Radiant, Eternity, Top 500) must have None.

## Game

| Field  | Type        | Notes                                                    |
|--------|-------------|----------------------------------------------------------|
| id     | str (uuid4) |                                                          |
| name   | str         | unique case-insensitively                                |
| preset | str         | `valorant` \| `marvel_rivals` \| `overwatch` \| `custom` |

- Renaming changes only `name`, because accounts reference `game_id`.
- Deleting is blocked (`GameInUseError`) while any account references the game.
- Changing `preset` is blocked (`ValidationError`, message gives the count) if any of the
  game's accounts would fail validation under the new preset. Accounts are never changed
  automatically.
- Moving an account to another game re-validates it against that game's preset.

## When preset rules apply

Preset rules (tier, division, region) are checked when an account is **edited**, not when a
vault is **loaded**. Loading checks structure only (`core/serialization.py`), so a vault still
opens after a game renames a tier. The UI shows unknown values as-is.

## Presets (`config/constants.py`)

Each preset defines an ordered tier list, which tiers have divisions, the division range and
order, and a region list. Ladders are checked against current official sources when written
(Phase 1). The source and date are recorded in a comment next to each preset. Anything that
couldn't be verified is marked UNVERIFIED in `constants.py`.

The `custom` preset (`free_text=True`) has no fixed ladder or region list. Rank is free text
stored in `Rank.tier` (division must be None), and region is free text. Unknown preset keys
fall back to `custom`.

Marvel Rivals regions are UNVERIFIED: broad groups (NA, EU, SA, Asia, OCE, ME) from third-party
server maps, because no official NetEase list was found (checked 2026-10-01).

## Search (`core/search.py`)

- Filter criteria combine with AND. Status, tier and region match any value in their set.
  Tags require ALL selected labels. Unranked is matched with `UNRANKED` (None).
- Free text: every word must appear (ignoring case) in name, tag, Riot ID, login, email,
  recovery email, notes, region, status, rank tier/division or labels. **Secrets are never
  searched.**
- Rank order: Unranked < ladder tiers (no division < lowest division … highest) < unknown or
  free-text tiers (alphabetical).

## Duplicate rule

This is a non-blocking warning. Inside the same game, two accounts are duplicates if either of
these matches after trimming and case-folding:
- `login_username`, or
- `display_name#tag` (only when both have a display name; a missing tag counts as empty).
