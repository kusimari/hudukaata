{
  description = "hudukaata monorepo dev environments";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }:
    let
      supportedSystems = [ "x86_64-linux" "aarch64-linux" "x86_64-darwin" "aarch64-darwin" ];
      forAllSystems = nixpkgs.lib.genAttrs supportedSystems;
    in {
      devShells = forAllSystems (system:
        let pkgs = nixpkgs.legacyPackages.${system};
        in {
          indexer = pkgs.mkShell {
            name = "indexer";
            packages = [
              pkgs.ffmpeg        # frame extraction + audio decode (ffprobe included)
              pkgs.rclone        # remote media / store support
              pkgs.python311
              # Use python -m pip (from the venv) rather than pkgs pip to avoid
              # version mismatches between the nixpkgs pip and the venv python.
            ];
            shellHook = ''
              # Anchor to the flake root regardless of the cwd from which
              # `nix develop` was invoked.
              FLAKE_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || echo "$PWD")"
              VENV="$FLAKE_ROOT/indexer/.venv"
              if [ ! -d "$VENV" ]; then
                python -m venv "$VENV"
              fi
              source "$VENV/bin/activate"
              python -m pip install --quiet -e "$FLAKE_ROOT/indexer[dev]"
              echo "indexer env ready (ffmpeg, rclone, python 3.11)"
            '';
          };
        }
      );
    };
}
