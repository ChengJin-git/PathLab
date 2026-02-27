"""
Chat and conversation management routes
Handles AI chat, conversation persistence, and task parsing
"""
import asyncio
import json
import mimetypes
import os
import re
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import httpx
from typing import List, Dict, AsyncIterator, Optional
from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.database import get_db
from backend.database.repositories import ChatRepository, WSIRepository, TrainedModelRepository, DatasetPermissionRepository, DatasetRepository, TrainingTaskRepository, AITaskRepository
from backend.database.models import TrainingTask, DataGroup, WSISlide, TrainingTaskWSI
from backend.auth import current_active_user, User
from backend.auth.dependencies import check_data_ownership, get_user_id_filter, get_user_from_header_or_param
from backend.common.config import Config
from backend.common.gpu_utils import get_gpu_summary_for_prompt
from ..dependencies import logger
from ..prompts import get_chat_system_prompt, format_user_data_context, detect_language
from ..models import ChatRequest, CreateConversationRequest, UpdateMessageRequest, AddMessageRequest
from .chat_pdf import (
    is_pdf_url, process_pdf_url, get_pdf_image_path,
    search_pdf_pages, get_cached_markdown, get_cached_pdf_meta, _split_md_into_pages,
    _get_url_hash, _get_pdf_cache_dir, _tokenize_for_search,
    detect_source_type, is_academic_content, format_reference_card,
)
from .chat_pdf_vectorstore import search_pdf_chunks

router = APIRouter(tags=["Chat & Conversations"])

# Maximum PDF papers to include in the AI supplement response (awaited tasks).
# ALL PDFs found in search results are started as background tasks (so they get
# cached for follow-up questions), but only the first _MAX_PDFS_SUPPLEMENT are
# awaited and included in the immediate supplement response.
_MAX_PDFS_SUPPLEMENT = 3

# Language-specific PDF supplement prompts (for i18n)
_PDF_SUPPLEMENT_PROMPTS = {
    "en": (
        "Here is the full content from the PDF papers that were being parsed in the background. "
        "Each paper is labelled [Paper N] so you can refer to them by number when the user asks "
        "which paper they mean (e.g. 'the HKUST paper' → look at the title/URL to match). "
        "Please supplement your previous response with specific details and citations from these papers.\n\n"
        "## STRICT GROUNDING RULES (MANDATORY)\n"
        "1. Your answer MUST be based ENTIRELY on the paper content below. "
        "Do NOT use your training knowledge to supplement information not present in the papers.\n"
        "2. Every factual claim MUST include a citation: [N, p.Y] (only when `--- Page Y ---` marker is visible) "
        "or [N] (when no page marker is available). N is the paper number. NEVER guess or invent page numbers.\n"
        "3. If the user asks about information NOT found in the provided paper content, you MUST say: "
        "'I could not find this information in the retrieved paper content. "
        "You can ask me to search specific pages or sections.'\n"
        "4. If a PDF failed to download or parse, you MUST tell the user explicitly. "
        "Do NOT answer from training knowledge as a substitute.\n\n"
        "## IMAGE RULES\n"
        "When a paper's content contains Markdown image links like ![fig](http://...), you MUST "
        "include those links verbatim in your response so the user can see the figures. "
        "Do NOT describe images as a substitute for the actual image link. "
        "If the user asks for a figure but the paper shows [PDF_IMAGES_STATUS: pending], tell the user "
        "that high-precision figure extraction is still running and to ask again later.\n\n"
        "## OTHER RULES\n"
        "LONG PAPERS: For papers with many pages, only the beginning, end, and most relevant "
        "middle sections are shown. If the user asks about a section not visible here, tell them "
        "you can search for specific pages or topics if they ask a follow-up question. "
        "CRITICAL: The [REFERENCE] blocks in the context are already correctly formatted. "
        "Copy them verbatim into your response - DO NOT modify their format or content."
    ),
    "zh_CN": (
        "以下是后台解析的 PDF 论文完整内容。"
        "每篇论文都标有 [Paper N] 编号，当用户问\"哪一篇\"时，请通过标题/URL 对应编号来回答。"
        "请用具体细节和论文引用来补充你之前的回答。\n\n"
        "## 严格 Grounding 规则（必须遵守）\n"
        "1. 你的回答**必须完全基于**下方论文内容。**禁止**使用训练知识补充论文中不存在的信息。\n"
        "2. 每个事实性陈述**必须**标注来源：[N, p.Y]（仅当能看到 `--- Page Y ---` 标记时）"
        "或 [N]（无页码标记时）。N 是论文编号。**绝对不要**猜测或捏造页码。\n"
        "3. 如果用户问的信息**不在**已提供的论文内容中，你**必须**说："
        "\"我在已检索的论文内容中没有找到这个信息，您可以让我搜索特定页面或章节。\"\n"
        "4. 如果某篇 PDF 下载或解析失败，**必须**明确告知用户，**不得**用训练知识替代回答。\n\n"
        "## 图片规则\n"
        "如果论文内容中包含 Markdown 图片链接（如 ![fig](http://...)），你**必须**将这些链接原样放入回答中，"
        "让用户直接看到图片。**不要**用文字描述来替代实际图片链接。"
        "如果用户询问图片但看到 [PDF_IMAGES_STATUS: pending]，请告知用户高精度图片提取仍在后台运行，稍后再问。\n\n"
        "## 其他规则\n"
        "长论文提示：对于页数很多的论文，仅展示了开头、结尾和最相关的中间部分。"
        "如果用户问到未展示的章节，请告知用户可以通过追问来搜索特定页面或主题。"
        "重要：上下文中的 [REFERENCE] 块格式已正确，请原样复制到回答中，不要修改格式或内容。"
    ),
    "zh_HK": (
        "以下是後台解析的 PDF 論文完整內容。"
        "每篇論文都標有 [Paper N] 編號，當用戶問「哪一篇」時，請透過標題/URL 對應編號來回答。"
        "請用具體細節和論文引用來補充你之前的回答。\n\n"
        "## 嚴格 Grounding 規則（必須遵守）\n"
        "1. 你的回答**必須完全基於**下方論文內容。**禁止**使用訓練知識補充論文中不存在的資訊。\n"
        "2. 每個事實性陳述**必須**標註來源：[N, p.Y]（僅當能看到 `--- Page Y ---` 標記時）"
        "或 [N]（無頁碼標記時）。N 是論文編號。**絕對不要**猜測或捏造頁碼。\n"
        "3. 如果用戶問的資訊**不在**已提供的論文內容中，你**必須**說："
        "「我在已檢索的論文內容中沒有找到這個資訊，您可以讓我搜尋特定頁面或章節。」\n"
        "4. 如果某篇 PDF 下載或解析失敗，**必須**明確告知用戶，**不得**用訓練知識替代回答。\n\n"
        "## 圖片規則\n"
        "如果論文內容中包含 Markdown 圖片連結（如 ![fig](http://...)），你**必須**將這些連結原樣放入回答中，"
        "讓用戶直接看到圖片。**不要**用文字描述來替代實際圖片連結。"
        "如果用戶詢問圖片但看到 [PDF_IMAGES_STATUS: pending]，請告知用戶高精度圖片提取仍在後台運行，稍後再問。\n\n"
        "## 其他規則\n"
        "長論文提示：對於頁數很多的論文，僅展示了開頭、結尾和最相關的中間部分。"
        "如果用戶問到未展示的章節，請告知用戶可以透過追問來搜尋特定頁面或主題。"
        "重要：上下文中的 [REFERENCE] 區塊格式已正確，請原樣複製到回答中，不要修改格式或內容。"
    ),
}

# Language-specific prompts for [READ_ARTICLE] tool — injected when the AI
# explicitly requests to read a full article for the user.
_READ_ARTICLE_PROMPTS = {
    "en": (
        "Here is the full content of the article the user asked to read. "
        "The content includes `--- Page X ---` markers for each page.\n\n"
        "## STRICT GROUNDING RULES (MANDATORY)\n"
        "1. Your answer MUST be based ENTIRELY on the article content below. "
        "Do NOT use your training knowledge to supplement information not present in the article.\n"
        "2. Every factual claim MUST include a citation: [N, p.Y] where N is the search result number "
        "and Y is the page number (only when `--- Page Y ---` marker is visible). "
        "NEVER guess or invent page numbers.\n"
        "3. If asked about information NOT found in the article, say: "
        "'I could not find this information in the retrieved article content.'\n"
        "4. If the article failed to download or parse, tell the user explicitly.\n\n"
        "## IMAGE RULES\n"
        "When the content contains Markdown image links like ![fig](http://...), include them verbatim.\n\n"
        "## OTHER RULES\n"
        "For long articles, only head/tail sections are shown. If the user asks about a missing section, "
        "tell them to ask a more specific follow-up question.\n"
        "CRITICAL: The [REFERENCE] blocks are already correctly formatted. "
        "Copy them verbatim into your response."
    ),
    "zh_CN": (
        "以下是用户要求阅读的文章完整内容。内容包含 `--- Page X ---` 页码标记。\n\n"
        "## 严格 Grounding 规则（必须遵守）\n"
        "1. 你的回答**必须完全基于**下方文章内容。**禁止**使用训练知识补充。\n"
        "2. 每个事实性陈述**必须**标注来源：[N, p.Y]，其中 N 是搜索结果编号，"
        "Y 是页码（仅当能看到 `--- Page Y ---` 标记时）。**绝对不要**猜测页码。\n"
        "3. 如果用户问的信息**不在**文章内容中，请说："
        "\"我在已检索的文章内容中没有找到这个信息。\"\n"
        "4. 如果文章下载或解析失败，**必须**明确告知用户。\n\n"
        "## 图片规则\n"
        "如果内容中包含 Markdown 图片链接（如 ![fig](http://...)），请原样放入回答中。\n\n"
        "## 其他规则\n"
        "长文章仅展示了开头和结尾部分。如果用户问到未展示的章节，请告知用户提出更具体的问题。\n"
        "重要：[REFERENCE] 块格式已正确，请原样复制到回答中。"
    ),
    "zh_HK": (
        "以下是用戶要求閱讀的文章完整內容。內容包含 `--- Page X ---` 頁碼標記。\n\n"
        "## 嚴格 Grounding 規則（必須遵守）\n"
        "1. 你的回答**必須完全基於**下方文章內容。**禁止**使用訓練知識補充。\n"
        "2. 每個事實性陳述**必須**標註來源：[N, p.Y]，其中 N 是搜尋結果編號，"
        "Y 是頁碼（僅當能看到 `--- Page Y ---` 標記時）。**絕對不要**猜測頁碼。\n"
        "3. 如果用戶問的資訊**不在**文章內容中，請說："
        "「我在已檢索的文章內容中沒有找到這個資訊。」\n"
        "4. 如果文章下載或解析失敗，**必須**明確告知用戶。\n\n"
        "## 圖片規則\n"
        "如果內容中包含 Markdown 圖片連結（如 ![fig](http://...)），請原樣放入回答中。\n\n"
        "## 其他規則\n"
        "長文章僅展示了開頭和結尾部分。如果用戶問到未展示的章節，請告知用戶提出更具體的問題。\n"
        "重要：[REFERENCE] 區塊格式已正確，請原樣複製到回答中。"
    ),
}

# Prompt fragment appended when PDF context is rebuilt for follow-up questions.
_PDF_FOLLOWUP_NOTE = {
    "en": (
        "NOTE: The PDF content below has been semantically searched to show the most relevant "
        "chunks for the user's latest question, along with the first and last pages for context. "
        "Chunks are labelled with page number and chunk index (e.g. `Page 3, Chunk 5`). "
        "When citing, use [N, p.Y] format where N is the paper number. If the user asks about content not shown here, "
        "tell them to ask a more specific follow-up question so the system can retrieve it.\n"
        "STRICT GROUNDING: Your answer MUST be based ENTIRELY on the paper content below. "
        "Do NOT use training knowledge to fill gaps. "
        "When quoting original text from the paper, use blockquotes (> ...) to clearly distinguish "
        "the paper's original words from your own analysis.\n"
        "If a paper's images are available (shown in Paper Registry), include image links verbatim."
    ),
    "zh_CN": (
        "注意：以下 PDF 内容已通过语义搜索筛选，展示与用户最新提问最相关的文本片段以及首尾页作为上下文。"
        "片段标记了页码和块编号（如 `Page 3, Chunk 5`）。引用格式：[N, p.Y]，其中 N 是论文编号。"
        "如果用户询问的信息不在这些片段中，请告诉用户提出更具体的追问以便系统检索。\n"
        "严格 Grounding：你的回答**必须完全基于**下方论文内容，**禁止**用训练知识填补空白。"
        "引用论文原文时，请使用引用块（> ...）来清楚区分论文原文和你自己的分析。\n"
        "如果论文图片可用（见 Paper Registry），请将图片链接原样包含在回答中。"
    ),
    "zh_HK": (
        "注意：以下 PDF 內容已透過語義搜尋篩選，展示與用戶最新提問最相關的文本片段以及首尾頁作為上下文。"
        "片段標記了頁碼和塊編號（如 `Page 3, Chunk 5`）。引用格式：[N, p.Y]，其中 N 是論文編號。"
        "如果用戶詢問的資訊不在這些片段中，請告訴用戶提出更具體的追問以便系統檢索。\n"
        "嚴格 Grounding：你的回答**必須完全基於**下方論文內容，**禁止**用訓練知識填補空白。"
        "引用論文原文時，請使用引用區塊（> ...）來清楚區分論文原文和你自己的分析。\n"
        "如果論文圖片可用（見 Paper Registry），請將圖片連結原樣包含在回答中。"
    ),
}


def _collect_pdf_urls_from_contexts(messages: list[dict]) -> list[str]:
    """Extract all unique PDF URLs from all [PDF_CONTEXT] blocks in conversation history.

    Returns a deduplicated list of URLs preserving first-seen order.
    """
    pdf_ctx_re = re.compile(r'\[PDF_CONTEXT\]\n?([\s\S]*?)\n?\[/PDF_CONTEXT\]')
    seen: dict[str, None] = {}  # ordered dict for dedup
    for msg in messages:
        if msg.get("role") != "user":
            continue
        raw = extract_text_from_content(msg.get("content", ""))
        m = pdf_ctx_re.search(raw)
        if m:
            urls = re.findall(r'- \*\*URL\*\*: (https?://[^\s\n]+)', m.group(1))
            for u in urls:
                seen.setdefault(u, None)
    return list(seen.keys())


def _build_merged_pdf_context(all_urls: list[str], user_query: str, detected_lang: str = "en") -> str:
    """Build a single merged PDF context from all unique URLs with BM25 page selection.

    This replaces the old per-block `_enhance_pdf_context_for_query` with a
    global merge that:
      1. Builds a Paper Registry with global sequential numbering and image status.
      2. Re-reads the **latest** cached markdown for each URL from disk (so MinerU
         upgrades are picked up automatically).
      3. Uses BM25 to select the most relevant pages per paper.
      4. Returns one unified context string.
    """
    _PDF_MAX_CHARS_PER_PAPER = 40_000

    if not all_urls:
        return ""

    total = len(all_urls)
    enhanced_parts: list[str] = []

    # ── Global Document Registry ─────────────────────────────────────────────
    registry_lines = [f"## Document Registry ({total} documents):\n"]
    paper_metas: list[dict] = []
    for idx, url in enumerate(all_urls, 1):
        meta = get_cached_pdf_meta(url) or {}
        title = meta.get('title', 'Unknown')
        parse_method = meta.get('parse_method', 'unknown')

        # Determine academic status from cache meta (persisted by process_pdf_url).
        # If not in cache (legacy), re-detect from cached markdown + source type.
        if 'is_academic' in meta:
            is_academic = meta['is_academic']
        else:
            cached_md = get_cached_markdown(url)
            src_type = detect_source_type(url)
            is_academic = is_academic_content(cached_md or "", src_type) if cached_md else False

        label = "Paper" if is_academic else "Doc"

        # Image status detection
        url_hash = _get_url_hash(url)
        images_dir = _get_pdf_cache_dir() / "images" / url_hash
        image_count = 0
        if images_dir.is_dir():
            image_count = sum(1 for f in images_dir.iterdir() if f.is_file())
        if image_count > 0:
            image_status = f"{image_count} figures ✅"
        elif parse_method == "pymupdf":
            image_status = "pending ⏳"
        else:
            image_status = "none"

        registry_lines.append(
            f"- [{label} {idx}] {title} ({url}) | Parse: {parse_method} | Images: {image_status}"
        )
        paper_metas.append({
            'url': url, 'meta': meta, 'title': title,
            'parse_method': parse_method, 'image_count': image_count,
            'is_academic': is_academic,
        })

        logger.info(
            f"[BM25] {label} {idx} '{title}': parse_method={parse_method}, "
            f"is_academic={is_academic}, images_available={image_count > 0} ({image_count} images)"
        )

    registry_lines.append("")
    enhanced_parts.extend(registry_lines)

    followup_note = _PDF_FOLLOWUP_NOTE.get(detected_lang, _PDF_FOLLOWUP_NOTE["en"])
    enhanced_parts.append(followup_note + "\n")
    enhanced_parts.append("## PDF Content (query-relevant pages):\n")

    # ── Per-document rebuild ─────────────────────────────────────────────────
    for paper_idx, pd in enumerate(paper_metas, 1):
        url = pd['url']
        meta = pd['meta']
        title = pd['title']
        page_count = meta.get('page_count')
        parse_method = pd['parse_method']
        is_academic = pd.get('is_academic', False)
        label = "Paper" if is_academic else "Doc"
        content_type = "Academic Paper" if is_academic else "General Document"
        quality_label = (
            "High-precision (MinerU — includes tables, formulas, images)"
            if parse_method == "mineru"
            else "Fast (PyMuPDF — text only, images not yet extracted)"
        )
        page_info = f"{page_count} pages" if page_count else "page count unknown"

        enhanced_parts.append(
            f"### [{label} {paper_idx} of {total}] {title}\n"
            f"- **URL**: {url}\n"
            f"- **Content type**: {content_type}\n"
            f"- **Total pages**: {page_info}\n"
            f"- **Parse quality**: {quality_label}\n"
        )

        # Read full cached markdown (always re-reads from disk → picks up MinerU upgrades)
        full_md = get_cached_markdown(url)
        if not full_md:
            enhanced_parts.append("[Content not available — cache may have expired]\n---\n")
            continue

        # 改动 8: Strip stale IMAGE_STATUS markers from old content
        full_md = re.sub(r'\[PDF_IMAGES_STATUS:[^\]]*\]', '', full_md)

        # Short papers: include everything
        if len(full_md) <= _PDF_MAX_CHARS_PER_PAPER:
            enhanced_parts.append(full_md)
            enhanced_parts.append("---\n")
            continue

        # ── Vector search for relevant chunks (with BM25 fallback) ──────────
        url_hash = _get_url_hash(url)
        vector_results = search_pdf_chunks(user_query, url_hashes=[url_hash], top_k=15)

        if vector_results:
            # Use vector search results — group by page, sorted by page_num
            logger.info(
                f"[VectorSearch] {label} {paper_idx}: {len(vector_results)} chunks "
                f"retrieved (best distance={vector_results[0]['_distance']:.3f})"
            )
            # Always include first and last page for context
            all_pages = _split_md_into_pages(full_md)
            first_pn, first_content = all_pages[0] if all_pages else (0, "")
            last_pn, last_content = all_pages[-1] if all_pages else (0, "")

            content_parts: list[str] = []
            char_count = 0

            # Add first page
            if first_content:
                first_text = f"--- Page {first_pn} ---\n{first_content}\n"
                content_parts.append(first_text)
                char_count += len(first_text)

            # Add vector-retrieved chunks, sorted by page then chunk_index
            sorted_chunks = sorted(vector_results, key=lambda c: (c["page_num"], c["chunk_index"]))
            seen_chunks = set()
            for chunk in sorted_chunks:
                chunk_key = (chunk["page_num"], chunk["chunk_index"])
                if chunk_key in seen_chunks:
                    continue
                seen_chunks.add(chunk_key)
                # Skip if this chunk is from first or last page (already included)
                if chunk["page_num"] == first_pn or chunk["page_num"] == last_pn:
                    continue
                chunk_text = (
                    f"--- Page {chunk['page_num']}, Chunk {chunk['chunk_index']} ---\n"
                    f"{chunk['chunk_text']}\n"
                )
                if char_count + len(chunk_text) > _PDF_MAX_CHARS_PER_PAPER:
                    break
                content_parts.append(chunk_text)
                char_count += len(chunk_text)

            # Add last page
            if last_pn != first_pn and last_content:
                last_text = f"--- Page {last_pn} ---\n{last_content}\n"
                if char_count + len(last_text) <= _PDF_MAX_CHARS_PER_PAPER:
                    content_parts.append(last_text)

            total_p = page_count or (len(all_pages) if all_pages else 0)
            note = (
                f"[Semantic search: showing {len(seen_chunks)} most relevant chunks "
                f"from {total_p} total pages. Ask about specific topics for more.]\n"
            )
            content_parts.insert(0, note)
            enhanced_parts.append("\n".join(content_parts))
        else:
            # ── BM25 fallback for documents not yet vector-indexed ────────────
            logger.info(f"[BM25 Fallback] {label} {paper_idx}: no vector results, using BM25")
            all_pages = _split_md_into_pages(full_md)
            if not all_pages:
                enhanced_parts.append(full_md[:_PDF_MAX_CHARS_PER_PAPER] + "\n[...truncated]\n")
            else:
                first_pn, first_content = all_pages[0]
                last_pn, last_content = all_pages[-1]

                bm25_results = search_pdf_pages(full_md, user_query, top_k=10)
                bm25_extras = [
                    (pn, content, score)
                    for pn, content, score in bm25_results
                    if pn != first_pn and pn != last_pn
                ]

                selected: list[tuple[int, str]] = [(first_pn, first_content)]
                for pn, content, _ in sorted(bm25_extras, key=lambda x: x[0]):
                    selected.append((pn, content))
                if last_pn != first_pn:
                    selected.append((last_pn, last_content))

                content_parts = []
                char_count = 0
                prev_pn = None
                for pn, page_content in selected:
                    page_text = f"--- Page {pn} ---\n{page_content}\n"
                    if char_count + len(page_text) > _PDF_MAX_CHARS_PER_PAPER:
                        remaining = _PDF_MAX_CHARS_PER_PAPER - char_count
                        if remaining > 200:
                            content_parts.append(page_text[:remaining] + "\n[...page truncated for length]")
                        break
                    if prev_pn is not None and pn > prev_pn + 1:
                        content_parts.append(f"\n[...pages {prev_pn + 1}–{pn - 1} omitted — ask about them if needed...]\n")
                    content_parts.append(page_text)
                    char_count += len(page_text)
                    prev_pn = pn

                shown = len([p for p in content_parts if p.startswith("--- Page")])
                total_p = page_count or len(all_pages)
                if shown < total_p:
                    note = (
                        f"[Showing {shown} of {total_p} pages: page 1 + "
                        f"{max(shown - 2, 0)} query-relevant pages + last page. "
                        f"Ask about specific pages or topics for more.]\n"
                    )
                    content_parts.insert(0, note)
                enhanced_parts.append("\n".join(content_parts))

        enhanced_parts.append("---\n")

    return "\n".join(enhanced_parts)


# Include feedback sub-router
from .chat_feedback import router as chat_feedback_router
router.include_router(chat_feedback_router)


def extract_text_from_content(content) -> str:
    """Extract text content from message content (handles both string and multimodal format)"""
    if isinstance(content, str):
        return content
    elif isinstance(content, list):
        # Multimodal format: [{"type": "text", "text": "..."}, {"type": "image_url", ...}]
        text_parts = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                text_parts.append(part.get("text", ""))
        return " ".join(text_parts)
    return ""


def _extract_citation_contexts(
    ai_response: str, article_pdf_content: str,
    per_paper_content: dict[int, str] | None = None,
) -> dict | None:
    """Extract citation contexts from AI response using BM25 paragraph search.

    For each ``[N, p.Y]`` citation found in *ai_response*, locate the
    most relevant ~200-char snippet from the corresponding page in the
    article PDF content (which contains ``--- Page X ---`` markers).

    When *per_paper_content* is provided (multi-paper follow-up), each
    paper's pages are stored separately so page numbers from different
    papers don't collide.

    Returns a dict keyed by ``"N-pY"`` with ``{page, context}`` values,
    or ``None`` if no citations are found.
    """
    import math
    from collections import Counter

    # General pattern: [N, p.ANY_PAGE_DESCRIPTION] — matches p.2, p.2-3, p.2, p.4, etc.
    citation_pattern = re.compile(r'\[(\d{1,2}),\s*(p\.[^\]]+)\]')
    citations = citation_pattern.findall(ai_response)
    if not citations:
        return None

    # Build per-paper page maps to avoid page-number collisions
    if per_paper_content:
        paper_page_maps: dict[int, dict[int, str]] = {}
        for paper_idx, content in per_paper_content.items():
            pgs = _split_md_into_pages(content)
            paper_page_maps[paper_idx] = {pn: ct for pn, ct in pgs}
    else:
        # Single-paper mode: all citations share the same page map
        pages = _split_md_into_pages(article_pdf_content)
        _single_page_map: dict[int, str] = {pn: ct for pn, ct in pages}
        paper_page_maps = {}  # unused in single mode

    def _best_paragraph(page_text: str, query: str, max_len: int = 200) -> str:
        """BM25-rank paragraphs of *page_text* against *query*,
        return the best-matching snippet truncated to *max_len* chars."""
        paragraphs = [p.strip() for p in re.split(r'\n{2,}', page_text) if p.strip()]
        if not paragraphs:
            return page_text[:max_len].strip()

        q_tokens = _tokenize_for_search(query)
        if not q_tokens:
            return paragraphs[0][:max_len]

        para_tokens = [_tokenize_for_search(p) for p in paragraphs]
        N = len(paragraphs)
        avgdl = sum(len(t) for t in para_tokens) / N if N else 1
        k1, b = 1.5, 0.75

        unique_qt = set(q_tokens)
        df: dict[str, int] = {qt: 0 for qt in unique_qt}
        for tl in para_tokens:
            for qt in unique_qt & set(tl):
                df[qt] += 1

        best_score, best_idx = -1.0, 0
        for idx, tl in enumerate(para_tokens):
            tf = Counter(tl)
            dl = len(tl)
            score = 0.0
            for qt in q_tokens:
                if qt not in tf:
                    continue
                n_qt = df[qt]
                idf = math.log((N - n_qt + 0.5) / (n_qt + 0.5) + 1)
                score += idf * (tf[qt] * (k1 + 1)) / (tf[qt] + k1 * (1 - b + b * dl / avgdl))
            if score > best_score:
                best_score = score
                best_idx = idx

        best_text = paragraphs[best_idx]
        # Strip URLs — they add no value in a tooltip snippet and clutter the display
        best_text = re.sub(r'https?://[^\s)\]]+', '', best_text).strip()
        # Collapse multiple spaces left after URL removal
        best_text = re.sub(r'  +', ' ', best_text)
        snippet = best_text[:max_len].strip()
        if len(best_text) > max_len:
            snippet += "…"
        return snippet

    contexts: dict[str, dict] = {}
    for idx_str, page_part in citations:
        # Normalize key: remove whitespace from page part for consistent lookup
        key = f"{idx_str}-{page_part.replace(' ', '')}"
        if key in contexts:
            continue

        # Select the correct page map for this paper
        paper_idx = int(idx_str)
        if per_paper_content:
            page_map = paper_page_maps.get(paper_idx, {})
        else:
            page_map = _single_page_map

        # Extract ALL page numbers mentioned in page_part (handles p.2, p.2-3, p.2, p.4, etc.)
        page_numbers = [int(x) for x in re.findall(r'\d+', page_part)]
        if not page_numbers:
            continue
        # For ranges like p.2-3, expand to [2, 3]
        expanded_pages: list[int] = []
        for rng in re.findall(r'(\d+)(?:-(\d+))?', page_part):
            start_p = int(rng[0])
            end_p = int(rng[1]) if rng[1] else start_p
            expanded_pages.extend(range(start_p, end_p + 1))
        # Deduplicate while preserving order
        seen: set[int] = set()
        unique_pages: list[int] = []
        for p in expanded_pages:
            if p not in seen:
                seen.add(p)
                unique_pages.append(p)
        # Concatenate content from all referenced pages
        page_content = "\n\n".join(
            page_map.get(p, "") for p in unique_pages if page_map.get(p)
        ).strip()
        if not page_content:
            continue

        # Extract ~100 chars around the citation in the AI response for BM25 query
        citation_text = f"[{idx_str}, {page_part}]"
        pos = ai_response.find(citation_text)
        if pos >= 0:
            start = max(0, pos - 80)
            end = min(len(ai_response), pos + 80)
            query = ai_response[start:end]
        else:
            query = ai_response[:160]

        contexts[key] = {
            "page": unique_pages[0],
            "context": _best_paragraph(page_content, query),
        }

    return contexts if contexts else None


async def _stream_from_openai_compatible(
    messages: List[Dict],
    base_url: str,
    api_key: str,
    model: str,
    source_name: str = "API"
) -> AsyncIterator[str]:
    """
    Stream AI response from an OpenAI-compatible API endpoint.

    Args:
        messages: Chat messages (text or multimodal format)
        base_url: API base URL (e.g., http://127.0.0.1:8000/v1)
        api_key: API key for authentication
        model: Model name to use
        source_name: Name of the source for logging (e.g., "Local vLLM", "OpenRouter")

    Yields:
        SSE formatted response chunks
    """
    logger.info(f"Using {source_name} with model: {model}")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    async with httpx.AsyncClient(timeout=60.0) as client:
        async with client.stream(
            "POST",
            f"{base_url}/chat/completions",
            headers=headers,
            json={
                "model": model,
                "messages": messages,
                "stream": True,
                "temperature": 0.7,
                "max_tokens": 2048,
            }
        ) as response:
            response.raise_for_status()

            last_finish_reason = None
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    data = line[6:]
                    if data == "[DONE]":
                        # Emit context_limit event before [DONE] if output was truncated
                        if last_finish_reason == "length":
                            yield f"data: {json.dumps({'context_limit': True})}\n\n"
                        yield "data: [DONE]\n\n"
                        break
                    try:
                        parsed = json.loads(data)
                        if "choices" in parsed and len(parsed["choices"]) > 0:
                            choice = parsed["choices"][0]
                            delta = choice.get("delta", {})
                            if "content" in delta and delta["content"] is not None:
                                yield f"data: {json.dumps({'content': delta['content']})}\n\n"
                            # Track finish_reason from the last chunk
                            fr = choice.get("finish_reason")
                            if fr:
                                last_finish_reason = fr
                    except json.JSONDecodeError:
                        continue
            # If stream ended without [DONE] but finish_reason was "length"
            if last_finish_reason == "length":
                yield f"data: {json.dumps({'context_limit': True})}\n\n"


async def _check_local_vllm_available(base_url: str, api_key: str = None) -> tuple[bool, str | None]:
    """
    Check if local vLLM server is available and get the first available model.

    Returns:
        Tuple of (is_available, first_model_name)
    """
    try:
        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(f"{base_url}/models", headers=headers)
            if response.status_code == 200:
                data = response.json()
                # Extract first model name for auto-detect
                model_name = None
                if "data" in data and len(data["data"]) > 0:
                    model_name = data["data"][0].get("id")
                return True, model_name
            return False, None
    except Exception:
        return False, None


async def _call_ai_complete(
    messages: List[Dict],
    base_url: str,
    api_key: str,
    model: str
) -> str:
    """
    Call AI completion API (non-streaming) and return the full response content.

    Args:
        messages: Chat messages
        base_url: API base URL
        api_key: API key
        model: Model name

    Returns:
        Full response content as string
    """
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            f"{base_url}/chat/completions",
            headers=headers,
            json={
                "model": model,
                "messages": messages,
                "stream": False,
                "temperature": 0.7,
                "max_tokens": 2048,
            }
        )
        response.raise_for_status()
        data = response.json()

        if "choices" in data and len(data["choices"]) > 0:
            return data["choices"][0]["message"]["content"]
        return ""


async def _execute_exa_search(query: str, exa_api_key: str, num_results: int = 5) -> Dict:
    """
    Execute Exa search and return results.

    Args:
        query: Search query
        exa_api_key: Exa API key
        num_results: Number of results to return

    Returns:
        Dict with query and results array
    """
    headers = {
        "Content-Type": "application/json",
        "x-api-key": exa_api_key
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            "https://api.exa.ai/search",
            headers=headers,
            json={
                "query": query,
                "num_results": num_results,
                "type": "auto",
                "contents": {
                    "text": True
                }
            }
        )
        response.raise_for_status()
        data = response.json()

        # Extract results
        results = []
        for item in data.get("results", []):
            results.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "snippet": item.get("text", "")[:2000]  # Extended snippet for better AI context
            })

        return {
            "query": query,
            "results": results
        }


# ── Client disconnect detection for immediate cancellation ──────────────────

class ClientDisconnectedError(Exception):
    """Raised when the SSE client disconnects during a long-running operation."""
    pass


async def _wait_for_disconnect(request: Request) -> None:
    """Poll ``request.is_disconnected()`` until the client drops the connection."""
    while not await request.is_disconnected():
        await asyncio.sleep(0.25)


async def _run_or_cancel_on_disconnect(coro, request: Request):
    """Race *coro* against client disconnect.

    If *request* is ``None`` (no disconnect detection available), simply
    ``await coro``.  Otherwise, the coroutine is cancelled as soon as the
    SSE client disconnects, and :class:`ClientDisconnectedError` is raised.
    """
    if request is None:
        return await coro

    task = asyncio.ensure_future(coro)
    disconnect_task = asyncio.ensure_future(_wait_for_disconnect(request))

    done, pending = await asyncio.wait(
        {task, disconnect_task},
        return_when=asyncio.FIRST_COMPLETED,
    )

    for p in pending:
        p.cancel()
        try:
            await p
        except (asyncio.CancelledError, Exception):
            pass

    if disconnect_task in done:
        raise ClientDisconnectedError()

    return task.result()


def _deduplicate_search_results(results: List[Dict]) -> List[Dict]:
    """Remove duplicate search results based on title similarity.

    Two results are considered duplicates when their normalised titles share
    a Jaccard word-overlap > 0.6.  The first occurrence is kept.

    This prevents the same paper from appearing N times via different
    mirrors (PubMed, nature.com, arxiv.org, lab pages, …) and ensures
    inline citation indices [N] remain consistent for the AI and the frontend.
    """
    if not results:
        return results

    _bracket_re = re.compile(r'\[.*?\]')
    _word_re = re.compile(r'[a-zA-Z0-9]{3,}')

    def _title_words(title: str) -> set:
        title = _bracket_re.sub('', title)
        return set(w.lower() for w in _word_re.findall(title))

    seen: list[set] = []
    deduplicated: list[Dict] = []

    for result in results:
        words = _title_words(result.get("title", ""))
        if not words:
            deduplicated.append(result)
            continue

        is_dup = False
        for seen_words in seen:
            intersection = words & seen_words
            union = words | seen_words
            if union and len(intersection) / len(union) > 0.6:
                is_dup = True
                break

        if not is_dup:
            seen.append(words)
            deduplicated.append(result)

    return deduplicated


async def stream_ai_response(
    messages: List[Dict],
    api_key: str = None,
    base_url: str = None,
    model: str = None,
    detected_lang: str = "en",
    request: Request = None
) -> AsyncIterator[str]:
    """
    Stream AI response using OpenAI-compatible API with Exa search support.
    Priority: Local vLLM (if enabled and online) > OpenRouter (fallback)

    Supports both text-only and multimodal messages.
    Supports web search via Exa API when AI outputs [WEB_SEARCH] blocks.

    When *request* is provided, long-running operations (AI completion,
    Exa search, PDF download/parse) are raced against client disconnect
    so the stop button cancels them immediately.

    Args:
        messages: Chat messages (text or multimodal format)
        api_key: OpenRouter API key (from global settings or env)
        base_url: OpenRouter base URL (from global settings or env)
        model: Model name (from global settings or env)
        request: FastAPI Request for disconnect detection (optional)
    """
    global_settings = Config.get_global_settings()

    # Local vLLM settings
    local_vllm_enabled = global_settings.get("local_vllm_enabled", False)
    local_vllm_base_url = global_settings.get("local_vllm_base_url", "http://127.0.0.1:8000/v1")
    local_vllm_model = global_settings.get("local_vllm_model", "")
    local_vllm_api_key = global_settings.get("local_vllm_api_key", "")

    # OpenRouter settings (fallback)
    openrouter_api_key = api_key or global_settings.get("openrouter_api_key") or os.environ.get("OPENROUTER_API_KEY")
    openrouter_base_url = base_url or global_settings.get("openrouter_base_url") or os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    openrouter_model = model or global_settings.get("openrouter_model") or os.environ.get("OPENROUTER_MODEL", "qwen/qwen3.5-plus-02-15")

    # Exa search settings
    exa_api_key = global_settings.get("exa_api_key", "")

    # Determine which API to use
    use_local = False
    detected_model = None
    if local_vllm_enabled and local_vllm_base_url:
        logger.info(f"Checking local vLLM server at {local_vllm_base_url}...")
        is_available, detected_model = await _check_local_vllm_available(local_vllm_base_url, local_vllm_api_key)
        if is_available:
            use_local = True
            logger.info("Local vLLM server is online, using local server")
        else:
            logger.warning("Local vLLM server is offline, falling back to OpenRouter")

    # Determine effective API settings
    if use_local:
        effective_model = local_vllm_model or detected_model
        effective_base_url = local_vllm_base_url
        effective_api_key = local_vllm_api_key
        if not effective_model:
            logger.error("No model specified and auto-detect failed, falling back to OpenRouter")
            use_local = False

    if not use_local:
        if not openrouter_api_key:
            # Return error message if no API key is configured
            error_msg = """**AI Configuration Required**

To use the AI assistant, please configure your OpenRouter API key or enable local vLLM server:

1. Click **Settings** in the left sidebar
2. Enter your **OpenRouter API Key** in the configuration form
   - OR enable **Local vLLM Server** and configure the server URL
3. Click **Save Settings**

**Get your API key:** [OpenRouter Console](https://openrouter.ai/keys)

After saving, return here and start chatting!"""

            yield f"data: {json.dumps({'content': error_msg})}\n\n"
            yield "data: [DONE]\n\n"
            return

        effective_model = openrouter_model
        effective_base_url = openrouter_base_url
        effective_api_key = openrouter_api_key

    # Tool loop: up to 3 iterations (web search + read article)
    max_tool_iterations = 3
    current_messages = messages.copy()
    article_pdf_content: str | None = None  # raw PDF markdown (with page markers) for citation context extraction
    _per_paper_pdf_content: dict[int, str] | None = None  # per-paper content for multi-paper follow-ups

    # ── Pre-populate PDF context for follow-up citation support ──────────
    # When conversation history contains [PDF_CONTEXT] blocks (from prior
    # article reads), pre-read the full cached markdown so
    # _extract_citation_contexts can work for follow-up questions.
    # Also prepare reference cards for the frontend's citationMap.
    _followup_reference_cards: list[str] = []
    _followup_pdf_urls = _collect_pdf_urls_from_contexts(messages)
    if _followup_pdf_urls:
        _per_paper_pdf_content = {}
        for idx, url in enumerate(_followup_pdf_urls, 1):
            cached_md = get_cached_markdown(url)
            if cached_md:
                _per_paper_pdf_content[idx] = cached_md
            meta = get_cached_pdf_meta(url) or {}
            title = meta.get('title', 'Unknown')
            src_type = detect_source_type(url)
            is_acad = meta.get('is_academic', False)
            if not is_acad and cached_md:
                is_acad = is_academic_content(cached_md, src_type)
            _followup_reference_cards.append(
                format_reference_card(title, url, src_type, is_acad)
            )
        if _per_paper_pdf_content:
            # Concatenated content for backward compat (single-paper case)
            article_pdf_content = "\n\n".join(_per_paper_pdf_content.values())
            logger.info(
                f"[FollowUp] Pre-populated article_pdf_content from "
                f"{len(_followup_pdf_urls)} cached PDF(s) for citation support"
            )

    # Track the URL currently being processed so we can clean up on cancel.
    _active_pdf_url: str | None = None

    # When True, the next iteration streams the AI response token-by-token
    # instead of buffering it.  Set after article content is injected so the
    # user sees the summary appear progressively.
    _stream_next_iteration = False
    _response_already_streamed = False
    full_response = ""

    for iteration in range(max_tool_iterations):

        # ── Streaming path: yield tokens directly to the client ──────────
        if _stream_next_iteration:
            try:
                streamed_response = ""
                async for chunk in _stream_from_openai_compatible(
                    messages=current_messages,
                    base_url=effective_base_url,
                    api_key=effective_api_key,
                    model=effective_model,
                    source_name="API (streaming)",
                ):
                    # _stream_from_openai_compatible yields SSE lines; forward them
                    if chunk == "data: [DONE]\n\n":
                        break  # we emit our own [DONE] below
                    yield chunk
                    # Buffer for citation extraction
                    if chunk.startswith("data: "):
                        try:
                            d = json.loads(chunk[6:])
                            if "content" in d and d["content"] is not None:
                                streamed_response += d["content"]
                        except (json.JSONDecodeError, KeyError):
                            pass
                full_response = streamed_response
            except ClientDisconnectedError:
                logger.info("Client disconnected during streaming AI completion — stopping")
                return
            except Exception as e:
                logger.error(f"Error in streaming AI completion: {e}")
                error_msg = f"❌ Error: {str(e)}\n\nPlease check your API key and network connection."
                yield f"data: {json.dumps({'content': error_msg})}\n\n"
                yield "data: [DONE]\n\n"
                return

            # Streaming path always breaks after emitting — no tool detection needed
            # because the AI was given article content and asked to summarize.
            # Inject CITATION_CONTEXTS before [DONE] if article was read
            if article_pdf_content:
                try:
                    ctx = _extract_citation_contexts(full_response, article_pdf_content, _per_paper_pdf_content)
                    if ctx:
                        ctx_block = f"[CITATION_CONTEXTS]{json.dumps(ctx, ensure_ascii=False)}[/CITATION_CONTEXTS]"
                        yield f"data: {json.dumps({'content': ctx_block})}\n\n"
                except Exception as e:
                    logger.warning(f"Failed to extract citation contexts: {e}")

            yield "data: [DONE]\n\n"
            return

        # ── Smart streaming: stream tokens, sniff for tool blocks ──────
        # Stream from the API while sniffing the first few tokens to detect
        # tool-call blocks ([WEB_SEARCH], [READ_ARTICLE]).
        # Normal responses are yielded to the client in real-time;
        # tool-call responses are buffered for processing.
        _TOOL_PREFIXES = ("[WEB_SEARCH]", "[READ_ARTICLE]")
        _SNIFF_CHARS = 20  # content chars to accumulate before deciding

        content_so_far = ""
        pending_sse_chunks: list[str] = []
        decided_streaming = False
        is_streaming_to_client = False

        try:
            async for chunk in _stream_from_openai_compatible(
                messages=current_messages,
                base_url=effective_base_url,
                api_key=effective_api_key,
                model=effective_model,
                source_name="API",
            ):
                if chunk == "data: [DONE]\n\n":
                    break

                # Accumulate content for tool detection
                if chunk.startswith("data: "):
                    try:
                        d = json.loads(chunk[6:])
                        if "content" in d and d["content"] is not None:
                            content_so_far += d["content"]
                    except (json.JSONDecodeError, KeyError):
                        pass

                if not decided_streaming:
                    pending_sse_chunks.append(chunk)
                    if len(content_so_far) >= _SNIFF_CHARS:
                        decided_streaming = True
                        stripped = content_so_far.lstrip()
                        if any(stripped.startswith(p) for p in _TOOL_PREFIXES):
                            is_streaming_to_client = False
                        else:
                            is_streaming_to_client = True
                            for pc in pending_sse_chunks:
                                yield pc
                            pending_sse_chunks = []
                elif is_streaming_to_client:
                    yield chunk
                # else: buffering for tool processing

        except ClientDisconnectedError:
            logger.info("Client disconnected during AI completion — stopping")
            return
        except Exception as e:
            logger.error(f"Error in AI completion: {e}")
            error_msg = f"❌ Error: {str(e)}\n\nPlease check your API key and network connection."
            yield f"data: {json.dumps({'content': error_msg})}\n\n"
            yield "data: [DONE]\n\n"
            return

        # Short responses that never crossed the sniff threshold
        if not decided_streaming:
            stripped = content_so_far.lstrip()
            if any(stripped.startswith(p) for p in _TOOL_PREFIXES):
                is_streaming_to_client = False
            else:
                is_streaming_to_client = True
                for pc in pending_sse_chunks:
                    yield pc
                pending_sse_chunks = []

        full_response = content_so_far

        # Mark if response was already streamed to client.
        # Do NOT break here — always continue to tool detection below.
        # [WEB_SEARCH] / [READ_ARTICLE] blocks may appear after normal text;
        # the frontend strips them from display (AssistantMessage.tsx L496-498).
        if is_streaming_to_client:
            _response_already_streamed = True

        # Check if AI requested web search
        search_match = json.loads('null')
        try:
            import re
            pattern = r'\[WEB_SEARCH\](.*?)\[/WEB_SEARCH\]'
            match = re.search(pattern, full_response, re.DOTALL)
            if match:
                search_match = json.loads(match.group(1).strip())
        except:
            search_match = None

        if search_match and exa_api_key:
            # ── Handle [WEB_SEARCH] ──
            query = search_match.get("query", "")
            reason = search_match.get("reason", "")
            ai_num_results = min(int(search_match.get("num_results", 5)), 10)
            if ai_num_results < 1:
                ai_num_results = 5

            # Emit search status to frontend
            search_status = json.dumps({"query": query, "reason": reason})
            yield f"data: {json.dumps({'content': f'[SEARCH_STATUS]{search_status}[/SEARCH_STATUS]'})}\n\n"

            # Execute Exa search
            try:
                search_results = await _run_or_cancel_on_disconnect(
                    _execute_exa_search(query, exa_api_key, num_results=ai_num_results),
                    request,
                )

                # Deduplicate results — the same paper often appears via
                # multiple mirrors (PubMed, nature.com, arxiv, lab pages…).
                search_results["results"] = _deduplicate_search_results(search_results["results"])

                # Emit web search results to frontend so UI can display completion status
                web_search_result_block = json.dumps(search_results)
                yield f"data: {json.dumps({'content': f'[WEB_SEARCH_RESULT]{web_search_result_block}[/WEB_SEARCH_RESULT]'})}\n\n"

                # Format search results for AI — include source type hints
                from .chat_pdf import _ACADEMIC_SOURCE_TYPES
                results_text = f"\n\n[WEB_SEARCH_RESULT]\n{json.dumps(search_results)}\n[/WEB_SEARCH_RESULT]\n\n"
                results_text += "Search results:\n"
                for idx, result in enumerate(search_results["results"], 1):
                    r_url = result.get("url", "")
                    src_type = detect_source_type(r_url)
                    is_academic_src = src_type in _ACADEMIC_SOURCE_TYPES
                    ref_type = "paper" if is_academic_src else "webpage"
                    results_text += (
                        f"{idx}. {result['title']}\n"
                        f"   URL: {r_url}\n"
                        f"   Source: {src_type} (reference type: {ref_type})\n"
                        f"   {result['snippet']}\n\n"
                    )

                # Add search results to messages for next AI iteration
                current_messages = current_messages + [
                    {"role": "assistant", "content": full_response},
                    {"role": "user", "content": (
                        f"Here are the search results for '{query}':\n{results_text}\n\n"
                        "NOTE: These results contain SNIPPETS (partial text), NOT full articles. "
                        "Synthesize the information, cite sources using inline [N] references matching the result numbers above, "
                        "and generate [REFERENCE] blocks. "
                        "If the user wants to read a full article, use the [READ_ARTICLE] tool.\n"
                        "IMPORTANT: Each result above includes a 'reference type' hint (paper or webpage). "
                        "Use `type: paper` ONLY for academic papers/journals; use `type: webpage` for GitHub repos, blogs, documentation, HuggingFace, and all other non-academic sources."
                    )}
                ]
                continue

            except ClientDisconnectedError:
                logger.info("Client disconnected during Exa search — stopping")
                return
            except Exception as e:
                logger.error(f"Exa search error: {e}")
                break

        # ── Check for [READ_ARTICLE] ──
        read_article_match = None
        try:
            ra_pattern = r'\[READ_ARTICLE\](.*?)\[/READ_ARTICLE\]'
            ra_match = re.search(ra_pattern, full_response, re.DOTALL)
            if ra_match:
                read_article_match = json.loads(ra_match.group(1).strip())
        except Exception:
            read_article_match = None

        if read_article_match:
            article_url = read_article_match.get("url", "")
            article_title = read_article_match.get("title", "Unknown")
            article_index = read_article_match.get("index")  # search result number

            if not article_url:
                break

            # Emit PDF_PARSE_STATUS: "downloading" (uncached) or "parsing" (cached)
            has_cache = get_cached_markdown(article_url) is not None
            initial_status = "parsing" if has_cache else "downloading"
            pdf_status = {"url": article_url, "title": article_title, "status": initial_status}
            yield f"data: {json.dumps({'content': f'[PDF_PARSE_STATUS]{json.dumps(pdf_status)}[/PDF_PARSE_STATUS]'})}\n\n"

            try:
                _active_pdf_url = article_url
                pdf_result = await _run_or_cancel_on_disconnect(
                    process_pdf_url(
                        url=article_url,
                        title=article_title,
                        base_url=effective_base_url,
                        api_key=effective_api_key,
                        model=effective_model,
                        use_cache=True
                    ),
                    request,
                )
                _active_pdf_url = None

                # For uncached PDFs: transition downloading → parsing → completed
                if not has_cache and pdf_result.get("success"):
                    pdf_status = {"url": article_url, "title": article_title, "status": "parsing"}
                    yield f"data: {json.dumps({'content': f'[PDF_PARSE_STATUS]{json.dumps(pdf_status)}[/PDF_PARSE_STATUS]'})}\n\n"

                # Emit PDF_PARSE_STATUS: completed or error
                if pdf_result.get("success"):
                    pdf_status = {
                        "url": article_url, "title": article_title,
                        "status": "completed", "from_cache": pdf_result.get("from_cache", False)
                    }
                else:
                    pdf_status = {
                        "url": article_url, "title": article_title,
                        "status": pdf_result.get("error", "unknown_error")
                    }
                yield f"data: {json.dumps({'content': f'[PDF_PARSE_STATUS]{json.dumps(pdf_status)}[/PDF_PARSE_STATUS]'})}\n\n"

                if pdf_result.get("success"):
                    # Build article content for AI
                    content = pdf_result.get("pdf_content") or pdf_result.get("summary") or ""
                    # Save raw PDF content (with page markers) for citation context extraction
                    article_pdf_content = content
                    # Head + tail truncation for long articles
                    _PDF_MAX_CHARS = 40000
                    _PDF_HEAD_CHARS = 28000
                    _PDF_TAIL_CHARS = 12000
                    if len(content) > _PDF_MAX_CHARS:
                        head = content[:_PDF_HEAD_CHARS]
                        tail = content[-_PDF_TAIL_CHARS:]
                        content = head + "\n\n...[middle pages omitted for length]...\n\n" + tail

                    # Build metadata
                    page_count = pdf_result.get("page_count")
                    parse_method = pdf_result.get("parse_method", "pymupdf")
                    quality_label = (
                        "High-precision (MinerU — includes tables, formulas, images)"
                        if parse_method == "mineru"
                        else "Fast (PyMuPDF — text only, images not yet extracted)"
                    )
                    page_info = f"{page_count} pages" if page_count else "page count unknown"
                    is_academic = pdf_result.get("is_academic", False)
                    label = "Paper" if is_academic else "Doc"
                    ref_label = f"[{label}]" if not article_index else f"[{article_index}]"

                    article_parts = [
                        f"### {ref_label} {article_title}\n"
                        f"- **URL**: {article_url}\n"
                        f"- **Total pages**: {page_info}\n"
                        f"- **Parse quality**: {quality_label}\n",
                        content,
                    ]
                    if pdf_result.get("reference_card"):
                        article_parts.append(pdf_result["reference_card"])

                    article_text = "\n".join(article_parts)

                    # Emit PDF context for persistence
                    yield f"data: {json.dumps({'pdf_context': article_text})}\n\n"

                    # Inject article content into conversation
                    read_prompt = _READ_ARTICLE_PROMPTS.get(detected_lang, _READ_ARTICLE_PROMPTS["en"])
                    current_messages = current_messages + [
                        {"role": "assistant", "content": full_response},
                        {"role": "user", "content": f"{read_prompt}\n\n{article_text}"}
                    ]
                    _stream_next_iteration = True
                    continue
                else:
                    # PDF failed — let AI know and break to stream response
                    error_detail = pdf_result.get("error_detail") or pdf_result.get("error") or "unknown error"
                    current_messages = current_messages + [
                        {"role": "assistant", "content": full_response},
                        {"role": "user", "content": (
                            f"The article '{article_title}' ({article_url}) could not be retrieved. "
                            f"Error: {error_detail}\n\n"
                            "Please inform the user about this issue and suggest alternatives."
                        )}
                    ]
                    _stream_next_iteration = True
                    continue

            except ClientDisconnectedError:
                logger.info(f"Client disconnected during PDF processing ({article_url}) — cleaning up")
                if _active_pdf_url:
                    from .chat_pdf import invalidate_pdf_cache
                    invalidate_pdf_cache(_active_pdf_url)
                return
            except Exception as e:
                logger.error(f"READ_ARTICLE error for {article_url}: {e}")
                pdf_status = {"url": article_url, "title": article_title, "status": "download_failed"}
                yield f"data: {json.dumps({'content': f'[PDF_PARSE_STATUS]{json.dumps(pdf_status)}[/PDF_PARSE_STATUS]'})}\n\n"
                # Add error context so the next AI call can inform the user
                current_messages = current_messages + [
                    {"role": "assistant", "content": full_response},
                    {"role": "user", "content": (
                        f"The article '{article_title}' ({article_url}) could not be downloaded. "
                        f"Error: {e}\n\n"
                        "Please inform the user that the article download failed and suggest alternatives "
                        "(e.g. trying another article, or accessing the URL directly)."
                    )}
                ]
                _stream_next_iteration = True
                continue

        # No tool requested — break out of loop
        break

    # ── Emit final AI response ──
    final_response_text = full_response or ""

    if not _response_already_streamed and final_response_text:
        # Buffered response (tool-call iteration that fell through) — emit now
        _CHUNK_SIZE = 80
        for i in range(0, len(final_response_text), _CHUNK_SIZE):
            yield f"data: {json.dumps({'content': final_response_text[i:i+_CHUNK_SIZE]})}\n\n"

    # Inject CITATION_CONTEXTS before [DONE] if article was read
    if article_pdf_content and final_response_text:
        try:
            ctx = _extract_citation_contexts(final_response_text, article_pdf_content, _per_paper_pdf_content)
            if ctx:
                ctx_block = f"[CITATION_CONTEXTS]{json.dumps(ctx, ensure_ascii=False)}[/CITATION_CONTEXTS]"
                yield f"data: {json.dumps({'content': ctx_block})}\n\n"
        except Exception as e:
            logger.warning(f"Failed to extract citation contexts: {e}")

    # Emit reference cards for follow-up messages so frontend can build
    # citationMap with paper title/URL for InlineCitation tooltips.
    if _followup_reference_cards:
        ref_block = "\n".join(_followup_reference_cards)
        yield f"data: {json.dumps({'content': ref_block})}\n\n"

    yield "data: [DONE]\n\n"


@router.post("/conversations")
async def create_conversation(
    req: CreateConversationRequest,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Create a new conversation for the current user"""
    conversation_id = f"conv_{uuid.uuid4().hex[:16]}"
    conversation_data = {
        "conversation_id": conversation_id,
        "user_id": str(user.id),  # Use authenticated user's ID
        "title": req.title or "New Conversation",
    }
    conversation = await ChatRepository.create_conversation(db, conversation_data)
    await db.commit()
    return conversation.to_dict()


@router.get("/conversations")
async def list_conversations(
    skip: int = 0,
    limit: int = 50,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """List all conversations for the current user"""
    user_id = str(user.id)
    conversations = await ChatRepository.get_user_conversations(db, user_id, skip, limit)
    total = await ChatRepository.count_user_conversations(db, user_id)
    return {"items": [conv.to_dict() for conv in conversations], "total": total}


@router.get("/conversations/{conversation_id}")
async def get_conversation(
    conversation_id: str,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Get a conversation with all messages. Users can only view their own conversations."""
    conversation = await ChatRepository.get_conversation(db, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Check ownership
    if not check_data_ownership(conversation.user_id, user):
        raise HTTPException(status_code=403, detail="You don't have permission to view this conversation")

    # Sort messages by id to ensure chronological order (defense-in-depth)
    sorted_messages = sorted(conversation.messages, key=lambda m: m.id)
    return {
        **conversation.to_dict(),
        "messages": [msg.to_dict() for msg in sorted_messages]
    }


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Delete a conversation. Users can only delete their own conversations."""
    conversation = await ChatRepository.get_conversation(db, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Check ownership
    if not check_data_ownership(conversation.user_id, user):
        raise HTTPException(status_code=403, detail="You don't have permission to delete this conversation")

    success = await ChatRepository.delete_conversation(db, conversation_id)
    if not success:
        raise HTTPException(status_code=404, detail="Conversation not found")
    await db.commit()
    return {"message": "Conversation deleted successfully"}


@router.patch("/conversations/{conversation_id}/messages/{message_id}")
async def update_message(
    conversation_id: str,
    message_id: int,
    req: UpdateMessageRequest,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Update a message's content. Used to persist task submission status."""
    # First check conversation exists and user owns it
    conversation = await ChatRepository.get_conversation(db, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    if not check_data_ownership(conversation.user_id, user):
        raise HTTPException(status_code=403, detail="You don't have permission to update this message")

    # Update the message
    message = await ChatRepository.update_message(db, message_id, req.content)
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")

    await db.commit()
    return message.to_dict()


@router.delete("/conversations/{conversation_id}/messages/{message_id}")
async def delete_messages_from(
    conversation_id: str,
    message_id: int,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Delete a message and all subsequent messages in a conversation.
    Used for conversation branching - allows users to delete from a point and restart.
    Users can only delete messages in their own conversations.
    """
    # First check conversation exists and user owns it
    conversation = await ChatRepository.get_conversation(db, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    if not check_data_ownership(conversation.user_id, user):
        raise HTTPException(status_code=403, detail="You don't have permission to delete messages in this conversation")

    # Delete the message and all subsequent messages
    deleted_count = await ChatRepository.delete_messages_from_id(db, conversation_id, message_id)
    if deleted_count == 0:
        raise HTTPException(status_code=404, detail="Message not found")

    await db.commit()
    return {"message": f"Deleted {deleted_count} message(s)", "deleted_count": deleted_count}


@router.post("/conversations/{conversation_id}/messages")
async def add_message(
    conversation_id: str,
    req: AddMessageRequest,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Add a message to a conversation. Used to persist task submission success messages."""
    # First check conversation exists and user owns it
    conversation = await ChatRepository.get_conversation(db, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    if not check_data_ownership(conversation.user_id, user):
        raise HTTPException(status_code=403, detail="You don't have permission to add messages to this conversation")

    # Add the message
    message_data = {
        "conversation_id": conversation_id,
        "role": req.role,
        "content": req.content,
    }
    message = await ChatRepository.add_message(db, message_data)
    await db.commit()
    return message.to_dict()


@router.post("/chat")
async def chat_with_ai(
    req: ChatRequest,
    request: Request,
    user: User = Depends(current_active_user),
    user_id_filter: Optional[str] = Depends(get_user_id_filter),
    db: AsyncSession = Depends(get_db)
):
    """
    Chat with AI assistant (streaming).
    Returns Server-Sent Events (SSE) stream.

    If conversation_id is provided, messages will be persisted to database.

    AI configuration is read from HTTP headers:
    - X-OpenRouter-API-Key: OpenRouter API key
    - X-OpenRouter-Base-URL: OpenRouter base URL
    - X-OpenRouter-Model: Model name
    - X-Language: Frontend i18n language code (e.g. en-US, zh-CN, zh-HK)
    - X-Timezone: IANA timezone string from the browser (e.g. Asia/Shanghai)
    """
    # Get AI configuration from request headers
    api_key = request.headers.get("X-OpenRouter-API-Key")
    base_url = request.headers.get("X-OpenRouter-Base-URL")
    model = request.headers.get("X-OpenRouter-Model")

    # Read the frontend i18n language preference. Maps frontend codes (en-US / zh-CN / zh-HK)
    # to the backend prompt language codes (en / zh_CN / zh_HK).
    _LANG_HEADER_MAP = {
        "en-US": "en",
        "zh-CN": "zh_CN",
        "zh-HK": "zh_HK",
    }
    ui_lang_header = request.headers.get("X-Language", "")
    ui_lang = _LANG_HEADER_MAP.get(ui_lang_header) if ui_lang_header else None

    # Resolve current datetime in the user's browser timezone (falls back to UTC).
    tz_header = request.headers.get("X-Timezone", "").strip()
    try:
        user_tz = ZoneInfo(tz_header) if tz_header else ZoneInfo("UTC")
    except ZoneInfoNotFoundError:
        user_tz = ZoneInfo("UTC")
    current_datetime = datetime.now(user_tz).strftime("%Y-%m-%d %H:%M:%S %Z")

    # Fetch user's temporary dataset permissions (for non-admin users)
    # Need this first to pass elevated_dataset_ids to get_chat_context_stats
    temp_permissions = []
    elevated_dataset_ids = None
    if not user.is_admin():
        temp_permissions = await DatasetPermissionRepository.get_valid_by_user(db, str(user.id))
        if temp_permissions:
            elevated_dataset_ids = [perm.dataset_id for perm in temp_permissions]

    # Fetch user's data overview for context (single optimized query)
    # Pass elevated_dataset_ids so that temporarily authorized datasets are included
    stats = await WSIRepository.get_chat_context_stats(
        db, user_id=user_id_filter, elevated_dataset_ids=elevated_dataset_ids
    )

    # Fetch user's trained models
    trained_models = await TrainedModelRepository.get_all(db, limit=100, offset=0, user_id=user_id_filter)

    # Fetch user's training tasks (recent 10 for context, with counts)
    training_tasks = await TrainingTaskRepository.get_all(db, limit=10, offset=0, user_id=user_id_filter)
    training_tasks_stats = await TrainingTaskRepository.get_status_counts(db, user_id=user_id_filter)

    # Fetch user's inference tasks (recent 10 for context, with counts)
    inference_tasks = await AITaskRepository.get_recent(db, limit=10, user_id=user_id_filter)
    inference_tasks_stats = await AITaskRepository.get_status_counts(db, user_id=user_id_filter)

    # Format user data context for System Prompt
    wsi_count = stats["total_count"]
    stats_datasets = stats["datasets"]  # Keep original reference; `datasets` may be overwritten later
    datasets = stats_datasets
    data_type_dist = stats["data_types"]

    # Auxiliary lookup dict built during the dataset loop (used later for model compatibility)
    available_extractors_per_dataset: dict = {}  # dataset_id -> list[str]

    # Format datasets with detailed info (data_type and labels per dataset)
    # Each dataset has its own labels and survival data - do NOT show global labels to avoid confusion
    # Datasets are now marked with access_type: "own" (user's own) or "elevated" (temporary permission)
    if datasets:
        datasets_details = []
        for d in datasets:
            ds_name = d['dataset_name']
            ds_id = d.get('dataset_id', 'unknown')
            ds_count = d['file_count']
            ds_type = d.get('data_type', 'unknown')
            ds_labels = d.get('labels', {})
            ds_survival = d.get('survival_count', 0)
            ds_event_status = d.get('event_status', {})
            ds_has_splits = d.get('has_predefined_splits', False)
            ds_access_type = d.get('access_type', 'own')

            # Build info parts
            labels_str = ", ".join([f"{lbl}({cnt})" for lbl, cnt in ds_labels.items()]) if ds_labels else "none"

            # Format survival data with event_status distribution
            if ds_survival > 0 and ds_event_status:
                event_count = ds_event_status.get('event', 0)
                censored_count = ds_event_status.get('censored', 0)
                survival_str = f", survival_data={ds_survival} (event={event_count}, censored={censored_count})"
            elif ds_survival > 0:
                survival_str = f", survival_data={ds_survival}"
            else:
                survival_str = ""

            splits_str = ", has_predefined_splits=true" if ds_has_splits else ""

            # Determine supported task types based on data
            task_types = []
            if ds_labels:
                task_types.append("classification")
            if ds_survival > 0:
                task_types.append("survival")
            task_types_str = f", supported_tasks=[{', '.join(task_types)}]" if task_types else ""

            # For WSI datasets, scan feature cache to find available extractors (for external validation compatibility)
            available_extractors_str = ""
            if ds_type == "wsi":
                # Get WSI IDs for this dataset
                wsi_ids = await DatasetRepository.get_wsi_ids(db, ds_id)
                if wsi_ids:
                    first_wsi_id = wsi_ids[0]
                    features_root = Config.get_uploads_dir() / "features"
                    available_extractors = []
                    if features_root.exists():
                        for extractor_dir in features_root.iterdir():
                            if extractor_dir.is_dir():
                                for params_hash_dir in extractor_dir.iterdir():
                                    if params_hash_dir.is_dir():
                                        feat_file = params_hash_dir / f"{first_wsi_id}.pt"
                                        if feat_file.exists():
                                            available_extractors.append(extractor_dir.name)
                                            break  # Found for this extractor, move to next
                    if available_extractors:
                        available_extractors_str = f", available_extractors=[{', '.join(available_extractors)}]"
                    # Store for model compatibility lookup
                    available_extractors_per_dataset[ds_id] = available_extractors

            # Add access type marker for elevated (temporary permission) datasets
            access_marker = " [ELEVATED ACCESS - temporary permission]" if ds_access_type == "elevated" else ""

            datasets_details.append(f"  - {ds_name} (dataset_id={ds_id}){access_marker}: {ds_count} files, type={ds_type}, labels=[{labels_str}]{survival_str}{splits_str}{task_types_str}{available_extractors_str}")
        datasets_list = "\n".join(datasets_details)
    else:
        datasets_list = "  None"

    # Format data type distribution (overall summary only)
    wsi_count_val = data_type_dist.get("wsi", 0)
    patch_count_val = data_type_dist.get("patch", 0)
    if wsi_count_val > 0 and patch_count_val > 0:
        data_types_info = f"WSI: {wsi_count_val}, Patches: {patch_count_val}"
    elif wsi_count_val > 0:
        data_types_info = f"WSI only: {wsi_count_val}"
    elif patch_count_val > 0:
        data_types_info = f"Patches only: {patch_count_val}"
    else:
        data_types_info = "None"

    # Format trained models info (with detailed info for external validation)
    # Embedding dimension mapping for feature extractors
    EXTRACTOR_EMBED_DIM = {
        "resnet50": 2048, "vit_l_16": 1024, "conch": 512, "uni": 1024, "uni2": 1536,
        "virchow": 1280, "virchow2": 1280, "plip": 512, "phikon": 1024, "phikon2": 1024,
        "patho_clip": 512, "openmidnight": 1536, "conch15": 512, "H-Optimus-1": 1536,
        "H-Optimus-0": 1536, "mSTAR": 1024, "GPFM": 1024,
    }

    if trained_models:
        models_details = []
        # Batch query all training tasks to get detailed info with eager loading
        task_ids = list(set(m.task_id for m in trained_models if m.task_id))
        training_tasks_map = {}
        # task_id -> set of dataset_ids actually used in training (via TrainingTaskWSI → WSISlide)
        training_dataset_ids_map: Dict[str, set] = {}
        if task_ids:
            from sqlalchemy import select
            # Eager load data_group (for data_type / task_type), no need to load datasets relation
            stmt = select(TrainingTask).options(
                selectinload(TrainingTask.data_group)
            ).where(TrainingTask.task_id.in_(task_ids))
            result = await db.execute(stmt)
            tasks = result.scalars().all()
            for task in tasks:
                training_tasks_map[task.task_id] = task

            # Batch-query the actual dataset_ids used in each training task
            # Join TrainingTaskWSI → WSISlide to get the real training datasets
            ds_rows = await db.execute(
                select(TrainingTaskWSI.task_id, WSISlide.dataset_id)
                .join(WSISlide, TrainingTaskWSI.wsi_id == WSISlide.wsi_id)
                .where(
                    TrainingTaskWSI.task_id.in_(task_ids),
                    WSISlide.dataset_id.isnot(None)
                )
                .distinct()
            )
            for row in ds_rows.all():
                tid, did = row[0], row[1]
                if tid not in training_dataset_ids_map:
                    training_dataset_ids_map[tid] = set()
                training_dataset_ids_map[tid].add(did)

        for m in trained_models:
            model_name = m.model_name
            model_id = m.model_id
            model_classes = m.classes or []
            model_task_id = m.task_id
            model_feature_extractor = m.feature_extractor or "unknown"
            classes_str = ", ".join(model_classes) if model_classes else "none"

            # Get data_type and task_type from training task's DataGroup
            training_task = training_tasks_map.get(model_task_id)
            # Actual dataset_ids this model was trained on (from WSI associations)
            training_dataset_ids = training_dataset_ids_map.get(model_task_id, set())
            if training_task and training_task.data_group:
                data_type = training_task.data_group.data_type
                task_type = training_task.data_group.task_type
            else:
                data_type = "unknown"
                task_type = "unknown"
            # Resolve training dataset names using the stats_datasets lookup
            dataset_id_to_name = {ds["dataset_id"]: ds["dataset_name"] for ds in stats_datasets}
            training_dataset_names = [
                dataset_id_to_name[did] for did in training_dataset_ids if did in dataset_id_to_name
            ]

            # Get embedding dimension for WSI models
            embed_dim = EXTRACTOR_EMBED_DIM.get(model_feature_extractor, 0)

            # -----------------------------------------------------------------------
            # Pre-compute compatible datasets for external validation at API level
            # Rules (mirrors frontend externalValidationUtils.ts isDatasetCompatible):
            #   1. data_type must match
            #   2. task_type must match (inferred from dataset's labels/survival_count)
            #   3. For classification: model classes must be a subset of dataset labels
            #   4. For WSI: dataset must have features extracted with the same extractor
            #   5. Exclude the dataset this model was trained on
            # -----------------------------------------------------------------------
            compatible_datasets = []
            if data_type != "unknown" and task_type != "unknown":
                model_classes_set = set(model_classes)
                for ds in stats_datasets:
                    cand_id = ds["dataset_id"]
                    cand_type = ds.get("data_type", "unknown")
                    cand_labels = ds.get("labels", {})
                    cand_survival = ds.get("survival_count", 0)
                    cand_name = ds["dataset_name"]

                    # Rule 5: skip any dataset this model was actually trained on
                    if cand_id in training_dataset_ids:
                        continue

                    # Rule 1: data_type must match
                    if cand_type != data_type:
                        continue

                    # Rule 2 + 3: task_type and label compatibility
                    if task_type == "classification":
                        # Dataset must support classification (has labels)
                        if not cand_labels:
                            continue
                        # Model classes must be a subset of the dataset's label set
                        if model_classes_set and not model_classes_set.issubset(set(cand_labels.keys())):
                            continue
                    elif task_type == "survival":
                        # Dataset must have survival data
                        if cand_survival == 0:
                            continue

                    # Rule 4: for WSI, feature extractor must be available in the dataset
                    if data_type == "wsi" and model_feature_extractor != "unknown":
                        ds_extractors = available_extractors_per_dataset.get(cand_id, [])
                        if model_feature_extractor not in ds_extractors:
                            continue

                    compatible_datasets.append(f"{cand_name} (dataset_id={cand_id})")

            # Build model info string
            info_parts = [
                f"id={model_id}",
                f"task_type={task_type}",
                f"data_type={data_type}",
            ]

            # Add classes for classification models
            if model_classes:
                info_parts.append(f"classes=[{classes_str}]")

            # Add feature extractor info for WSI models
            if data_type == "wsi" and model_feature_extractor != "unknown":
                info_parts.append(f"feature_extractor={model_feature_extractor}")
                if embed_dim > 0:
                    info_parts.append(f"embedding_dim={embed_dim}")

            # Add training dataset names for reference
            if training_dataset_names:
                info_parts.append(f"trained_on_dataset={', '.join(training_dataset_names)}")

            info_parts.append(f"trained_on_task={model_task_id}")

            # Add pre-computed compatible datasets list (API-level filtering)
            if compatible_datasets:
                compat_str = ", ".join(compatible_datasets)
                info_parts.append(f"compatible_validation_datasets=[{compat_str}]")
            else:
                info_parts.append("compatible_validation_datasets=[]")

            models_details.append(f"  - {model_name} ({', '.join(info_parts)})")

        models_list = "\n".join(models_details)
        models_count = len(trained_models)
    else:
        models_list = "  None - user needs to train a model first"
        models_count = 0

    # Format user permissions info
    user_role = user.role  # "admin", "pathologist", or "guest"
    can_use_gpu_base = user.can_use_gpu()  # True for admin/pathologist, False for guest

    # Format temporary permissions if any (for non-admin users)
    # These are datasets owned by OTHER users that this user has been granted access to
    if temp_permissions:
        # Batch query all datasets at once to avoid N+1 query problem
        dataset_ids = [perm.dataset_id for perm in temp_permissions]
        datasets = await DatasetRepository.get_by_ids(db, dataset_ids)
        dataset_map = {d.dataset_id: d for d in datasets}

        temp_perms_details = []
        for perm in temp_permissions:
            dataset = dataset_map.get(perm.dataset_id)
            dataset_name = dataset.name if dataset else "Unknown Dataset"

            # Format expiration info
            expires_info = ""
            if perm.expires_at:
                expires_info = f", expires: {perm.expires_at.strftime('%Y-%m-%d %H:%M UTC')}"
            else:
                expires_info = ", no expiration"

            temp_perms_details.append(f"  - **{dataset_name}** (dataset_id={perm.dataset_id}): {perm.permission_level} access{expires_info}")
        temp_perms_list = "\n".join(temp_perms_details)
    else:
        temp_perms_list = "  None"

    # Get GPU status for system prompt
    gpu_summary = get_gpu_summary_for_prompt()

    # Format training tasks info (recent 10 tasks with summary)
    training_tasks_total = training_tasks_stats.get("total", 0)
    training_tasks_completed = training_tasks_stats.get("completed", 0)
    training_tasks_running = training_tasks_stats.get("running", 0)
    training_tasks_failed = training_tasks_stats.get("failed", 0)

    if training_tasks:
        training_tasks_details = []
        for t in training_tasks:
            created_str = t.created_at.strftime("%Y-%m-%d %H:%M") if t.created_at else "unknown"
            # Get task_type and data_type from DataGroup relationship
            if t.data_group:
                task_type = t.data_group.task_type
                data_type = t.data_group.data_type
            else:
                task_type = "unknown"
                data_type = "unknown"
            training_tasks_details.append(
                f"  - [{t.status.upper()}] {t.task_name} (id={t.task_id}): {task_type}, {data_type}, created={created_str}"
            )
        if training_tasks_total > 10:
            training_tasks_details.append(f"  ... and {training_tasks_total - 10} more tasks")
        training_tasks_list = "\n".join(training_tasks_details)
    else:
        training_tasks_list = "  None - user has not created any training tasks yet"

    # Format inference tasks info (recent 10 tasks with summary)
    inference_tasks_total = inference_tasks_stats.get("total", 0)
    inference_tasks_completed = inference_tasks_stats.get("completed", 0)
    inference_tasks_running = inference_tasks_stats.get("running", 0)

    if inference_tasks:
        inference_tasks_details = []
        for t in inference_tasks:
            created_str = t.created_at.strftime("%Y-%m-%d %H:%M") if t.created_at else "unknown"
            inference_tasks_details.append(
                f"  - [{t.status.upper()}] {t.task_type} on {t.wsi_id} (id={t.task_id}): created={created_str}"
            )
        if inference_tasks_total > 10:
            inference_tasks_details.append(f"  ... and {inference_tasks_total - 10} more tasks")
        inference_tasks_list = "\n".join(inference_tasks_details)
    else:
        inference_tasks_list = "  None - user has not run any inference tasks yet"

    # Format user data context using template
    user_data_context = format_user_data_context(
        wsi_count=wsi_count,
        data_types_info=data_types_info,
        datasets_list=datasets_list,
        models_count=models_count,
        models_list=models_list,
        training_tasks_total=training_tasks_total,
        training_tasks_completed=training_tasks_completed,
        training_tasks_running=training_tasks_running,
        training_tasks_failed=training_tasks_failed,
        training_tasks_list=training_tasks_list,
        inference_tasks_total=inference_tasks_total,
        inference_tasks_completed=inference_tasks_completed,
        inference_tasks_running=inference_tasks_running,
        inference_tasks_list=inference_tasks_list,
        gpu_summary=gpu_summary,
        user_role=user_role,
        is_admin=user.is_admin(),
        can_use_gpu_base=can_use_gpu_base,
        temp_perms_list=temp_perms_list,
        current_datetime=current_datetime,
    )

    # Log the user_data_context for debugging
    # logger.info(f"[Chat] User data context for agent:\n{user_data_context}")

    # Determine language for system prompt.
    # Priority: explicit X-Language header (user's i18n setting) > content-based heuristic.
    if ui_lang:
        detected_lang = ui_lang
    else:
        # Fallback: infer from the last user message content
        detected_lang = "en"
        for msg in reversed(req.messages):
            if msg.get("role") == "user":
                user_text = extract_text_from_content(msg.get("content", ""))
                detected_lang = detect_language(user_text)
                break

    # Add system prompt if not present
    messages = req.messages.copy()
    if not messages or messages[0].get("role") != "system":
        # Load language-specific system prompt from template file
        base_system_prompt = get_chat_system_prompt(detected_lang)

        system_prompt = {
            "role": "system",
            "content": base_system_prompt + user_data_context
        }
        messages.insert(0, system_prompt)

    # If conversation_id is provided, save user message to database
    # For multimodal messages, only save the text content
    if req.conversation_id and len(req.messages) > 0:
        last_user_message = req.messages[-1]
        if last_user_message.get("role") == "user":
            # Extract text content (handles both string and multimodal format)
            content = last_user_message.get("content", "")
            text_content = extract_text_from_content(content)
            message_data = {
                "conversation_id": req.conversation_id,
                "role": "user",
                "content": text_content,
            }
            await ChatRepository.add_message(db, message_data)
            await db.commit()

    # ── BM25-enhanced PDF context for follow-up questions ────────────────────
    # Collect ALL [PDF_CONTEXT] blocks from conversation history, merge them
    # into a single unified view with global paper numbering, then replace all
    # original blocks with the merged version.
    all_pdf_urls = _collect_pdf_urls_from_contexts(messages)

    user_query_for_bm25 = ""
    if all_pdf_urls:
        for msg in reversed(messages):
            if msg.get("role") == "user":
                txt = extract_text_from_content(msg.get("content", ""))
                if not txt.strip().startswith("[PDF_CONTEXT]"):
                    user_query_for_bm25 = txt
                    break

    if user_query_for_bm25 and all_pdf_urls:
        merged_ctx = _build_merged_pdf_context(all_pdf_urls, user_query_for_bm25, detected_lang)
        merged_content = f"[PDF_CONTEXT]\n{merged_ctx}\n[/PDF_CONTEXT]"

        # Remove all old [PDF_CONTEXT] messages
        _pdf_ctx_re = re.compile(r'\[PDF_CONTEXT\]\n?[\s\S]*?\n?\[/PDF_CONTEXT\]')
        first_ctx_idx: int | None = None
        indices_to_remove: list[int] = []
        for i, msg in enumerate(messages):
            if msg.get("role") != "user":
                continue
            raw = extract_text_from_content(msg.get("content", ""))
            if _pdf_ctx_re.search(raw):
                if first_ctx_idx is None:
                    first_ctx_idx = i
                else:
                    indices_to_remove.append(i)

        # Replace the first block with the merged version; remove the rest
        if first_ctx_idx is not None:
            messages[first_ctx_idx] = {
                **messages[first_ctx_idx],
                "content": merged_content,
            }
            for idx in reversed(indices_to_remove):
                messages.pop(idx)

        logger.info(
            f"[BM25] Merged {len(all_pdf_urls)} documents into unified PDF context "
            f"for follow-up query: '{user_query_for_bm25[:80]}...'"
        )

    # Stream AI response
    def _strip_internal_status_blocks(content: str) -> str:
        """Strip frontend-only status blocks before saving to DB.

        [SEARCH_STATUS] is stripped — it is a transient "searching…" indicator
        that has no meaning once the stream ends.

        [WEB_SEARCH_RESULT] is kept in DB so that the SearchCompletedCard can be
        re-displayed when the user reopens the conversation.  The frontend's
        sanitizeConfigBlocksForAI() already strips ALL WEB_SEARCH_RESULT blocks
        before sending history to the AI, so the AI will never misinterpret them
        as pre-existing search results.

        [PDF_PARSE_STATUS] blocks with status "parsing" (in-progress) are stripped
        since they have no meaning after the stream ends.  Completed/failed blocks
        ARE kept so the frontend can display the PDF parsed card when the user
        reopens the conversation.  The frontend's sanitizeConfigBlocksForAI()
        already strips ALL PDF_PARSE_STATUS blocks before sending history to the AI,
        so there is no risk of the AI misinterpreting them.
        """
        import re as _re
        import json as _json
        content = _re.sub(r'\[SEARCH_STATUS\][\s\S]*?\[/SEARCH_STATUS\]', '', content)

        # Only strip in-progress ("parsing"/"downloading") PDF status blocks; keep completed/failed ones.
        def _strip_parsing_only(m: re.Match) -> str:
            try:
                data = _json.loads(m.group(1).strip())
                if data.get('status') in ('parsing', 'downloading'):
                    return ''
            except Exception:
                pass
            return m.group(0)

        content = _re.sub(
            r'\[PDF_PARSE_STATUS\]([\s\S]*?)\[/PDF_PARSE_STATUS\]',
            _strip_parsing_only,
            content
        )
        return content.strip()

    async def stream_with_persistence():
        """Stream AI response and save to database if conversation_id is provided"""
        full_response = ""
        async for chunk in stream_ai_response(messages, api_key, base_url, model, detected_lang, request):
            # Intercept pdf_context event - save to DB as hidden user message but don't
            # yield to frontend. This lets follow-up questions reference the PDF content.
            if chunk.startswith("data: ") and chunk != "data: [DONE]\n\n":
                try:
                    data = json.loads(chunk[6:])
                    if "pdf_context" in data:
                        if req.conversation_id:
                            async for db_session in get_db():
                                try:
                                    message_data = {
                                        "conversation_id": req.conversation_id,
                                        "role": "user",
                                        "content": f"[PDF_CONTEXT]\n{data['pdf_context']}\n[/PDF_CONTEXT]",
                                    }
                                    await ChatRepository.add_message(db_session, message_data)
                                    await db_session.commit()
                                finally:
                                    await db_session.close()
                        continue  # Don't yield this to frontend
                except (json.JSONDecodeError, KeyError):
                    pass

            # Don't yield [DONE] yet - we need to send message_id first
            if chunk == "data: [DONE]\n\n":
                # Save assistant response to database and return message_id BEFORE [DONE]
                if req.conversation_id and full_response:
                    async for db_session in get_db():
                        try:
                            # Strip internal-only status blocks before persisting so that
                            # on the next turn the AI won't mistake them for existing search results.
                            save_content = _strip_internal_status_blocks(full_response)
                            message_data = {
                                "conversation_id": req.conversation_id,
                                "role": "assistant",
                                "content": save_content,
                            }
                            saved_message = await ChatRepository.add_message(db_session, message_data)
                            await db_session.commit()
                            # Send message_id back to frontend so it can update the message ID
                            # This enables proper persistence of task submission status
                            if saved_message:
                                yield f"data: {json.dumps({'message_id': saved_message.id})}\n\n"
                        finally:
                            await db_session.close()
                # Now yield [DONE] after message_id has been sent
                yield chunk
            else:
                yield chunk
                # Extract content from SSE chunk
                if chunk.startswith("data: "):
                    try:
                        data = json.loads(chunk[6:])
                        if "content" in data and data["content"] is not None:
                            full_response += data["content"]
                    except:
                        pass

    return StreamingResponse(
        stream_with_persistence(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )



# ──────────────────────────────────────────────────────────────────────────────
# PDF image serving
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/pdf-images/{url_hash}/{filename}")
async def serve_pdf_image(
    url_hash: str,
    filename: str,
    user: User = Depends(get_user_from_header_or_param)
):
    """Serve MinerU-extracted PDF images from persistent cache.

    Images are stored at: uploads/pdf_cache/images/{url_hash}/{filename}
    They are created by the background MinerU upgrade task (or the synchronous
    MinerU fallback) and referenced by absolute URLs inside the .mineru.md cache.
    """
    # Prevent path traversal: url_hash must be hex chars only; filename must be
    # a plain filename with no directory separators or parent-dir references.
    if not re.match(r'^[0-9a-f]+$', url_hash, re.IGNORECASE):
        raise HTTPException(status_code=400, detail="Invalid url_hash")
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    image_path = get_pdf_image_path(url_hash, filename)

    if not image_path.exists() or not image_path.is_file():
        raise HTTPException(status_code=404, detail="Image not found")

    content_type, _ = mimetypes.guess_type(str(image_path))
    if content_type is None:
        content_type = "application/octet-stream"

    return FileResponse(image_path, media_type=content_type)
