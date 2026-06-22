{
  lib,
  pkgs,
  registry,
}:

let
  mkSkillPackage =
    slug: entry:
    let
      source = entry.source;
      src = pkgs.fetchFromGitHub {
        owner = source.owner;
        repo = source.repo;
        rev = source.rev;
        hash = source.narHash;
      };
    in
    pkgs.runCommand "nix-skill-${slug}"
      {
        meta = {
          description = entry.description or "";
          license = entry.license or "unknown";
          homepage = entry.homepage or "https://github.com/${source.owner}/${source.repo}";
          maintainers = [ ];
        };
      }
      ''
        mkdir -p "$out"
        if [ ! -d "${src}/${source.path}" ]; then
          echo "Skill path not found: ${source.path}" >&2
          exit 1
        fi
        cp -R "${src}/${source.path}/." "$out/"
        if [ ! -f "$out/SKILL.md" ]; then
          echo "Skill ${slug} does not contain SKILL.md" >&2
          exit 1
        fi
      '';
in
lib.mapAttrs mkSkillPackage registry
