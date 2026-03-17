# Feature: index-faces-full

## Goal

Add face detection, incremental clustering, and face-aware search to the indexing pipeline.

## Data Model

### `common/src/common/index.py` changes

`IndexStore` and `IndexResult` become `Generic[T]`. Two item types:
- `CaptionItem(text: str)` — vectorized internally by the store
- `FaceItem(embedding: list[float], cluster_id: str)` — stored directly as vector

`IndexResult.caption: str` is removed and replaced by `item: T`.

```
@dataclass class CaptionItem: text: str
@dataclass class FaceItem:    embedding: list[float]; cluster_id: str

class IndexResult(Generic[T]): id, relative_path, item: T, score, extra
class IndexStore(ABC, Generic[T]): search(query: T, top_k) → list[IndexResult[T]]; ...
```

### Indexer additions

- `indexer/models/insightface.py` — `InsightFaceModel` (concrete, no ABC)
  - `detect_batch(mfs: list[MediaFile]) → list[list[list[float]]]`
    (per-image list of face embedding vectors)
- `indexer/tests/stubs/insightface.py` — stub subclassing `InsightFaceModel`
- `indexer/face_cluster.py` — `FaceClusterer` (incremental centroid clustering)
  - `assign(face_vector, image_path) → cluster_id`
  - cosine similarity threshold; new cluster if no match
- `indexer/stores/chroma_face.py` — `ChromaFaceIndexStore(IndexStore[FaceItem])`
  - stores face cluster centroids; metadata includes `image_paths: "p1,p2,..."`
- `BatchItem` extended with `face_cluster_ids: list[str]`

### New pipeline: `blip2_sentok_exif_insightface_chroma.py`

Stages:
1. `_open` (unbatched)
2. `_caption` (batched)
3. `_faces` (batched) — `InsightFaceModel.detect_batch` → `face_vectors`
4. `_exif` (unbatched)
5. `_assign_clusters` (unbatched) — `FaceClusterer.assign()` → `face_cluster_ids`
6. `_format_text` (unbatched)
7. `_upsert_captions` (batched) — caption store; metadata includes `face_cluster_ids`
8. `_upsert_faces` (unbatched) — update face cluster metadata (`image_paths`) in face store
9. `_close` (unbatched)

### Store layout (base `store_uri`)

```
{store_uri}/
  captions/db/index_meta.json    ← written by both indexers
  faces/db/index_meta.json       ← written only by blip2-sentok-exif-insightface
```

### Search additions

`startup.py` keeps only common args: `--store-uri`, `--media-uri`, `--port`, `--top-k`.
A subcommand selects the indexer and determines which stores to load:

```bash
python -m search serve blip2-sentok-exif            --store-uri ... --media-uri ...
python -m search serve blip2-sentok-exif-insightface --store-uri ... --media-uri ...
```

`AppState.face_store: IndexStore[FaceItem] | None` — present only for the insightface subcommand.

Starting with the wrong store URI (missing `faces/db/`) → `RuntimeError`.

New routes:
- `GET /faces?top_k=N` → `list[IndexResult[FaceItem]]` sorted by cluster frequency
- `GET /search?q=text&face_ids=c1,c2&top_k=N` → `list[IndexResult[CaptionItem]]`, filtered

Face-image lookup: `face_store.get_metadata(cluster_id)` returns `{image_paths: "p1,p2,..."}`.
Search endpoint filters text results to `candidate_paths` derived from requested face clusters.

### Webapp additions

- `src/api/faces.ts` — typed `getFaces(topK)` API call
- `src/components/FaceRibbon.tsx` — horizontally scrollable face cluster thumbnails
- Search state extended: `selectedFaceIds: string[]`
- `GET /search` call passes `face_ids` param when faces are selected
- `IndexResult` type updated: `item` field replaces `caption`

## Task Breakdown

### Phase A — common
- A1: Update `index.py` — Generic `IndexStore[T]`, `IndexResult[T]`; add `CaptionItem`, `FaceItem`; remove `caption`
- A2: Update `__init__.py` exports
- A3: Add/update `tests/test_faces.py` (test new types and ABC contract)
- A4: Quality + test gates → `dev:` commit

### Phase B — indexer (depends on A)
- B1: Add `models/insightface.py` (`InsightFaceModel`)
- B2: Add `tests/stubs/insightface.py` (stub)
- B3: Add `face_cluster.py` (`FaceClusterer`)
- B4: Add `stores/chroma_face.py` (`ChromaFaceIndexStore`)
- B5: Update `stores/chroma_caption.py` generic signature
- B6: Extend `pipeline.py:BatchItem` with `face_cluster_ids`
- B7: Add `indexers/blip2_sentok_exif_insightface_chroma.py`
- B8: Update `cli.py` registry
- B9: Add tests for all new components
- B10: Quality + test gates → `dev:` commit

### Phase C — search (depends on A)
- C1: Update `startup.py` — subcommand dispatch, `_SERVE_REGISTRY`, multi-store loading
- C2: Update `config.py` — `indexer_key` field
- C3: Update `__main__.py` — subcommand-based CLI
- C4: Update `app.py` — `GET /faces`, `face_ids` in `GET /search`
- C5: Add/update tests
- C6: Quality + test gates → `dev:` commit

### Phase D — webapp (independent)
- D1: Add `src/api/faces.ts`
- D2: Add `src/components/FaceRibbon.tsx`
- D3: Update `IndexResult` type and search state
- D4: Quality + test gates → `dev:` commit

### Phase E — push
- E1: All gates green → push to `claude/add-index-faces-full-HIW5n`

## Status

- [ ] Plan approved
- [ ] Phase A complete
- [ ] Phase B complete
- [ ] Phase C complete
- [ ] Phase D complete
- [ ] Pushed
