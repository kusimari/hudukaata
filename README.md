# hudukaata

A monorepo that indexes media (images, video, audio) into a vector database for semantic search, then streams results to a browser app. Point it at a folder of photos and videos, run the indexer, and search your collection with natural language queries from any browser.

> Full project description: [.kdevkit/project.md](.kdevkit/project.md)

## How it works

| Package | Role |
|---------|------|
| `common` | Shared vectorizers and vector store abstractions |
| `indexer` | Scans media, generates captions (BLIP-2), vectorizes, writes to ChromaDB |
| `search` | FastAPI server — semantic search endpoint + media streaming |
| `webapp` | React SPA — search bar, result cards, media preview |

---

## Running locally

### 1 — Install Nix

Nix manages all dependencies (Python, Node.js, ffmpeg, rclone, model weights, libraries). No manual installs needed beyond Nix itself.

```bash
# Works on macOS, Linux, and WSL2. Flakes are enabled automatically.
curl --proto '=https' --tlsv1.2 -sSf -L https://install.determinate.systems/nix | sh -s -- install
```

Restart your shell (or open a new terminal) after the installer finishes.

### 2 — Clone the repo

```bash
git clone https://github.com/kusimari/hudukaata.git
cd hudukaata
```

### 3 — Configure

```bash
cp runner-scripts/hudukaata.conf.example runner-scripts/hudukaata.conf
```

Edit `runner-scripts/hudukaata.conf` and set at minimum:

```ini
media = file:///absolute/path/to/your/media
store = file:///absolute/path/to/your/store
```

`store` is where the index is saved — it can be any empty directory.

### 4 — Index your media

The first run downloads the BLIP-2 caption model (~4 GB). Subsequent runs skip files that haven't changed.

```bash
./runner-scripts/index.sh
```

### 5 — Start the search API

```bash
./runner-scripts/search.sh
```

### 6 — Start the webapp (second terminal)

```bash
./runner-scripts/webapp.sh
```

Open **http://localhost:5173** in your browser and start searching.

---

## Configuration reference

All settings live in `runner-scripts/hudukaata.conf` (git-ignored).

| Key | Default | Description |
|-----|---------|-------------|
| `media` | **required** | Media root URI (`file:///path` or `rclone:remote:///path`) |
| `store` | **required** | Vector index URI (`file:///path` or `rclone:remote:///path`) |
| `caption_model` | `blip2` | Caption model used at index time |
| `vectorizer` | `sentence-transformer` | Text embedding model |
| `vector_store` | `chroma` | Vector database backend |
| `log_level` | `INFO` | Logging verbosity (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `search_port` | `8080` | Port for the search API |
| `search_api_host` | `http://localhost` | Host the browser uses to reach the API |
| `webapp_port` | `5173` | Port for the webapp |

Each script also accepts a path to an alternative config file as its first argument:

```bash
./runner-scripts/index.sh /path/to/other.conf
```

---

## Running on separate machines

Each script is independent. A common setup:

- **Indexer machine** (GPU recommended): run `index.sh`, point `store` at shared storage (e.g. `rclone:s3:///my-bucket/store`)
- **Serving machine**: run `search.sh` and `webapp.sh` with the same `store` URI

---

## End-to-end test

`runner-scripts/e2e-test/run.sh` spins up all three services against a small set of sample images and verifies that indexing, search, and the webapp all work together:

```bash
./runner-scripts/e2e-test/run.sh
```

The first run downloads the BLIP-2 model (~4 GB). Subsequent runs reuse the nix cache and are faster.

---

## Development

See [.kdevkit/agent-dev-instructions.md](.kdevkit/agent-dev-instructions.md) for the per-package dev loop (setup → quality → test → push).

---

## Project todos

- [ ] **Mobile app (React Native)** — reuse the webapp API client and search UX for iOS and Android
- [ ] **LG WebOS app** — package the webapp as a WebOS IPK for smart TVs
- [ ] **Thumbnails** — generate thumbnails at index time and return thumbnail URLs in search results for faster rendering
- [ ] **Full-screen play mode** — view search results one by one sequentially (slideshow / media player) in the webapp
- [ ] **LLM-powered search** — add an LLM layer on top of the vector RAG for conversational and reasoning-based queries
