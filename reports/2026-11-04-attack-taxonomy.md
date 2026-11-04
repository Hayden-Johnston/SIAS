# Attack taxonomy and schema v2 spec (ticket 0004)

## What changed

`docs/datasets.md` now specifies schema version 2 on top of version 1: `channel` (where the text
reaches the model: direct, multi_turn, document, email, tool_output, code_comment), `techniques` (a
list: override, roleplay, encoding, delimiter_spoof, payload_split, many_shot, named_jailbreak, novel),
and `spans` (`[turn, start, end]` attack locations, or null when unknown). It also specifies how long
contexts are chunked at scoring time to locate attacks, and deterministic family-based split assignment.

## Decisions and why

- Long context is a length bucket derived at report time, not a channel: a long email is both, and a
  single-valued field cannot hold both.
- Techniques are a list because real attacks combine them; `attack_family` stays the finer split unit.
- Multi-turn rows keep one `text` field (a JSON message array) so IDs, hashing and normalization are
  unchanged.
- Chunks are derived from text + spans by run config, never stored: replay stays deterministic and no
  extra storage is used (disks are 93-95% full per the 0003 survey).
- Public sources get `novel` and `null` spans unless the source states otherwise; no guessed labels.

## Effect

Documentation only; no code, data or model change. No detection, false-positive, latency or storage
effect yet. Follow-up Codex tickets: 0009 schema v2, 0010 split assignment, 0011 chunked scoring and
location metrics, 0012 source loaders (after 0005 approvals).
