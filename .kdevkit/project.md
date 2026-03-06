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

## Structure (target)
```
hudukaata/
  indexer/       # indexing job(s)
  search/        # search server
  .kdevkit/      # dev workflow metadata
```
