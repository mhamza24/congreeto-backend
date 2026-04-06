"""
pdf_reader.py — Unified PDF reader with source-switching via flag.

One public function. One `source` flag. Switch between:
    "url"  → direct HTTP/HTTPS URL  (default)
               Works with: GCS presigned URLs, Azure Blob SAS, S3 presigned,
               Supabase Storage, Cloudflare R2 — anything public or presigned.
    "gcs"  → Google Cloud Storage   (recommended for GCP infra)
               Auth: service account JSON  OR  Application Default Credentials.
    "s3"   → AWS S3
               Auth: explicit keys  OR  boto3 default credential chain.

Usage:
    # Default — any public or presigned blob URL
    result = await read_pdf("https://storage.googleapis.com/bucket/file.pdf?token=...")

    # GCS directly — no presigned URL needed
    result = await read_pdf("gs://my-bucket/reports/brochure.pdf", source="gcs")

    # S3 directly
    result = await read_pdf("s3://my-bucket/reports/brochure.pdf", source="s3")

    # Multiple files in one call
    result = await read_pdf(
        ["gs://bucket/apartments.pdf", "gs://bucket/terraces.pdf"],
        source="gcs",
    )
"""

import io
import re
from typing import Any, Dict, List, Optional, Union

import httpx
import pdfplumber

from app.config.settings import get_settings

settings = get_settings()

# ── Optional cloud SDK imports ────────────────────────────────────────────────
# Only imported inside the fetcher that needs them — no hard dependency.
# GCS: pip install google-cloud-storage
# S3:  pip install boto3

try:
    from google.cloud import storage as _gcs  # noqa: F401
    _GCS_AVAILABLE = True
except ImportError:
    _GCS_AVAILABLE = False

try:
    import boto3 as _boto3  # noqa: F401
    _S3_AVAILABLE = True
except ImportError:
    _S3_AVAILABLE = False


# ─────────────────────────────────────────────────────────────────────────────
# Return type shape (for reference)
# ─────────────────────────────────────────────────────────────────────────────
#
# {
#   "gs://bucket/file.pdf": {
#       "filename":    "file.pdf",
#       "source":      "gcs",
#       "total_pages": 4,
#       "pages": [
#           {
#               "page_number": 1,
#               "text":        "Cleaned text from this page...",
#               "tables": [
#                   [["Col A", "Col B"], ["Val 1", "Val 2"]],
#               ],
#           },
#           ...
#       ],
#       "full_text":  "All pages concatenated...",
#       "error":       None,
#   }
# }
#
# Failed files are always included with error set — function never raises.


# =========================================================
# Public Function (This is the ONLY function you call)
# =========================================================


async def read_pdf(
    input_data: Union[str, List[str]],
    source: str = "url",
    extract_tables: bool = True,
    password: Optional[str] = None,
    # ── "url" source options ──────────────────────────────────────────────────
    timeout: int = settings.SCRAPPER_PDF_TIMEOUT,
    # ── "gcs" source options ──────────────────────────────────────────────────
    # gcs_project: Optional[str] = settings.GCS_PROJECT_ID | "test",
    # gcs_credentials_path: Optional[str] = settings.GCS_CREDENTIALS_PATH | "test",
    # # ── "s3" source options ───────────────────────────────────────────────────
    # s3_region: Optional[str] = settings.S3_REGION | "test",
    # s3_access_key: Optional[str] = settings.S3_ACCESS_KEY | "test",
    # s3_secret_key: Optional[str] = settings.S3_SECRET_KEY | "test",
) -> Dict[str, Dict[str, Any]]:
    """
    Read one or more PDFs. Switch sources via the `source` flag.

    Args:
        input_data:             Single path/URL string or list of strings.
        source:                 "url" | "gcs" | "s3"  (default: "url")
        extract_tables:         Parse tables per page  (default: True)
        password:               Password for encrypted PDFs.
        timeout:                HTTP timeout in seconds (url source only).
        gcs_project:            GCP project ID (gcs source).
        gcs_credentials_path:   Path to service account JSON (gcs source).
                                None → Application Default Credentials (ADC).
                                On Cloud Run / GCE / GKE this is automatic.
                                Locally: gcloud auth application-default login
        s3_region:              AWS region (s3 source).
        s3_access_key:          AWS access key (s3 source).
                                None → boto3 default credential chain.
        s3_secret_key:          AWS secret key (s3 source).

    Path formats per source:
        url → "https://storage.googleapis.com/bucket/file.pdf?token=..."
        gcs → "gs://bucket-name/path/to/file.pdf"
        s3  → "s3://bucket-name/path/to/file.pdf"

    Returns:
        Dict keyed by the original path/URL passed in.
    """
    paths = _normalize_input(input_data)
    results: Dict[str, Dict[str, Any]] = {}

    for path in paths:
        result = _empty_result(_filename_from_path(path), source)

        # ── Step 1: fetch raw bytes based on source flag ───────────────────
        try:
            if source == "url":
                pdf_bytes = await _fetch_url(path, timeout)

            elif source == "gcs":
                if not _GCS_AVAILABLE:
                    raise ImportError(
                        "google-cloud-storage is not installed. "
                        "Run: pip install google-cloud-storage"
                    )
                # pdf_bytes = _fetch_gcs(
                #     path,
                #     project=gcs_project,
                #     credentials_path=gcs_credentials_path,
                # )

            elif source == "s3":
                if not _S3_AVAILABLE:
                    raise ImportError(
                        "boto3 is not installed. Run: pip install boto3"
                    )
                # pdf_bytes = _fetch_s3(
                #     path,
                #     region=s3_region,
                #     access_key=s3_access_key,
                #     secret_key=s3_secret_key,
                # )

            else:
                raise ValueError(
                    f"Unknown source '{source}'. Must be 'url', 'gcs', or 's3'."
                )

        except Exception as exc:
            result["error"] = f"Fetch error ({source}): {exc}"
            results[path] = result
            continue

        # ── Step 2: parse PDF bytes ────────────────────────────────────────
        try:
            result.update(
                _parse_pdf(pdf_bytes, extract_tables=extract_tables,
                           password=password)
            )
        except Exception as exc:
            result["error"] = f"Parse error: {exc}"

        results[path] = result

    return results


# =========================================================
# Source Fetchers (Private)
# =========================================================


async def _fetch_url(url: str, timeout: int) -> bytes:
    """
    Fetch over HTTP/HTTPS. Follows redirects automatically.
    Works with any publicly accessible or presigned blob URL.
    """
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.content


def _fetch_gcs(
    path: str,
    project: Optional[str],
    credentials_path: Optional[str],
) -> bytes:
    """
    Fetch directly from GCS using the SDK — no presigned URL required.

    Accepts:
        "gs://my-bucket/reports/brochure.pdf"
        "my-bucket/reports/brochure.pdf"         ← gs:// prefix is optional

    Auth:
        credentials_path set  → explicit service account JSON file
        credentials_path None → ADC (automatic on Cloud Run / GCE / GKE)
    """
    from google.cloud import storage

    if credentials_path:
        from google.oauth2 import service_account
        creds = service_account.Credentials.from_service_account_file(
            credentials_path,
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
        client = storage.Client(project=project, credentials=creds)
    else:
        # ADC — zero config on GCP, `gcloud auth application-default login` locally
        client = storage.Client(project=project)

    bucket_name, blob_name = _split_gcs_path(path)
    buffer = io.BytesIO()
    client.bucket(bucket_name).blob(blob_name).download_to_file(buffer)
    return buffer.getvalue()


def _fetch_s3(
    path: str,
    region: Optional[str],
    access_key: Optional[str],
    secret_key: Optional[str],
) -> bytes:
    """
    Fetch directly from S3 using boto3 — no presigned URL required.

    Accepts:
        "s3://my-bucket/reports/brochure.pdf"
        "my-bucket/reports/brochure.pdf"         ← s3:// prefix is optional

    Auth:
        access_key + secret_key set → explicit credentials
        both None                   → boto3 default chain (env, ~/.aws, IAM role)
    """
    import boto3

    kwargs: Dict[str, Any] = {}
    if region:
        kwargs["region_name"] = region
    if access_key and secret_key:
        kwargs["aws_access_key_id"] = access_key
        kwargs["aws_secret_access_key"] = secret_key

    bucket_name, key = _split_s3_path(path)
    s3 = boto3.client("s3", **kwargs)
    return s3.get_object(Bucket=bucket_name, Key=key)["Body"].read()


# =========================================================
# PDF Parser
# Exposed so routes can call it directly with raw bytes
# (e.g. multipart upload from Postman — bytes come from UploadFile, not a URL)
# =========================================================


def _parse_pdf(
    pdf_bytes: bytes,
    extract_tables: bool,
    password: Optional[str],
) -> Dict[str, Any]:
    """Parse raw bytes with pdfplumber. Returns the dict merged into result."""
    pages_data: List[Dict[str, Any]] = []
    full_text_parts: List[str] = []

    open_kwargs: Dict[str, Any] = {}
    if password:
        open_kwargs["password"] = password

    with pdfplumber.open(io.BytesIO(pdf_bytes), **open_kwargs) as pdf:
        for page in pdf.pages:
            text = _clean_text(page.extract_text() or "")

            tables: List[List[List[str]]] = []
            if extract_tables:
                for raw_table in page.extract_tables():
                    # Normalise None cells → "" and drop fully empty rows
                    cleaned = [
                        [cell if cell is not None else "" for cell in row]
                        for row in raw_table
                        if any(cell for cell in row)
                    ]
                    if cleaned:
                        tables.append(cleaned)

            pages_data.append({
                "page_number": page.page_number,   # 1-indexed
                "text": text,
                "tables": tables,
            })

            if text:
                full_text_parts.append(text)

    return {
        "total_pages": len(pages_data),
        "pages": pages_data,
        "full_text": "\n\n".join(full_text_parts),
    }


# =========================================================
# Path Parsers (Private)
# =========================================================


def _split_gcs_path(path: str) -> tuple:
    """
    "gs://bucket/a/b/file.pdf" → ("bucket", "a/b/file.pdf")
    "bucket/a/b/file.pdf"      → ("bucket", "a/b/file.pdf")
    """
    path = path.removeprefix("gs://")
    parts = path.split("/", 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError(
            f"Invalid GCS path: '{path}'. "
            "Expected format: 'gs://bucket-name/path/to/file.pdf'"
        )
    return parts[0], parts[1]


def _split_s3_path(path: str) -> tuple:
    """
    "s3://bucket/a/b/file.pdf" → ("bucket", "a/b/file.pdf")
    "bucket/a/b/file.pdf"      → ("bucket", "a/b/file.pdf")
    """
    path = path.removeprefix("s3://")
    parts = path.split("/", 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError(
            f"Invalid S3 path: '{path}'. "
            "Expected format: 's3://bucket-name/path/to/file.pdf'"
        )
    return parts[0], parts[1]


# =========================================================
# Shared Helpers (Private)
# =========================================================


def _normalize_input(input_data: Union[str, List[str]]) -> List[str]:
    """Same interface contract as scrape_websites()."""
    if isinstance(input_data, str):
        return [input_data]
    if isinstance(input_data, list):
        if not all(isinstance(u, str) for u in input_data):
            raise ValueError("All items in list must be strings.")
        return input_data
    raise TypeError(
        "input_data must be a URL/path string or a list of strings."
    )


def _filename_from_path(path: str) -> str:
    """Strip query params (for presigned URLs) then grab the last segment."""
    return path.split("?")[0].rstrip("/").split("/")[-1] or "document.pdf"


def _empty_result(filename: str, source: str) -> Dict[str, Any]:
    return {
        "filename": filename,
        "source": source,
        "total_pages": 0,
        "pages": [],
        "full_text": "",
        "error": None,
    }


def _clean_text(raw: str) -> str:
    """Collapse whitespace and drop noise lines (page numbers, lone dashes)."""
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in raw.splitlines()]
    return "\n".join(
        line for line in lines
        if line and not re.fullmatch(r"[\-\–\—\d\s]+", line)
    )
