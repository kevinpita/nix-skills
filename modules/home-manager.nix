{ registry }:

{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.programs.nix-skills;
  skillPackages = import ../lib/build.nix {
    inherit lib pkgs registry;
  };

  targetType = lib.types.submodule (
    { name, ... }:
    {
      options = {
        baseDir = lib.mkOption {
          type = lib.types.str;
          default = name;
          description = "Directory under the user's home where this target stores agent data.";
        };

        skillsDir = lib.mkOption {
          type = lib.types.str;
          default = "skills";
          description = "Directory below baseDir where skill folders are linked.";
        };

        kind = lib.mkOption {
          type = lib.types.str;
          default = name;
          description = "Compatibility kind used to check registry metadata.";
        };

        skills = lib.mkOption {
          type = lib.types.listOf lib.types.str;
          default = [ ];
          description = "Registry or extra skill slugs to install into this target.";
        };

        allowIncompatible = lib.mkOption {
          type = lib.types.bool;
          default = false;
          description = "Allow installing skills whose compatibleTargets do not include this target kind.";
        };
      };
    }
  );

  extraSkillType = lib.types.submodule (
    { ... }:
    {
      options = {
        path = lib.mkOption {
          type = lib.types.either lib.types.path lib.types.package;
          description = "Path or derivation containing the skill folder, including SKILL.md.";
        };

        description = lib.mkOption {
          type = lib.types.str;
          default = "";
          description = "Short description for this extra skill.";
        };

        license = lib.mkOption {
          type = lib.types.str;
          default = "unknown";
          description = "License identifier for this extra skill.";
        };

        author = lib.mkOption {
          type = lib.types.str;
          default = "local";
          description = "Author or maintainer for this extra skill.";
        };

        compatibleTargets = lib.mkOption {
          type = lib.types.listOf lib.types.str;
          default = [ ];
          description = "Target kinds this extra skill is compatible with.";
        };

        dependencies = lib.mkOption {
          type = lib.types.listOf lib.types.str;
          default = [ ];
          description = "Other registry or extra skill slugs required by this skill.";
        };
      };
    }
  );

  registryRecords =
    lib.mapAttrs
      (slug: entry:
        entry
        // {
          inherit slug;
          path = skillPackages.${slug};
          dependencies = entry.dependencies or [ ];
          compatibleTargets = entry.compatibleTargets or [ ];
        })
      registry;

  extraRecords =
    lib.mapAttrs
      (slug: entry:
        entry
        // {
          inherit slug;
          dependencies = entry.dependencies or [ ];
          compatibleTargets = entry.compatibleTargets or [ ];
        })
      cfg.extraSkills;

  duplicateExtraSlugs = lib.intersectLists (lib.attrNames registryRecords) (lib.attrNames extraRecords);
  allSkills = registryRecords // extraRecords;

  resolveSkill =
    stack: slug:
    if lib.elem slug stack then
      throw "nix-skills dependency cycle: ${lib.concatStringsSep " -> " (stack ++ [ slug ])}"
    else if !(lib.hasAttr slug allSkills) then
      throw "nix-skills unknown skill slug: ${slug}"
    else
      let
        skill = allSkills.${slug};
      in
      [ slug ] ++ lib.concatMap (resolveSkill (stack ++ [ slug ])) (skill.dependencies or [ ]);

  closureFor = slugs: lib.unique (lib.concatMap (resolveSkill [ ]) slugs);

  activeTargets = lib.filterAttrs (_: target: target.skills != [ ]) cfg.targets;

  targetFiles =
    targetName: target:
    let
      closure = closureFor target.skills;
    in
    map (slug: {
      name = "${target.baseDir}/${target.skillsDir}/${slug}";
      value = {
        source = allSkills.${slug}.path;
        recursive = true;
      };
    }) closure;

  incompatibleFor =
    target:
    let
      closure = closureFor target.skills;
      isCompatible =
        slug:
        let
          compatibleTargets = allSkills.${slug}.compatibleTargets or [ ];
        in
        target.allowIncompatible
        || lib.elem target.kind compatibleTargets
        || lib.elem "*" compatibleTargets;
    in
    lib.filter (slug: !(isCompatible slug)) closure;
in
{
  options.programs.nix-skills = {
    targets = lib.mkOption {
      type = lib.types.attrsOf targetType;
      default = { };
      description = "Skill installation targets keyed by target name.";
    };

    extraSkills = lib.mkOption {
      type = lib.types.attrsOf extraSkillType;
      default = { };
      description = "Extra local or packaged skills addressable by slug.";
    };
  };

  config = {
    programs.nix-skills.targets = {
      agents = {
        baseDir = lib.mkDefault ".agents";
        skillsDir = lib.mkDefault "skills";
        kind = lib.mkDefault "agents";
      };

      claude = {
        baseDir = lib.mkDefault ".claude";
        skillsDir = lib.mkDefault "skills";
        kind = lib.mkDefault "claude";
      };
    };

    assertions =
      [
        {
          assertion = duplicateExtraSlugs == [ ];
          message = "programs.nix-skills.extraSkills cannot redefine registry slugs: ${lib.concatStringsSep ", " duplicateExtraSlugs}";
        }
      ]
      ++ lib.mapAttrsToList
        (targetName: target: {
          assertion = incompatibleFor target == [ ];
          message = "programs.nix-skills target '${targetName}' has incompatible skills for kind '${target.kind}': ${lib.concatStringsSep ", " (incompatibleFor target)}";
        })
        activeTargets;

    home.file = builtins.listToAttrs (lib.concatLists (lib.mapAttrsToList targetFiles activeTargets));
  };
}
