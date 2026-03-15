# Feature: constrained-hw — Adaptive Batch Indexing

## Status: in-progress

## Problem

The indexer processes media files one at a time, which underutilises GPU throughput and is
impractical on machines with limited VRAM/RAM. On constrained hardware:
- BLIP-2 inference is slow because each image triggers a full forward pass.
- A crash or kill loses all unwritten work (checkpoint interval defaults to 100 files).
- There is no way to tune throughput to the machine's capacity.

## Requirements

1. **Batch processing**: Accumulate N media files, then caption/vectorize/upsert them together.
2. **Adaptive batch sizing**: Start at batch_size=1. After each batch measure time-per-item.
   Grow the batch if the machine can handle more; shrink on OOM or if it's too slow.
3. **Frequent checkpoints**: Default to writing a checkpoint after every batch (not every 100 files).
4. **True GPU batching for images**: Feed multiple PIL images in one BLIP-2 forward pass.
5. **No new heavy deps**: Use `psutil` for RAM monitoring; skip `accelerate`.

## Success criteria

- `indexer index --initial-batch-size 1 --max-batch-size 32 --adaptive-batch` works end-to-end.
- Batch of N images produces the same index as N single-image runs.
- A checkpoint file appears after each batch when `--checkpoint-interval 0`.
- All existing tests continue to pass.
- ruff + mypy strict pass.

## Design

### AdaptiveBatchController (`indexer/src/indexer/batch.py`)
- Tracks `current_size` (starts at `initial_size`, bounded by `max_size`).
- `record_batch(n_items, elapsed_secs)`: compute secs/item, double if < 80% of target, halve if > 150%.
- Also halves if `psutil.virtual_memory().available < memory_headroom_mb * 1024**2`.
- `on_oom()`: halve immediately.

### CaptionModel base extension (`models/base.py`)
- Add non-abstract `caption_batch(mfs) -> list[str]` defaulting to per-item `caption()`.

### Blip2CaptionModel override (`models/blip2.py`)
- Partition batch by media_type.
- Images: single BLIP-2 forward pass with padded batch.
- Video/audio: fall back to single `caption()`.

### Runner refactor (`runner.py`)
- Accumulate `pending: list[MediaFile]` up to `controller.current_size`.
- Flush when full, at end, or on exception.
- Catch `torch.cuda.OutOfMemoryError` / `RuntimeError` OOM patterns → `controller.on_oom()` → retry as singles.
- Checkpoint after each batch when `checkpoint_interval == 0`.

### CLI (`cli.py`)
- `--initial-batch-size INT` (default 1)
- `--max-batch-size INT` (default 32)
- `--adaptive-batch / --no-adaptive-batch` (default adaptive)
- `--checkpoint-interval` default changed to 0.

## Task checklist

- [x] Feature file created
- [ ] batch.py + test_batch_controller.py
- [ ] models/base.py caption_batch() default
- [ ] tests/stubs/caption_model.py caption_batch()
- [ ] models/blip2.py caption_batch() override
- [ ] runner.py batch loop
- [ ] cli.py new options
- [ ] pyproject.toml psutil dep
- [ ] tests/test_batch_runner.py integration tests
- [ ] ruff + mypy pass
- [ ] pytest pass
- [ ] committed and pushed

## Branch

`claude/optimize-constrained-hardware-Bv72K`
