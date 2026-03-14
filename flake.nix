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
              pkgs.uv                    # fast pip/venv replacement (10-100x over pip)
              pkgs.stdenv.cc.cc.lib  # libstdc++.so.6 for pip-installed native extensions
            ];
            shellHook = ''
              export LD_LIBRARY_PATH="${pkgs.stdenv.cc.cc.lib}/lib''${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
              FLAKE_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || echo "$PWD")"
              VENV="$FLAKE_ROOT/common/.venv"
              if [ ! -d "$VENV" ]; then
                uv venv --python python3.11 --quiet "$VENV"
              fi
              source "$VENV/bin/activate"
              # Stamp-file guard: only re-install when pyproject.toml actually changed.
              _STAMP="$VENV/.pip-stamp"
              _HASH="$(sha256sum "$FLAKE_ROOT/common/pyproject.toml" | cut -d' ' -f1)"
              if [ ! -f "$_STAMP" ] || [ "$(cat "$_STAMP" 2>/dev/null)" != "$_HASH" ]; then
                uv pip install --quiet -e "$FLAKE_ROOT/common[dev]"
                echo "$_HASH" > "$_STAMP"
              fi
              echo "common env ready (python 3.11)"
            '';
          };

          indexer = pkgs.mkShell {
            name = "indexer";
            packages = [
              pkgs.ffmpeg        # frame extraction + audio decode (ffprobe included)
              pkgs.rclone        # remote media / store support
              pkgs.python311
              pkgs.uv
              pkgs.stdenv.cc.cc.lib  # libstdc++.so.6 for pip-installed native extensions (numpy, etc.)
            ];
            shellHook = ''
              export LD_LIBRARY_PATH="${pkgs.stdenv.cc.cc.lib}/lib''${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
              FLAKE_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || echo "$PWD")"
              VENV="$FLAKE_ROOT/indexer/.venv"
              if [ ! -d "$VENV" ]; then
                uv venv --python python3.11 --quiet "$VENV"
              fi
              source "$VENV/bin/activate"
              # Stamp covers both common and indexer so a change to either triggers reinstall.
              _STAMP="$VENV/.pip-stamp"
              _HASH="$(cat "$FLAKE_ROOT/common/pyproject.toml" "$FLAKE_ROOT/indexer/pyproject.toml" | sha256sum | cut -d' ' -f1)"
              if [ ! -f "$_STAMP" ] || [ "$(cat "$_STAMP" 2>/dev/null)" != "$_HASH" ]; then
                uv pip install --quiet -e "$FLAKE_ROOT/common"
                uv pip install --quiet -e "$FLAKE_ROOT/indexer[dev]"
                echo "$_HASH" > "$_STAMP"
              fi
              # Model weight cache dirs — keeps downloaded weights in a stable, shared
              # location across shell activations.  Set these before running the indexer
              # or tests so models are only downloaded once per machine/runner.
              export HF_HOME="''${HF_HOME:-$HOME/.cache/huggingface}"
              export WHISPER_MODEL_DIR="''${WHISPER_MODEL_DIR:-$HOME/.cache/whisper}"
              echo "indexer env ready (ffmpeg, rclone, python 3.11)"
            '';
          };

          search = pkgs.mkShell {
            name = "search";
            packages = [
              pkgs.rclone        # remote store support
              pkgs.python311
              pkgs.uv
              pkgs.stdenv.cc.cc.lib  # libstdc++.so.6 for pip-installed native extensions
            ];
            shellHook = ''
              export LD_LIBRARY_PATH="${pkgs.stdenv.cc.cc.lib}/lib''${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
              FLAKE_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || echo "$PWD")"
              VENV="$FLAKE_ROOT/search/.venv"
              if [ ! -d "$VENV" ]; then
                uv venv --python python3.11 --quiet "$VENV"
              fi
              source "$VENV/bin/activate"
              _STAMP="$VENV/.pip-stamp"
              _HASH="$(cat "$FLAKE_ROOT/common/pyproject.toml" "$FLAKE_ROOT/search/pyproject.toml" | sha256sum | cut -d' ' -f1)"
              if [ ! -f "$_STAMP" ] || [ "$(cat "$_STAMP" 2>/dev/null)" != "$_HASH" ]; then
                uv pip install --quiet -e "$FLAKE_ROOT/common"
                uv pip install --quiet -e "$FLAKE_ROOT/search[dev]"
                echo "$_HASH" > "$_STAMP"
              fi
              # sentence-transformers >= 3.0 respects HF_HOME for its model cache.
              export HF_HOME="''${HF_HOME:-$HOME/.cache/huggingface}"
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
              pkgs.uv
              pkgs.stdenv.cc.cc.lib
            ];
            shellHook = ''
              export LD_LIBRARY_PATH="${pkgs.stdenv.cc.cc.lib}/lib''${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
              FLAKE_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || echo "$PWD")"
              VENV="$FLAKE_ROOT/.e2e-venv"
              if [ ! -d "$VENV" ]; then
                uv venv --python python3.11 --quiet "$VENV"
              fi
              source "$VENV/bin/activate"
              _STAMP="$VENV/.pip-stamp"
              _HASH="e2e:pytest:httpx"
              if [ ! -f "$_STAMP" ] || [ "$(cat "$_STAMP" 2>/dev/null)" != "$_HASH" ]; then
                uv pip install --quiet pytest httpx
                echo "$_HASH" > "$_STAMP"
              fi
              echo "e2e test env ready (python 3.11)"
            '';
          };
        }
      );
    };
}
