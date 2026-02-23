"""
PDF Parsing utilities for AI chat - uses MinerU for academic paper processing

When Exa search returns PDF links (e.g., arXiv papers),
this module downloads, parses, and summarizes the content for the AI agent.
"""
import json
import os
import re
import uuid
import tempfile
import asyncio
from pathlib import Path
from typing import Dict, Optional, List
from urllib.parse import urlparse
import httpx

from ..dependencies import logger

# Academic PDF URL patterns
PDF_URL_PATTERNS = [
    # Direct PDF links
    r'\.pdf$',
    # arXiv
    r'arxiv\.org/(pdf|abs)/',
    r'arxiv\.org/pdf/',
    # PubMed / PMC
    r'ncbi\.nlm\.nih\.gov/pmc/articles/',
    r'pubmed\.ncbi\.nlm\.nih\.gov/',
    # Semantic Scholar
    r'semanticscholar\.org/paper/',
    r's2-pdf\.s3\.amazonaws\.com/',
    # ACL Anthology
    r'aclanthology\.org/',
    # IEEE
    r'ieeexplore\.ieee\.org/document/',
    # ACM DL
    r'dl\.acm\.org/doi/',
    # Springer
    r'link\.springer\.com/',
    r'springer\.com/content/pdf/',
    # Elsevier / ScienceDirect
    r'sciencedirect\.com/science/article/',
    r'elsevier\.com/',
    # Nature
    r'nature\.com/articles/',
    # Wiley
    r'onlinelibrary\.wiley\.com/doi/',
    # PLoS
    r'plos\.org/',
    r'journals\.plos\.org/',
    # bioRxiv / medRxiv
    r'biorxiv\.org/content/',
    r'medrxiv\.org/content/',
]


def is_pdf_url(url: str) -> bool:
    """Check if a URL is likely to be a PDF or academic paper."""
    if not url:
        return False
    url_lower = url.lower()
    for pattern in PDF_URL_PATTERNS:
        if re.search(pattern, url_lower):
            return True
    return False


def get_arxiv_pdf_url(url: str) -> str:
    """Convert arXiv abstract URL to PDF URL."""
    match = re.search(r'arxiv\.org/(abs|pdf)/([\w\.\-]+)', url)
    if match:
        paper_id = match.group(2)
        paper_id = paper_id.replace('.pdf', '')
        return f"https://arxiv.org/pdf/{paper_id}.pdf"
    return url


async def download_pdf(url: str, timeout: float = 60.0) -> Optional[bytes]:
    """Download PDF from URL."""
    try:
        if 'arxiv.org' in url:
            url = get_arxiv_pdf_url(url)
        
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.get(
                url,
                headers={"User-Agent": "Mozilla/5.0 (compatible; PathLabBot/1.0)"}
            )
            if response.status_code == 200:
                content = response.content
                if content[:4] == b'%PDF':
                    return content
                content_type = response.headers.get('content-type', '')
                if 'pdf' in content_type.lower():
                    return content
        logger.warning(f"Failed to download PDF from {url}: status {response.status_code}")
        return None
    except Exception as e:
        logger.error(f"Error downloading PDF from {url}: {e}")
        return None


def _parse_pdf_sync(pdf_bytes: bytes, max_pages: int = 10) -> str:
    """Parse PDF using MinerU (synchronous for asyncio.to_thread)."""
    try:
        from mineru.cli.common import convert_pdf_bytes_to_bytes_by_pypdfium2, prepare_env
        from mineru.data.data_reader_writer import FileBasedDataWriter
        from mineru.backend.hybrid.hybrid_analyze import doc_analyze as hybrid_doc_analyze
        from mineru.backend.vlm.vlm_middle_json_mkcontent import union_make
        from mineru.utils.enum_class import MakeMode
        from mineru.utils.engine_utils import get_vlm_engine
        
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            pdf_path = temp_path / "input.pdf"
            pdf_path.write_bytes(pdf_bytes)
            
            output_dir = temp_path / "output"
            local_image_dir, local_md_dir = prepare_env(output_dir, "input", "hybrid_auto")
            
            backend = get_vlm_engine(inference_engine='auto', is_async=False)
            
            start_page_id = 0
            end_page_id = max_pages - 1 if max_pages > 0 else None
            
            pdf_bytes_limited = convert_pdf_bytes_to_bytes_by_pypdfium2(
                pdf_bytes, start_page_id, end_page_id
            )
            
            middle_json, _, _ = hybrid_doc_analyze(
                pdf_bytes_limited,
                image_writer=FileBasedDataWriter(local_image_dir),
                backend=backend,
                parse_method="hybrid_auto",
                language="en",
                inline_formula_enable=True,
                server_url=None,
            )
            
            pdf_info = middle_json["pdf_info"]
            image_dir = str(os.path.basename(local_image_dir))
            md_content = union_make(pdf_info, MakeMode.MM_MD, image_dir)
            
            return md_content
            
    except ImportError as e:
        logger.error(f"MinerU not available: {e}")
        return "[Error: MinerU not installed or import failed]"
    except Exception as e:
        logger.error(f"Error parsing PDF with MinerU: {e}")
        return f"[Error parsing PDF: {str(e)}]"


async def parse_pdf(pdf_bytes: bytes, max_pages: int = 10) -> str:
    """Parse PDF using MinerU asynchronously."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _parse_pdf_sync, pdf_bytes, max_pages)


async def summarize_pdf_content(
    pdf_content: str,
    title: str,
    base_url: str,
    api_key: str,
    model: str,
    max_length: int = 3000
) -> str:
    """Summarize PDF content using LLM."""
    if len(pdf_content) > 15000:
        pdf_content = pdf_content[:15000] + "\n...[content truncated]"
    
    prompt = f"""Analyze this academic paper and provide a comprehensive summary.

Title: {title}

Content:
{pdf_content}

Provide:
1. **Main Topic**: What is this paper about?
2. **Key Contributions**: What are the main contributions or findings?
3. **Methodology**: Brief overview of the approach/method used
4. **Results**: Key results and their significance
5. **Limitations**: Any mentioned limitations or future work

Keep each section concise (2-3 sentences)."""

    messages = [{"role": "user", "content": prompt}]
    
    try:
        from .chat import _call_ai_complete
        summary = await _call_ai_complete(
            messages=messages,
            base_url=base_url,
            api_key=api_key,
            model=model
        )
        return summary
    except Exception as e:
        logger.error(f"Error summarizing PDF: {e}")
        return pdf_content[:max_length]


