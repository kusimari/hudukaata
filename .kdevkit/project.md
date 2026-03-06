# Project: hudukaata

## Purpose
A Python monorepo containing an indexing job service and a search server. The system indexes data for fast searching and retrieval.

## Tech Stack
- Language: Python
- Architecture: Monorepo (indexer + search server as separate services/packages)

## Constraints
No specific constraints specified; standard Python best practices apply.

## Quality Gate Settings

quality_threshold: 70
# Score 0–100; computed as max(0, 100 − penalty) where each High finding
# costs 10 pts, each Medium costs 3, each Low costs 1.
# Tune this value to adjust how strict the quality gate is.

max_test_fix_attempts: 2
# Maximum number of fix-and-rerun cycles for the test gate before stopping.
# When the limit is reached the agent must stop, report the remaining
# failures, and NOT push. The human reviewer decides what to do next.

## Structure (target)
```
hudukaata/
  indexer/       # indexing job(s)
  search/        # search server
  .kdevkit/      # dev workflow metadata
```
