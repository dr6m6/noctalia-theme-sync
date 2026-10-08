{
  description = "Safe Noctalia v5 theme synchronization";
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  outputs = { self, nixpkgs }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" ];
      each = nixpkgs.lib.genAttrs systems;
    in {
      packages = each (system:
        let pkgs = import nixpkgs { inherit system; };
        in { default = pkgs.callPackage ./nix/package.nix {}; });
      apps = each (system: { default = {
        type = "app";
        program = "${self.packages.${system}.default}/bin/noctalia-theme-sync";
        meta.description = "Noctalia theme sync CLI";
      }; });
      checks = each (system:
        let
          pkgs = import nixpkgs { inherit system; };
          evaluated = nixpkgs.lib.nixosSystem {
            inherit system;
            modules = [ self.nixosModules.default {
              system.stateVersion = "26.05";
              programs.noctalia-theme-sync.enable = true;
              programs.noctalia-theme-sync.bridge.enable = true;
            } ];
          };
        in {
          package = self.packages.${system}.default;
          module = assert builtins.elem self.packages.${system}.default evaluated.config.environment.systemPackages;
            assert evaluated.config.systemd.user.services.noctalia-theme-sync-bridge.serviceConfig.NoNewPrivileges;
            pkgs.runCommand "noctalia-theme-sync-module-check" {} "touch $out";
        });
      devShells = each (system:
        let pkgs = import nixpkgs { inherit system; };
        in { default = pkgs.mkShell {
          packages = [ (pkgs.python3.withPackages (p: [ p.setuptools p.jsonschema p.build ])) pkgs.ruff pkgs.gitleaks ];
          shellHook = "export PYTHONPATH=$PWD/src";
        }; });
      nixosModules.default = { config, lib, pkgs, ... }:
        import ./nix/module.nix {
          inherit config lib pkgs;
          defaultPackage = self.packages.${pkgs.stdenv.hostPlatform.system}.default;
        };
    };
}
