# hudukaata end-to-end test

`run.sh` is a self-contained integration test that exercises the full pipeline
from raw media files to search results returned through the webapp.

## What it tests

```
sample images
    │
    ▼
indexer          (nix devShell — downloads caption + vectorizer models on first run)
    │  writes ChromaDB store to a temp dir
    ▼
search API       (background process, port 18080)
    │  loads the index, exposes /search /media /readyz
    ▼
webapp           (background process, port 15173)
    │  Vite dev server configured with VITE_API_URL pointing at the search API
    │  /api/* proxied → search API (strips /api prefix)
    ▼
assertions
  1. GET /              → response body contains <html  (webapp is up and serving)
  2. GET /api/search    → goes through the Vite proxy to the search API;
                          verifies ≥ 1 result is returned for the query "blue sky"
```

The proxy approach (step 2) is deliberate: rather than calling the search API
directly, the test hits the webapp's `/api` route.  This verifies that the
webapp process is running *and* is correctly wired to the search API — a direct
API call would not catch a misconfigured `VITE_API_URL`.

## Why the search returns both sample images

The vector store returns the top-N most similar items with **no minimum
relevance threshold**.  With only two images in the test index and `n=5`
requested, both images are returned — the green-field image is the *least*
similar match to "blue sky" but still appears because there is nothing else to
fill the result set.  The assertion intentionally checks only that *at least
one* result is returned, which is sufficient for an existence/wiring test.

## Running locally

```
./runner-scripts/e2e-test/run.sh
```

Requires: `nix` with flakes enabled.  Models are cached after the first run.
