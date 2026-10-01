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

Length limits and character rules live in `core/validation.py` (control characters are
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

## When preset rules apply

Preset rules (tier, division, region) are checked when an account is **edited**, not when a
vault is **loaded**. Loading checks structure only (`core/serialization.py`), so a vault still
opens after a game renames a tier. The UI shows unknown values as-is.

## Presets (`config/constants.py`)

Each preset defines an ordered tier list, which tiers have divisions, the division range and
order, and a region list. Ladders are checked against current official sources when written
(Phase 1). The source and date are recorded in a comment next to each preset. The `custom`
preset has a generic tier list and regions.

The Marvel Rivals region list is an unverified best guess (pending user review).

## Duplicate rule

This is a non-blocking warning. Inside the same game, two accounts are duplicates if either of
these matches after trimming and case-folding:
- `login_username`, or
- `display_name#tag` (only when both have a display name; a missing tag counts as empty).
