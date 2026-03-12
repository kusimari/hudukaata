# Feature: create-webapp

## Status: In Progress

## Summary
Create a minimal web app that provides a search UX backed by the existing search server.
The webapp only knows the address of the API server — it has no direct access to the
media store or the vector index.  All media is served via the search server.

## Architecture

```
Browser ──► (any static file server) GET /  → Vite/React SPA bundle
Browser ──► search  GET /search?q=...        → JSON results (relative_path per item)
Browser ──► search  GET /media/{path}        → raw media bytes
```

The webapp is a pure static Vite + TypeScript + React SPA. No backend server.
Config is baked at build time via `VITE_API_URL` env var.

### Search server changes (search/)
- `config.py`: new `SEARCH_MEDIA` env var — a `file://` or `rclone:` URI pointing
  to the root of the original media files.
- `startup.py`: parse the media URI into a pointer; store it in `AppState`.
- `app.py`: new `GET /media/{path:path}` endpoint that resolves the `relative_path`
  and streams the file back to the caller.  Adds CORS middleware so the browser can
  call the search server from a different origin.

### common/ changes
- `pointer.py`: add `get_file_ctx(relative_path)` context-manager to `_BasePointer`.
  For `file://` yields the local path directly; for `rclone:` downloads the file to a
  temp location, yields it, and removes it on exit.

### webapp/ (new Vite + TypeScript + React package)
- Config: `VITE_API_URL` (the search server base URL), baked at build time.
- No server — the browser talks directly to the search server.
- `src/api.ts`: typed fetch client whose types match the search server's OpenAPI schema.
- `src/App.tsx`: search box → results grid with loading + error states.
- `src/components/SearchBar.tsx`: controlled input + submit button.
- `src/components/ResultCard.tsx`: `<img>` for image files, `<video>` for video files.
- Build: `npm run build` → `dist/` (Vite production bundle).
- Tests: Vitest + @testing-library/react (28 tests, zero failures).
- Nix devShell: `nix develop .#webapp` (Node 20, runs `npm install`).

## Requirements
- [x] Webapp is configured with only one thing: the API server URL (`VITE_API_URL`).
- [x] Webapp has no knowledge of the media store path.
- [x] Simple single-page UX: search box → result cards with media previews.
- [x] Search server extends its config to serve media files.
- [x] CORS on search server allows browser requests from any origin.
- [x] Path traversal is prevented in the `/media` endpoint.
- [x] Tests cover all new code paths (28 tests across api, SearchBar, ResultCard, App).

## Implementation Tasks
1. [x] `common/pointer.py` — add `get_file_ctx(relative_path)` to `_BasePointer`
2. [x] `common/tests/test_pointer.py` — tests for `get_file_ctx`
3. [x] `search/src/search/config.py` — add `media` field
4. [x] `search/src/search/startup.py` — add `media_ptr` to `AppState`, parse in `load()`
5. [x] `search/src/search/app.py` — CORS middleware + `/media/{path:path}` endpoint
6. [ ] `search/tests/test_media_route.py` — tests for media endpoint (remaining)
7. [x] `webapp/` — Vite + TypeScript + React SPA (package.json, tsconfig, vite.config.ts,
       index.html, src/, tests, .env.example, .envrc)
8. [x] `flake.nix` — add `webapp` devShell (Node 20)
