# Nix Skills

Nix Skills is a curated, flake-first registry for installing agent skills declaratively.
It exposes skills as package-like Nix outputs and includes a Home Manager module for linking
skills into user-owned agent folders.

## Usage

Add this flake as an input:

```nix
{
  inputs.nix-skills = {
    url = "github:kevinpita/nix-skills";
    inputs.nixpkgs.follows = "nixpkgs";
  };
}
```

If Home Manager is managed from NixOS, import the module inside the user config:

```nix
{
  inputs,
  username,
  ...
}:
let
  commonSkills = [
    "domain-modeling"
  ];
in
{
  home-manager.users.${username} = {
    imports = [
      inputs.nix-skills.homeManagerModules.default
    ];

    programs.nix-skills.targets = {
      agents.skills = commonSkills ++ [
        # Also fetches and installs dependencies: domain-modeling and grilling.
        "grill-with-docs"
      ];

      claude.skills = commonSkills ++ [
        "grilling"
      ];
    };
  };
}
```

For standalone Home Manager, import the same module from `homeConfigurations.<name>`:

```nix
{
  outputs = { nix-skills, home-manager, ... }: {
    homeConfigurations.kevin = home-manager.lib.homeManagerConfiguration {
      modules = [
        nix-skills.homeManagerModules.default
        {
          programs.nix-skills.targets = {
            agents.skills = [
              # Also fetches and installs dependencies: domain-modeling and grilling.
              "grill-with-docs"
            ];
            claude.skills = [ "domain-modeling" ];
          };
        }
      ];
    };
  };
}
```

Built-in targets install to:

| Target | Destination |
| --- | --- |
| `agents` | `~/.agents/skills/<slug>` |
| `claude` | `~/.claude/skills/<slug>` |

Targets become active when their `skills` list is nonempty. Dependencies are installed into
the same target automatically.

Custom targets use the same shape:

```nix
programs.nix-skills.targets.my-agent = {
  baseDir = ".my-agent";
  skillsDir = "skills";
  kind = "agents";
  skills = [ "grill-with-docs" ];
};
```

For local or private skills, add `extraSkills` and reference them by slug:

```nix
programs.nix-skills.extraSkills.my-local-skill = {
  path = ./skills/my-local-skill;
  description = "A private local skill.";
  license = "private";
  author = "Me";
  compatibleTargets = [ "*" ];
};

programs.nix-skills.targets.agents.skills = [ "my-local-skill" ];
```

Use `compatibleTargets = [ "*" ];` for target-agnostic skills. List specific target kinds
only when a skill has reviewed target-specific compatibility.

## Package Outputs

Skills are also exposed as packages:

```sh
nix build .#domain-modeling
nix build .#grill-with-docs
```

The overlay exposes them as `pkgs.nixSkills."<slug>"`.

## Helper

The helper manages registry entries and generated files:

```sh
nix run .#nix-skills -- check
nix run .#nix-skills -- generate
nix run .#nix-skills -- add https://github.com/owner/repo/tree/main/path/to/skill
nix run .#nix-skills -- update grill-with-docs
nix run .#nix-skills -- update --all
```

Use `check --fetch` when network access is available and you want to verify upstream hashes and
`SKILL.md` paths.

## Catalog

See [CATALOG.md](./CATALOG.md) for the current registry.

## Request a Skill

To request a new skill, open an issue:

https://github.com/kevinpita/nix-skills/issues/new

Include the skill name, source repository or URL, and the target agents you want to use it with.

## Open a PR

To add a skill yourself, open a pull request that includes the registry entry and generated files:

```sh
nix run .#nix-skills -- add https://github.com/owner/repo/tree/main/path/to/skill
nix run .#nix-skills -- generate
nix run .#nix-skills -- check --fetch
```

See [CONTRIBUTING.md](./CONTRIBUTING.md) for registry requirements and review policy.

## Development

```sh
nix flake check
nix run .#nix-skills -- check
```
