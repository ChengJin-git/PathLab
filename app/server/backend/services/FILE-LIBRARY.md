# File library and personal RAG

PathLab v1.0.8 · Updated 2026-11-06

The file library supplies the user's retrieval corpus. Uploads and generated files share a metadata catalog, revision checks and owner-scoped search.

## Retrieval stack

LlamaIndex Core 0.14.25 provides document chunking. LanceDB 0.41.0 stores local vector and BM25 indexes, with PyArrow 24.0.0 and Sentence Transformers 6.2.0. PathLab checks account authorization before and after retrieval.

References: [LlamaIndex node parsing](https://developers.llamaindex.ai/python/framework/module_guides/loading/node_parsers/modules/) and [LanceDB hybrid search](https://docs.lancedb.com/search/hybrid-search).

Embedding: `intfloat/multilingual-e5-small`, revision
`614241f622f53c4eeff9890bdc4f31cfecc418b3` (384 dimensions, CPU).
Reranking: `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1`, revision
`1427fd652930e4ba29e8149678df786c240d8825` (CPU).
Models are downloaded during deployment, not during user requests. `jieba 0.42.1`
segments Chinese and English for BM25. Model licenses/provenance remain upstream;
copy their complete snapshots for offline deployments.

## File lifecycle

`workbench_files` is the shared metadata catalog. Uploaded attachments, library
uploads, Chat deliveries and cataloged research outputs have an immutable
`storage_path` under `chat-files/<owner>/`, a content SHA-256 `revision`, source
conversation/title, optional folder, origin and indexing state. Research catalog
entries also retain their source path/revision so repeated indexing does not overwrite
user renames/replacements when the source has not changed.

The HTTP list/search endpoints return metadata only. File bytes are parsed only for
preview or indexing. File replacement publishes new bytes before updating the row;
the old revision becomes inaccessible immediately. File deletion revokes access and
removes its chunks and stored versions.

Deleting a conversation marks files belonging to that conversation or its research sessions as deleted before responding. The durable cleanup worker stops writers, removes their index entries and immutable stored versions, and deletes the associated records. Files uploaded independently to the library, or merely referenced by the conversation, remain independent. A saved storage copy does not by itself detach a file from its source conversation.

Supported automatic indexing: PDF (including OCR), UTF-8 text/Markdown/code,
HTML, CSV/TSV, DOCX, PPTX and XLSX. Other formats remain available for preview where
supported, download, and runtime references. Uploads are bounded to 64 MiB. Parser
processes have a 180-second deadline and a 4-million-character output budget;
PDFs use the existing 300-page CPU reader limit. Each document is capped at 2000
chunks. XLSX parsing caps sheets/rows explicitly and never executes formulas.

## Indexing and retrieval

The Gateway starts a durable polling worker. PostgreSQL's deployment-wide advisory
lock admits one indexer, row locking claims jobs, and stopped `processing` jobs are
requeued after lock recovery. Parsing runs in an isolated CPU subprocess. Text is
split using the embedding tokenizer (320-token chunks, 48-token overlap); PDF page
numbers, slide numbers, worksheet names and document sections accompany chunks.
Models and inference concurrency are bounded. A version is searchable only when
`index_status=ready` and `indexed_revision=revision`.

LanceDB has one directory/table per owner. SQL first selects authorized ready
file IDs and revisions; both vector and BM25 searches receive the same prefilter.
The top 24 candidates per retrieval method are fused with reciprocal rank fusion,
then reranked by the multilingual cross encoder. At most six passages are returned.
File ownership, deletion, revision and folder membership are checked again after
retrieval. Queries across more than 2000 files require a narrower folder/file scope.
Administrator views default to their own files; `all_users` is explicitly gated.

## Chat

`@` file discovery covers the authorized global library, not only the current chat.
Selected file IDs/revisions are reauthorized on each turn. Indexed files supply
retrieved evidence alongside bounded previews. The LLM can issue `SEARCH_FILES`
for natural-language requests about the user's library; no keyword router picks
the query. Retrieval output is untrusted evidence, never instructions.

Answers cite `/files?file=<id>&revision=<hash>&page=<n>` links. The frontend opens
the library preview and PDF page. A replaced file displays a version-change notice;
deleted or inaccessible sources cannot be previewed. When the documents do not
support an answer, Chat is instructed to state that rather than invent it.

## APIs

- `/file-library`: bounded metadata list, filename search, origin/folder/user filters.
- `/file-library/upload`: upload and automatically queue supported documents.
- `/file-library/folders`: create/list; `/{id}` rename/delete (files retained).
- `/file-library/files/{id}`: metadata, rename/move, delete.
- `/file-library/files/{id}/content`: replace content with expected revision.
- `/file-library/files/{id}/index`: retry or cancel processing.
- `/file-library/search`: semantic/keyword content search, optionally scoped.
- Existing `/workbench/files/{id}` preview/download and conversation file panels
  use the same IDs and owner checks.
- `/workbench/files/{id}/pages/{page}` serves version-checked rendered PDF/Office
  pages. PDF, presentations and Word documents share a paged viewer; table,
  Markdown/HTML, image, audio, video and code files retain their format-specific
  previews. Research detail links use the same file authorization and viewer.

Document publication schedules one bounded background converter so an opened
deliverable can reuse its PDF and first page. Unchanged content-addressed files
are not rewritten; cached previews remain valid. The first page is returned with
the descriptor, then nearby pages are fetched on demand. No preview parsing runs
during directory search. Office rendering uses LibreOffice on the host (optional
`PATHLAB_PREVIEW_SOFFICE` executable) or the installed Office-capable research
sandbox. The Ubuntu dependency installer includes Writer, Impress and CJK fonts.

## Deployment and verification

Run `deploy/prepare-knowledge.py` and `--check` before starting the current release.
Back up PostgreSQL, `chat-files`, `knowledge-index` and Hugging Face model snapshots
together. `current_schema.py` initializes a fresh current schema and verifies the
version of existing databases. All one-time application schema migration scripts
and startup backfills were removed after applying and recording the upgrade.
The storage-directory migration feature is an ongoing product capability and remains.

Regression coverage is in `server/tests/test_file_library.py`, `test_file_library_parser.py` and `test_chat_deletion.py`. These check revision replacement, retrieval authorization, durable deletion and preservation of independently referenced files. See [deployment](../../../deploy/README.md) for runtime preparation.
