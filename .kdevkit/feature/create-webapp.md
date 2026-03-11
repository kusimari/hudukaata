# Feature: create-webapp

## Status: In Progress

## Summary
Create a minimal web app that provides a search UX backed by the existing search server.
The webapp only knows the address of the API server — it has no direct access to the
media store or the vector index.  All media is served via the search server.

## Architecture

```
Browser ──► webapp GET /          → HTML page (with API_URL embedded)
Browser ──► search  GET /search?q=...   → JSON results (relative_path per item)
Browser ──► search  GET /media/{path}   → raw media bytes
```

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

### webapp/ (new package)
- Config: `WEBAPP_API_URL` (the search server base URL) + `WEBAPP_PORT` (default 8888).
- App: one route `GET /` that returns the HTML page with the API URL injected as a
  JS constant.  No proxy logic — the browser talks directly to the search server.
- Frontend (embedded in the Python source):
  - Search input + button.
  - On submit: fetches `{API_URL}/search?q=…`, renders result cards.
  - Each card loads its media from `{API_URL}/media/{relative_path}`.
  - Uses `<img>` for image files, `<video>` for video files.

## Requirements
- [ ] Webapp is configured with only one thing: the API server URL.
- [ ] Webapp has no knowledge of the media store path.
- [ ] Simple single-page UX: search box → result cards with media previews.
- [ ] Search server extends its config to serve media files.
- [ ] CORS on search server allows browser requests from any origin.
- [ ] Path traversal is prevented in the `/media` endpoint.
- [ ] Tests cover all new code paths.

## Implementation Tasks
1. `common/pointer.py` — add `get_file_ctx(relative_path)` to `_BasePointer`
2. `common/tests/test_pointer.py` — tests for `get_file_ctx`
3. `search/src/search/config.py` — add `media` field
4. `search/src/search/startup.py` — add `media_ptr` to `AppState`, parse in `load()`
5. `search/src/search/app.py` — CORS middleware + `/media/{path:path}` endpoint
6. `search/tests/test_media_route.py` — tests for media endpoint
7. `webapp/` — new package (pyproject.toml, config, app, __main__, tests, .envrc)
8. `flake.nix` — add `webapp` devShell
