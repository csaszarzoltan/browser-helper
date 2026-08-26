# MCP Memory Tools

**Since:** v1.26.0

Browser Helper ships a **persistent agent memory** layer backed by SQLite + FTS5. AI agents (Claude Code, Codex CLI, Cursor) driving the browser fleet via MCP can now persist facts across sessions — page states, selectors that work, anti-detection profile choices, user preferences, session notes — and recall them later with keyword search.

Memory is exposed as four MCP tools (`memory_remember`, `memory_recall`, `memory_forget`, `memory_list`) and a CLI surface (`bh memory add|search|list|delete`).

---

## 1. Quick start

### MCP tools (via any MCP client)

No setup required — memory tools are available automatically when the MCP server starts:

```bash
bh mcp                     # stdio
bh mcp --http --port 8765  # streamable HTTP
```

The server now exposes **64 tools** (37 browser/fleet + 4 memory + 6 agent testing + 17 E2E validation). Memory tools are backed by the `memory.persistent` capability (status: READY).

### CLI

```bash
# Store a memory
bh memory add --key "login-selector" --content "Use #email-field for login"

# Search memories
bh memory search --query "login"

# List all memories
bh memory list

# Filter by metadata
bh memory list --filter "source=claude-code"

# Delete a memory
bh memory delete --key "login-selector"
```

---

## 2. MCP tool reference

All memory tools return the standard JSON envelope (`status`/`operation`/`data`/`error`/`meta`) — the same contract as every other MCP tool. Agents can branch on `error.code` / `error.message` uniformly.

| Tool | Parameters | Description |
|------|-----------|-------------|
| `memory_remember` | `key` (str, required), `content` (str, required), `metadata` (str, optional — JSON object) | Store a memory entry. **Upserts by key** — if the key already exists, the entry is updated (content, metadata, updated_at). |
| `memory_recall` | `query` (str, required), `limit` (int, optional, default 10) | Search memories by keyword. Returns entries ordered by relevance: FTS5 keyword matches rank above non-matches; among equal matches, newer entries rank higher. Non-matching entries fill remaining slots (newest first). |
| `memory_forget` | `key_or_id` (str, required) | Remove a memory by key or id. Idempotent — returns `removed: true` even if the entry does not exist. |
| `memory_list` | `filter` (str, optional) | List all stored memories, ordered by most recently updated. Optional `filter` is a `key=value` expression matched against the metadata JSON object (e.g. `"source=claude-code"`). |

### Success envelope example

```json
{
  "status": "ok",
  "operation": "memory_remember",
  "data": {
    "id": 42,
    "key": "login-selector",
    "content": "Use #email-field for login",
    "metadata": {"source": "claude-code"},
    "created_at": "2026-08-09T20:00:00+00:00",
    "updated_at": "2026-08-09T20:00:00+00:00",
    "source_session": ""
  },
  "error": null,
  "meta": {}
}
```

### Error envelope example

```json
{
  "status": "error",
  "operation": "memory_remember",
  "data": null,
  "error": {"code": "invalid_params", "message": "key must be a non-empty string", "details": null},
  "meta": {}
}
```

### Error codes

| Code | Meaning |
|------|---------|
| `invalid_params` | Validation failure (empty key, empty content, bad metadata JSON, non-positive limit) |
| `operation_failed` | Store-level error (e.g. corrupt SQLite database) |

---

## 3. Storage

### SQLite database

- **Default path:** `~/.browser-helper/memory.db`
- **Override:** set `BROWSER_HELPER_MEMORY_DB` env var (see Configuration below)
- **Journal mode:** WAL (Write-Ahead Logging) — concurrent MCP sessions and CLI invocations share the same DB file safely; readers never block the writer
- **Busy timeout:** 5000 ms — concurrent writers wait up to 5 seconds before raising

### Schema

```sql
CREATE TABLE memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL UNIQUE,
    content TEXT NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}',       -- JSON object
    created_at TEXT NOT NULL,                  -- ISO-8601 UTC
    updated_at TEXT NOT NULL,                  -- ISO-8601 UTC
    source_session TEXT NOT NULL DEFAULT ''
);

CREATE TABLE embeddings (
    memory_id INTEGER PRIMARY KEY,
    vector TEXT NOT NULL,                      -- reserved for future vector ranking
    FOREIGN KEY (memory_id) REFERENCES memories (id) ON DELETE CASCADE
);
```

### FTS5 keyword search

A virtual table (`memories_fts`) is synchronized via triggers on INSERT/UPDATE/DELETE. The store probes for FTS5 availability at open time and falls back to LIKE matching if the running Python build lacks FTS5.

Search terms are quoted using the FTS5 `"..."` syntax so special characters never raise a MATCH error. The recall algorithm:

1. **FTS5 keyword match** — fetch up to `limit × 4` candidates ranked by FTS5 `rank`
2. **Recency tie-break** — sort keyword matches by `updated_at DESC`
3. **Fill remaining slots** — newest non-matching entries (up to `limit` total)
4. **Truncate** to `limit`

### Concurrency

- Writes serialize on a `threading.Lock` (one writer at a time)
- `check_same_thread=False` — the connection is shared across async handlers
- Each CLI subcommand opens its own `MemoryStore` instance (WAL keeps them safe)

### Vector ranking (future)

The `embeddings` table is reserved for optional vector search. When an embedder is configured, a pure-python cosine ranking is applied on top of FTS5 + recency. Without an embedder, the store degrades gracefully — recall never fails because of missing vectors. The `vector_mode` config flag controls this behavior.

---

## 4. Configuration

### Settings

`MemorySettings` dataclass (in `src/mcp_server/memory/config.py`):

| Field | Type | Default | Env var |
|-------|------|---------|---------|
| `store_path` | str | `~/.browser-helper/memory.db` | `BROWSER_HELPER_MEMORY_DB` |
| `search_limit` | int | `10` | `BROWSER_HELPER_MEMORY_SEARCH_LIMIT` |
| `vector_mode` | bool | `False` | `BROWSER_HELPER_MEMORY_VECTOR` |

### Precedence

**CLI > env > settings.json > defaults**

1. **CLI overrides** — programmatic `overrides` dict passed to `load_memory_settings()`
2. **Environment variables** — `BROWSER_HELPER_MEMORY_DB`, `BROWSER_HELPER_MEMORY_SEARCH_LIMIT`, `BROWSER_HELPER_MEMORY_VECTOR`
3. **settings.json** — `SettingsManager` lookup (shared with MCP server settings)
4. **Defaults** — the dataclass defaults above

---

## 5. CLI reference

The `bh memory` group is registered on the main `bh` Click router (`src/browser_helper/__main__.py`) and is also directly runnable as `python -m mcp_server.memory.cli`.

### `bh memory add`

Store a memory entry (upsert by key).

```bash
bh memory add --key "my-selector" --content "Use .submit-btn for form submit"
# → stored #1 key='my-selector' (updated_at=2026-08-09T20:00:00+00:00)

# With metadata
bh memory add --key "profile-choice" --content "stealth-chrome-120 for Google" \
  --metadata '{"source": "claude-code", "confidence": "high"}'
# → stored #2 key='profile-choice' (updated_at=2026-08-09T20:01:00+00:00)

# Upsert (updates existing key)
bh memory add --key "my-selector" --content "Updated: use .submit-v2"
# → stored #1 key='my-selector' (updated_at=2026-08-09T20:05:00+00:00)
```

Options:

| Flag | Required | Description |
|------|----------|-------------|
| `--key` | Yes | Unique identifier for the memory |
| `--content` | Yes | Text content to store |
| `--metadata` | No | JSON object string (e.g. `'{"source": "agent"}'`) |

### `bh memory search`

Search memories by keyword.

```bash
bh memory search --query "login"
# → 2 match(es):
#   #1  [login-selector]  (2026-08-09T20:05:00+00:00)
#     Updated: use .submit-v2
#   #2  [profile-choice]  (2026-08-09T20:01:00+00:00)
#     stealth-chrome-120 for Google

bh memory search --query "login" --limit 1
# → 1 match(es):
#   #1  [login-selector]  (2026-08-09T20:05:00+00:00)
#     Updated: use .submit-v2
```

Options:

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `--query` | Yes | — | Search keyword(s) |
| `--limit` | No | `10` | Maximum results |

### `bh memory list`

List all stored memories.

```bash
bh memory list
# → 2 entr(ies):
#   #1  [my-selector]  (2026-08-09T20:05:00+00:00)
#     Updated: use .submit-v2
#   #2  [profile-choice]  (2026-08-09T20:01:00+00:00)
#     stealth-chrome-120 for Google

# Filter by metadata key=value
bh memory list --filter "source=claude-code"
# → 1 entr(ies):
#   #2  [profile-choice]  (2026-08-09T20:01:00+00:00)
#     stealth-chrome-120 for Google
#     meta: {"confidence": "high", "source": "claude-code"}
```

Options:

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `--filter` | No | None | Metadata filter in `key=value` format |

### `bh memory delete`

Delete a memory entry by key or id. Idempotent — deleting a non-existent entry succeeds silently.

```bash
bh memory delete --key-or-id "my-selector"
# → deleted 'my-selector'

bh memory delete --key-or-id "nonexistent"
# → nothing to delete for 'nonexistent'
```

Options:

| Flag | Required | Description |
|------|----------|-------------|
| `--key-or-id` | Yes | Key string or numeric id |

---

## 6. Hybrid search behavior

The recall algorithm combines keyword matching, recency ranking, and optional vector similarity to return the most relevant entries:

```
┌──────────────────────────────────────────────────┐
│                  memory_recall                    │
├──────────────────────────────────────────────────┤
│ 1. FTS5 keyword match (limit × 4 candidates)     │
│    → ranked by FTS5 internal rank (lower = better)│
│                                                   │
│ 2. Recency tie-break                              │
│    → sort keyword matches by updated_at DESC      │
│                                                   │
│ 3. Fill remaining slots                           │
│    → newest non-matching entries (updated_at DESC)│
│                                                   │
│ 4. (Future) Vector cosine ranking                 │
│    → if vector_mode=True AND embedder available   │
│    → combined score: α × keyword + β × vector    │
│    → graceful degradation without embedder         │
│                                                   │
│ 5. Truncate to limit                              │
└──────────────────────────────────────────────────┘
```

**Without vector mode (default):** FTS5 keyword matches always rank above non-matches. Among keyword matches, newer entries rank higher. Non-matching entries fill the remaining slots newest-first.

**With vector mode (future):** When a vector embedder is configured and embeddings are stored in the `embeddings` table, a cosine similarity score is combined with the keyword score. The weighting is `α × keyword_rank + β × cosine_similarity` where `α + β = 1`. Without embeddings for some entries, those entries fall back to keyword + recency only.

---

## 7. Architecture

```
src/mcp_server/memory/
├── __init__.py      # exports MemoryStore, MemoryEntry
├── store.py         # MemoryStore — SQLite + FTS5 + WAL
├── tools.py         # MCP tool handlers (memory_remember, etc.)
├── config.py        # MemorySettings + load_memory_settings()
├── cli.py           # Click CLI group (bh memory add|search|list|delete)
└── types.py         # MemoryEntry dataclass
```

**Tool registration:** Memory tools are registered in `src/mcp_server/registry.py` with capability `memory.persistent` (status: READY). The `build_tool_defs()` function resolves handler references from `memory.tools` — the same pattern used for browser and fleet tools.

**Envelope contract:** All memory tools use `tool_result()` / `tool_error()` from `src/mcp_server/serialization.py`. The response shape is identical to every other MCP tool:

```json
{"status": "ok"|"error", "operation": "memory_*", "data": ..., "error": ..., "meta": {}}
```

**Corrupt store handling:** If the SQLite file is not a valid database (e.g. garbage bytes), `MemoryStore.open()` raises `sqlite3.DatabaseError` with a clear message. The handler catches this and returns a clean `operation_failed` error envelope — no traceback surfaces to the MCP client.
