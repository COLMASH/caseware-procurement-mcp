# Procurement Knowledge Base — Data Pipeline + MCP Server

A lightweight, **local** data pipeline and **MCP server** that let an AI agent
(Claude Desktop / ChatGPT / any MCP client) retrieve, compare and reason over a
heterogeneous procurement knowledge base — invoices, purchase orders, shipping
orders, inventory reports and a supply contract — with **grounded, source-cited**
answers.

> **Design thesis.** The data has two shapes, so retrieval has two shapes.
> The transactional records (invoices / POs / shipping / inventory) are
> relational, so they go into SQL tables and the cross-document questions become
> deterministic joins and anti-joins. The one narrative document (the contract)
> is the only thing that gets embedded for semantic search. The MCP client is the
> agent that routes between the tools. Most of the brief's example questions are
> relational, not semantic — so "embed everything into a vector store" would be
> the wrong architecture.

---

## What's in the box

| Component | Tech | Why |
|---|---|---|
| Storage | **SQLite** (one file) | tables + FTS5 keyword index + vectors, zero services |
| Vectors | **sqlite-vec** (`vec0`, 384-d) | local vector search in the same file (numpy fallback included) |
| Embeddings | **fastembed · bge-small-en-v1.5** | local, ONNX, no torch, no GPU, no API key |
| Clean PDFs | **pdfplumber** + deterministic parsers | consistent templates → parsing beats an LLM |
| Image invoices | **Claude vision** + tolerant Pydantic schema (cached) | the 5 JPGs are heterogeneous; an LLM absorbs layout variance |
| Contract | **PyMuPDF** (text + highlight colors) | digital PDF → **no OCR**; colors become data-quality metadata |
| Server | **FastMCP** (official MCP SDK), stdio | small, well-typed tool set; client is the agent |

No cloud, no agent framework, no dedicated vector DB — deliberately. See the
[technical overview](docs/technical-overview.md) for the full rationale and the
"what I did NOT build" list.

> **Full technical overview** — architecture, data flow, data modeling, retrieval,
> the six tools, citations, what was deliberately left out, the AWS scaling path,
> and a requirements-coverage map:
> [`docs/technical-overview.md`](docs/technical-overview.md) (or
> [`.html`](docs/technical-overview.html) for the formatted version with rendered diagrams).

---

## Setup

Requires [`uv`](https://docs.astral.sh/uv/) and Python ≥ 3.11.

```bash
cd caseware-procurement-mcp
uv sync            # creates the venv and installs locked dependencies
```

That's it. **No API key is required for the default flow** — the 5 image invoices
ship pre-extracted in `cache/`, so the pipeline runs fully offline.

### Optional: an Anthropic API key (only for *new* / *changed* images)

The image invoices are the one non-deterministic extractor — they go through
**Claude vision**. Each result is cached by the SHA-256 of the image bytes, so the
key is consulted **only on a cache miss**: a brand-new image, a changed image, or
an empty `cache/`. To enable that path, provide `ANTHROPIC_API_KEY` in any of three
ways (first match wins):

```bash
# (a) a .env file at the repo root  ← recommended; auto-loaded, git-ignored
cp .env.example .env          # then edit .env:  ANTHROPIC_API_KEY=sk-ant-...

# (b) export it for the whole shell session
export ANTHROPIC_API_KEY=sk-ant-...

# (c) inline, for a single command
ANTHROPIC_API_KEY=sk-ant-... uv run python -m procurement_kb.pipeline.run
```

The project auto-loads `.env` from the repo root (no extra dependency). A real
exported/inline variable always overrides `.env`. Optional overrides: `PKB_VISION_MODEL`
(default `claude-opus-4-8`) selects the vision model.

> If `cache/` is ever cleared and you have no API key, restore the pre-extracted
> invoices offline with `uv run python scripts/seed_image_cache.py`.

---

## 1) Run the data pipeline

```bash
uv run python -m procurement_kb.pipeline.run
```

Walks `data/`, registers every file for lineage, routes each document to the
right extractor, and builds `procurement.db` (relational tables + FTS5 +
contract vectors). Re-runnable and idempotent. Expected output:

```
Vector backend: sqlite-vec
Contract: 210 chunks, 209 indexed, 1 excluded (template/instruction blocks).
  Embedded 209 chunks (BAAI/bge-small-en-v1.5, 384-d).
Ingested: contract 1 · image_invoice 5 · inventory_report 7 · invoice 8 · purchase_order 8 · shipping_order 16
```

### Extraction modes — cache vs. live API, and changing the images

The pipeline is **re-runnable and idempotent**: every run drops and rebuilds
`procurement.db` from whatever is in `data/`, and the image-extraction cache is
keyed on each image's content hash. That yields five behaviors you can verify:

| You do… | What happens | API key needed? |
|---|---|---|
| Run as shipped (cache warm) | All 5 invoices load from `cache/` | **No** — fully offline |
| Clear `cache/`, then run | All 5 images re-extracted via Claude vision | **Yes** |
| Replace / edit an image in `data/invoices/` | Only that image re-extracts (new hash → cache miss); the rest stay cached | **Yes** (just the changed one) |
| Add a new image to `data/invoices/` | It's picked up and extracted; existing ones stay cached | **Yes** (just the new one) |
| Remove an image | It simply disappears on the next run | **No** |

```bash
# Full pipeline against the live API (no cache): force a clean extraction of all 5
mv cache cache.bak                                # or: rm cache/*.json
uv run python -m procurement_kb.pipeline.run      # -> 5 Claude-vision calls
rm -rf cache && git checkout -- cache             # restore committed extractions
                                                  # (or: rm -rf cache && mv cache.bak cache)

# Add or change an image, then just re-run — only the new/changed file calls the API
cp my_new_invoice.jpg data/invoices/
uv run python -m procurement_kb.pipeline.run      # -> 1 Claude-vision call, rest cached

# Back to fully offline (cache warm): zero API calls, deterministic output
uv run python -m procurement_kb.pipeline.run      # -> 0 API calls
```

`doc_id` is the image filename without its extension, so a new file becomes a new
`image_invoice` document automatically. A differently-shaped invoice still extracts
without code changes — the Pydantic schema is a mostly-optional superset with a
`layout_family` discriminator.

> **Seeing a data change in the client.** The MCP server reads only `procurement.db`
> — never `data/` or `cache/` directly. So after you add, change, or remove a file in
> `data/`, **re-run the pipeline** to rebuild `procurement.db`; the client then reflects
> it on its **next** tool call automatically — no need to restart Claude Desktop.
> (Editing `cache/` alone changes nothing the client sees; the cache is only an input to
> the pipeline.) Restart Claude Desktop **only** when you change the server code or the
> config, which it reads at startup.

## 2) Run / connect the MCP server

**stdio (for Claude Desktop):**
```bash
uv run python -m procurement_kb.server.mcp_server
```

**Claude Desktop** (live tool calls). You don't run the command above yourself —
Claude Desktop launches the server for you once it's registered:

1. **Open the config file** (create it if it doesn't exist), or use Claude Desktop →
   Settings → Developer → Edit Config:
   - macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
   - Windows: `%APPDATA%\Claude\claude_desktop_config.json`
2. **Add the `procurement-kb` block** from
   [`docs/claude_desktop_config.example.json`](docs/claude_desktop_config.example.json)
   inside `mcpServers`, and replace `ABSOLUTE_PATH` with the full path to this repo.
3. **If Claude Desktop can't find `uv`** — the server shows as failed or the log says
   `spawn uv ENOENT` — note that Claude Desktop does **not** inherit your shell `PATH`,
   so a bare `"command": "uv"` fails when `uv` isn't on a standard system path. Fix it
   by using uv's **absolute path**: run `which uv` (macOS/Linux) or `where uv` (Windows)
   and use that as `"command"`, e.g. `"command": "/Users/you/.local/bin/uv"`.
4. **Fully quit and reopen** Claude Desktop (⌘Q on macOS — the config is read only at
   startup). The server appears under Settings → Developer and the six tools show in the
   tools (🔌) menu.
5. **Ask an example question** — *"Which invoices are missing a purchase order?"* — and
   it calls the tools and answers with sources.

> **Troubleshooting:** if the server doesn't appear, the log says why —
> `~/Library/Logs/Claude/mcp-server-procurement-kb.log` (macOS). The usual cause is the
> `uv` path (step 3) or a wrong `ABSOLUTE_PATH`. If you already have other MCP servers,
> just add `procurement-kb` alongside them inside the same `mcpServers` object.

---

## Evidence it works

```bash
# 1. The 8 example questions answered with grounded sources (offline, no GUI):
uv run python scripts/smoke_test.py

# 2. A real MCP protocol round-trip via the official MCP client:
uv run python scripts/mcp_client_test.py
```

`mcp_client_test.py` spawns the server over stdio, lists the 6 tools, and calls
them — proving the server speaks MCP to a client, returning `structuredContent`.
Captured output is in [`docs/EVIDENCE.txt`](docs/EVIDENCE.txt). A point-by-point map
of every brief requirement to where it is addressed is in the technical overview's
[Requirements coverage appendix](docs/technical-overview.md#appendix--requirements-coverage).

---

## MCP tools (the retrieval surface)

| Tool | Answers |
|---|---|
| `search(query, doc_type?, limit)` | "find evidence about a vendor / order / item" (keyword over all records) |
| `get_document(doc_id)` | full structured record + line items for one document |
| `get_order_dossier(order_id)` | "which documents support order 10687?" / "what PO supports this invoice?" |
| `reconcile(order_id?)` | "which invoices are missing a PO?" / "mismatches between invoice/PO/shipping?" |
| `search_contract(query, k)` | "summarize the contract terms relevant to supply of goods" (hybrid vector + BM25) |
| `list_inventory_reports()` | "what inventory reports are available, and what period do they cover?" |

Every result carries a `SourceRef { doc_id, category, source_path, page }` so the
agent's answers trace back to the original file.

---

## Project layout

```
procurement_kb/
  config.py              paths + model settings
  models.py              Pydantic schemas (extraction + typed tool I/O)
  db.py                  SQLite schema, sqlite-vec loading (+ fallback)
  pipeline/
    run.py               orchestrator  -> procurement.db
    cache.py             content-hash extraction cache
    extract_pdf.py       deterministic Northwind parsers
    extract_image.py     Claude-vision structured extraction (cached)
    extract_contract.py  PyMuPDF text + highlight-color metadata (no OCR)
    embed.py             fastembed bge-small (graceful fallback)
  server/
    queries.py           query logic (typed, testable)
    mcp_server.py        FastMCP tool definitions
scripts/
  seed_image_cache.py    seeds the 5 pre-extracted invoices
  smoke_test.py          8 example questions -> grounded answers
  mcp_client_test.py     MCP protocol round-trip
data/                          the provided documents (self-contained)
cache/                         5 pre-extracted invoices (committed -> offline reproducible)
docs/technical-overview.md     full technical overview (architecture -> AWS, + requirements coverage)
docs/technical-overview.html   the same overview, formatted with rendered diagrams
docs/claude_desktop_config.example.json   Claude Desktop MCP config block
docs/EVIDENCE.txt              captured smoke-test + MCP round-trip output
```

## AI-assisted development

Built with AI assistance (Claude Code) for scaffolding, the parsers and the MCP
wiring. Validation: extraction cross-checked against the raw PDF text and the
images; `smoke_test.py` and `mcp_client_test.py` verify answers, sources and the
MCP round-trip; every SQL query is auditable. Architecture and trade-offs are my
own — see the [technical overview](docs/technical-overview.md).
