"""Authenticated HTTP access to images produced by the shared article reader."""

import mimetypes
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from backend.auth.dependencies import get_user_from_header_or_param
from backend.services.articles import reader

router = APIRouter(tags=["Chat & Conversations"])


@router.get("/pdf-images/{url_hash}/{filename}")
async def serve_pdf_image(
    url_hash: str, filename: str, user: Any = Depends(get_user_from_header_or_param)
):
    if not re.fullmatch(r"[0-9a-f]{64}", url_hash) or any(
        part in filename for part in ["..", "/", "\\"]
    ):
        raise HTTPException(400, "Invalid image path")
    root = (reader.get_pdf_cache_dir() / "images" / url_hash).resolve()
    path = reader.get_pdf_image_path(url_hash, filename).resolve()
    if not path.is_relative_to(root):
        raise HTTPException(400, "Invalid image path")
    if not path.is_file():
        raise HTTPException(404, "Image not found")
    return FileResponse(
        path,
        media_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
    )
