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
          common = pkgs.mkShell {
            name = "common";
            packages = [
              pkgs.python311
              pkgs.stdenv.cc.cc.lib  # libstdc++.so.6 for pip-installed native extensions
            ];
            shellHook = ''
              export LD_LIBRARY_PATH="${pkgs.stdenv.cc.cc.lib}/lib''${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
              FLAKE_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || echo "$PWD")"
              VENV="$FLAKE_ROOT/common/.venv"
              if [ ! -d "$VENV" ]; then
                python -m venv "$VENV"
              fi
              source "$VENV/bin/activate"
              python -m pip install --quiet -e "$FLAKE_ROOT/common[dev]"
              echo "common env ready (python 3.11)"
            '';
          };

          indexer = pkgs.mkShell {
            name = "indexer";
            packages = [
              pkgs.ffmpeg        # frame extraction + audio decode (ffprobe included)
              pkgs.rclone        # remote media / store support
              pkgs.python311
              pkgs.stdenv.cc.cc.lib  # libstdc++.so.6 for pip-installed native extensions (numpy, etc.)
              # Use python -m pip (from the venv) rather than pkgs pip to avoid
              # version mismatches between the nixpkgs pip and the venv python.
            ];
            shellHook = ''
              export LD_LIBRARY_PATH="${pkgs.stdenv.cc.cc.lib}/lib''${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
              # Anchor to the flake root regardless of the cwd from which
              # `nix develop` was invoked.
              FLAKE_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || echo "$PWD")"
              VENV="$FLAKE_ROOT/indexer/.venv"
              if [ ! -d "$VENV" ]; then
                python -m venv "$VENV"
              fi
              source "$VENV/bin/activate"
              python -m pip install --quiet -e "$FLAKE_ROOT/common"
              python -m pip install --quiet -e "$FLAKE_ROOT/indexer[dev]"
              echo "indexer env ready (ffmpeg, rclone, python 3.11)"
            '';
          };

          search = pkgs.mkShell {
            name = "search";
            packages = [
              pkgs.rclone        # remote store support
              pkgs.python311
              pkgs.stdenv.cc.cc.lib  # libstdc++.so.6 for pip-installed native extensions
            ];
            shellHook = ''
              export LD_LIBRARY_PATH="${pkgs.stdenv.cc.cc.lib}/lib''${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
              FLAKE_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || echo "$PWD")"
              VENV="$FLAKE_ROOT/search/.venv"
              if [ ! -d "$VENV" ]; then
                python -m venv "$VENV"
              fi
              source "$VENV/bin/activate"
              python -m pip install --quiet -e "$FLAKE_ROOT/common"
              python -m pip install --quiet -e "$FLAKE_ROOT/search[dev]"
              echo "search env ready (rclone, python 3.11)"
            '';
          };

          webapp = pkgs.mkShell {
            name = "webapp";
            packages = [
              pkgs.nodejs_20     # node + npm for the React/Vite frontend
            ];
            shellHook = ''
              FLAKE_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || echo "$PWD")"
              cd "$FLAKE_ROOT/webapp"
              npm install --prefer-offline --no-audit --no-fund
              echo "webapp env ready ($(node --version))"
            '';
          };

          # Minimal shell for running the e2e pytest suite.
          # The test itself only needs Python + pytest; the services it starts
          # (index.sh, search.sh, webapp.sh) each pull in their own nix shells.
          e2e = pkgs.mkShell {
            name = "e2e";
            packages = [
              pkgs.python311
              pkgs.stdenv.cc.cc.lib
            ];
            shellHook = ''
              export LD_LIBRARY_PATH="${pkgs.stdenv.cc.cc.lib}/lib''${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
              FLAKE_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || echo "$PWD")"
              VENV="$FLAKE_ROOT/.e2e-venv"
              if [ ! -d "$VENV" ]; then
                python -m venv "$VENV"
              fi
              source "$VENV/bin/activate"
              python -m pip install --quiet pytest
              echo "e2e test env ready (python 3.11)"
            '';
          };
        }
      );
    };
}
