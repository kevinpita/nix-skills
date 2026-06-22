{
  description = "A curated Nix registry and Home Manager module for declarative agent skills.";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  };

  outputs =
    { self, nixpkgs }:
    let
      lib = nixpkgs.lib;
      systems = [
        "x86_64-linux"
        "aarch64-linux"
        "x86_64-darwin"
        "aarch64-darwin"
      ];
      forAllSystems = f: lib.genAttrs systems (system: f system);
      registry = import ./generated/registry.nix;

      mkSkillPackages =
        pkgs:
        import ./lib/build.nix {
          inherit lib pkgs registry;
        };

      mkHelper =
        pkgs:
        pkgs.writeShellApplication {
          name = "nix-skills";
          runtimeInputs = [
            pkgs.git
            pkgs.nix
            pkgs.python3
          ];
          text = ''
            exec ${pkgs.python3}/bin/python3 ${./tools/nix_skills.py} "$@"
          '';
        };
    in
    {
      lib = {
        registry = registry;
        inherit mkSkillPackages;
      };

      skills = forAllSystems (system: mkSkillPackages nixpkgs.legacyPackages.${system});

      packages = forAllSystems (
        system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
          skillPackages = mkSkillPackages pkgs;
          helper = mkHelper pkgs;
        in
        skillPackages
        // {
          nix-skills = helper;
          default = helper;
        }
      );

      apps = forAllSystems (
        system:
        let
          app = {
            type = "app";
            program = "${self.packages.${system}.nix-skills}/bin/nix-skills";
            meta.description = "Manage the Nix Skills registry";
          };
        in
        {
          nix-skills = app;
          default = app;
        }
      );

      overlays.default = final: _prev: {
        nixSkills = mkSkillPackages final;
        nix-skills = mkHelper final;
      };

      homeManagerModules.default = import ./modules/home-manager.nix {
        inherit registry;
      };

      checks = forAllSystems (
        system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
          skillPackages = mkSkillPackages pkgs;
          helper = self.packages.${system}.nix-skills;
          moduleHarness = modules:
            lib.evalModules {
              specialArgs = { inherit pkgs; };
              modules = [
                (
                  { lib, ... }:
                  {
                    options.home.file = lib.mkOption {
                      type = lib.types.attrsOf lib.types.anything;
                      default = { };
                    };

                    options.assertions = lib.mkOption {
                      type = lib.types.listOf lib.types.attrs;
                      default = [ ];
                    };
                  }
                )
                self.homeManagerModules.default
              ] ++ modules;
            };
          moduleDependencyFiles =
            builtins.attrNames
              (moduleHarness [
                ({ ... }: {
                  config.programs.nix-skills.targets.agents.skills = [ "grill-with-docs" ];
                })
              ]).config.home.file;
          moduleIncompatibleAssertions =
            (moduleHarness [
              ({ ... }: {
                config.programs.nix-skills.extraSkills.only-agents = {
                  path = skillPackages.domain-modeling;
                  compatibleTargets = [ "agents" ];
                };

                config.programs.nix-skills.targets.custom = {
                  baseDir = ".custom";
                  skillsDir = "skills";
                  kind = "unsupported";
                  skills = [ "only-agents" ];
                };
              })
            ]).config.assertions;
          moduleHasIncompatibleFailure =
            lib.any (assertion: assertion.assertion == false) moduleIncompatibleAssertions;
        in
        skillPackages
        // {
          python-tests = pkgs.runCommand "nix-skills-python-tests" { nativeBuildInputs = [ pkgs.python3 ]; } ''
            cd ${self}
            python3 -m unittest discover -s tests
            touch "$out"
          '';

          registry = pkgs.runCommand "nix-skills-registry-check" { nativeBuildInputs = [ helper ]; } ''
            nix-skills --repo ${self} check
            touch "$out"
          '';

          module-dependencies =
            pkgs.runCommand "nix-skills-module-dependencies"
              {
                expected = ".agents/skills/domain-modeling .agents/skills/grill-with-docs .agents/skills/grilling";
                actual = lib.concatStringsSep " " moduleDependencyFiles;
              }
              ''
                test "$actual" = "$expected"
                touch "$out"
              '';

          module-compatibility =
            pkgs.runCommand "nix-skills-module-compatibility"
              {
                hasFailure = if moduleHasIncompatibleFailure then "yes" else "no";
              }
              ''
                test "$hasFailure" = "yes"
                touch "$out"
              '';
        }
      );
    };
}
