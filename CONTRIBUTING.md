# Contributing Skills

This registry is curated. Pull requests are manually reviewed, with a target review window of
24-48 hours when maintainers are available.

## Request a Skill

Open an issue with the skill name, source repository or URL, and the target agents you want to
use it with:

https://github.com/kevinpita/nix-skills/issues/new

## Add a Skill

Open a pull request with a registry entry and regenerated artifacts. Use the helper from the
repository root:

```sh
nix run .#nix-skills -- add https://github.com/owner/repo/tree/main/path/to/skill
nix run .#nix-skills -- generate
nix run .#nix-skills -- check --fetch
```

Every registry entry must:

- point at a GitHub source pinned to a full 40-character commit SHA
- include the Nix `narHash` for the fetched repository
- select a folder containing `SKILL.md`
- declare display name, description, license, author, and compatible targets
- declare dependencies when the skill expects other skills to be installed

The first supported target kinds are `agents` and `claude`. Custom Home Manager targets can
declare their own kind. Use `*` for target-agnostic skills, and list specific target kinds only
when compatibility has been reviewed.

## Update a Skill

```sh
nix run .#nix-skills -- update grill-with-docs
nix run .#nix-skills -- update --all
nix run .#nix-skills -- check --fetch
```

The updater resolves the upstream default branch to an immutable commit, refreshes the hash, and
regenerates committed artifacts.

## Review Policy

CI validates structure, dependency consistency, generated file drift, and source reproducibility.
Maintainers still manually inspect submitted skill content before merge.
