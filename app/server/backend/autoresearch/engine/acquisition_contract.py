"""Validated acquisition metadata survives download, preparation and registration."""

import re
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Provider = Literal["huggingface", "zenodo", "kaggle", "gdc", "dataverse", "scidb", "direct_http"]
PROVIDERS: tuple[str, ...] = Provider.__args__
# Spellings agents and papers use for the same source, after lowercasing and dropping
# everything but letters and digits.
ALIASES = {
    "hf": "huggingface", "huggingfacehub": "huggingface", "hfhub": "huggingface",
    "huggingfacedatasets": "huggingface", "huggingfacedataset": "huggingface",
    "http": "direct_http", "https": "direct_http", "url": "direct_http", "directhttp": "direct_http",
    "direct": "direct_http", "web": "direct_http", "tcga": "gdc", "gdcportal": "gdc",
    "tcia": "gdc", "harvarddataverse": "dataverse", "sciencedb": "scidb",
}
HOSTS = {
    "huggingface.co": "huggingface", "hf.co": "huggingface", "zenodo.org": "zenodo",
    "kaggle.com": "kaggle", "gdc.cancer.gov": "gdc", "scidb.cn": "scidb", "dataverse": "dataverse",
}


def _key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def _host_provider(url: str) -> str | None:
    host = (urlsplit(url).hostname or "").casefold()
    return next((name for marker, name in HOSTS.items() if marker in host), None)


def normalize_provider(value: str, download: dict | None = None) -> str:
    """Map a free-text source name to a provider key, or explain the valid ones."""
    key = _key(value or "")
    if key in PROVIDERS or key in {_key(p) for p in PROVIDERS}:
        return next(p for p in PROVIDERS if _key(p) == key)
    if key in ALIASES:
        return ALIASES[key]
    # "Owkin / Hugging Face" names the host among other words.
    named = {p for p in PROVIDERS if p != "direct_http" and _key(p) in key}
    named |= {ALIASES[a] for a in ALIASES if len(a) > 4 and a in key}
    if len(named) == 1:
        return named.pop()
    download = download or {}
    urls = list(download.get("urls") or [])
    if download.get("remote_id") or not urls:
        hosts = {_host_provider(url) for url in urls} - {None}
        if len(hosts) == 1:
            return hosts.pop()
    elif urls:
        # Explicit file URLs download as they are, whatever site serves them.
        return "direct_http"
    raise ValueError(
        f"Unknown provider {value!r}. Use one of: {', '.join(PROVIDERS)} "
        "(direct_http downloads the exact files listed in download.urls).")


class DownloadLocation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str
    remote_id: str = ""
    urls: list[str] = Field(default_factory=list)
    filename: str = ""
    checksum_sha256: str = ""
    include: list[str] = Field(
        default_factory=list, max_length=200,
        description="huggingface only: glob patterns of repository paths to fetch (fnmatch; * also "
                    "matches /), for example ['camelyon17/gigapath/*']. Fetch only what the study uses; "
                    "large repositories are refused without it.")


class AcquisitionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    dataset_id: str = Field(min_length=1, max_length=255)
    name: str = Field(min_length=1, max_length=255)
    provider: Provider = Field(description="Source adapter. Free-text names such as 'Hugging Face' are normalized.")
    access: Literal["public", "gated", "manual"]
    task_types: list[
        Literal[
            "wsi_classification",
            "patch_classification",
            "wsi_survival",
            "patch_segmentation",
            "patch_detection",
        ]
    ] = Field(min_length=1, max_length=1)
    asset_types: list[str] = Field(min_length=1)
    organs: list[str] = Field(
        min_length=1,
        description="Verified organs; use Unknown only when the source does not state them. Never guess.",
    )
    license: str = Field(
        min_length=1, description="Source license, or Unknown if not stated"
    )
    source_url: str = Field(min_length=1)
    description: str = ""
    visibility: Literal["public", "private"] | None = None
    aggregation_level: Literal["file", "case"] = "file"
    estimated_size_gb: float = Field(default=0, ge=0)
    tags: list[str] = Field(default_factory=list)
    source_paper_ids: list[str] = Field(default_factory=list)
    download: DownloadLocation
    annotation_columns: dict[str, str] = Field(
        default_factory=dict,
        description="Optional table columns: slide_id, label, case_id, event_time, event_status",
    )
    annotations_file: str = Field(
        default="",
        description="Relative path inside the downloaded dataset to the authoritative label/case/survival table or COCO JSON",
    )
    splits_file: str = Field(
        default="",
        description="Relative path to source-defined train/val/test splits; never invent an official split",
    )

    @model_validator(mode="before")
    @classmethod
    def known_provider(cls, data):
        if isinstance(data, dict) and isinstance(data.get("provider"), str):
            download = data.get("download") if isinstance(data.get("download"), dict) else {}
            data = {**data, "provider": normalize_provider(data["provider"], download)}
        return data

    @model_validator(mode="after")
    def include_is_supported(self):
        if self.download.include and self.provider != "huggingface":
            raise ValueError("download.include selects files in a huggingface repository; for other sources "
                             "list the exact files in download.urls with provider direct_http")
        return self

    @field_validator("organs")
    @classmethod
    def valid_organs(cls, values):
        if any(not value.strip() for value in values):
            raise ValueError("Organs cannot contain blank values")
        return [value.strip() for value in values]

    @field_validator("source_url")
    @classmethod
    def valid_source(cls, value):
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
        ):
            raise ValueError("Provide the public source metadata URL")
        return value
