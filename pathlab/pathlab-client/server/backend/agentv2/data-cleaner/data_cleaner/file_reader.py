"""Smart file reader for messy Excel/CSV files.

Handles:
- CSV with auto-detected delimiters and encoding (via clevercsv + chardet)
- Excel with merged cells, multi-sheet, header not on first row
- Generates sample markdown for LLM analysis
"""

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import chardet
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class FileMetadata:
    """Metadata about the input file."""

    file_path: str
    file_type: str  # "csv" or "excel"
    file_size_bytes: int = 0
    encoding: str = "utf-8"
    delimiter: str = ","
    num_rows: int = 0
    num_cols: int = 0
    sheet_names: list[str] = field(default_factory=list)
    active_sheet: str = ""
    has_merged_cells: bool = False
    header_row: int = 0  # 0-indexed
    issues: list[str] = field(default_factory=list)


@dataclass
class ReadResult:
    """Result of reading a file."""

    df: pd.DataFrame
    metadata: FileMetadata
    sample_markdown: str  # First N rows as markdown table for LLM
    schema_text: str = ""  # Structured schema (column name, type, samples)


def detect_encoding(file_path: str) -> str:
    """Detect file encoding using chardet."""
    with open(file_path, "rb") as f:
        raw = f.read(min(100_000, os.path.getsize(file_path)))
    result = chardet.detect(raw)
    encoding = result.get("encoding", "utf-8") or "utf-8"
    confidence = result.get("confidence", 0)
    logger.info(f"Detected encoding: {encoding} (confidence: {confidence:.2f})")
    # Normalize common encoding names
    encoding_map = {
        "ascii": "utf-8",
        "iso-8859-1": "latin-1",
        "windows-1252": "latin-1",
        "gb2312": "gbk",
        "gb18030": "gbk",
    }
    return encoding_map.get(encoding.lower(), encoding)


def _detect_header_row(df_raw: pd.DataFrame, max_scan: int = 20) -> int:
    """Heuristic to find the actual header row in a messy table.

    Looks for the first row where most values are non-null strings
    (likely column names) followed by rows with actual data.
    Prefers rows with:
    - High column coverage (many non-null values)
    - Diverse values (not all the same, which indicates merged cell artifact)
    - Short, non-numeric strings (typical header names)
    """
    if df_raw.empty:
        return 0

    total_cols = len(df_raw.columns)
    scan_limit = min(max_scan, len(df_raw))
    best_row = 0
    best_score = 0

    for i in range(scan_limit):
        row = df_raw.iloc[i]
        # Score: count of non-null string values that look like headers
        header_like = 0
        non_null = 0
        unique_values = set()
        for val in row:
            if pd.isna(val):
                continue
            s = str(val).strip()
            if not s:
                continue
            non_null += 1
            unique_values.add(s)
            # Headers tend to be short strings, not pure numbers
            if len(s) < 60 and not _is_pure_number(s):
                header_like += 1

        # Penalize rows where all values are the same
        # (common artifact from merged cells being expanded)
        if len(unique_values) <= 1 and non_null > 1:
            continue  # Skip: merged cell artifact

        # Score rewards: high column coverage + header-like values + diversity
        coverage = non_null / total_cols if total_cols > 0 else 0
        diversity = len(unique_values) / max(non_null, 1)
        score = header_like * (1 + coverage) * (0.5 + 0.5 * diversity)

        if score > best_score:
            best_score = score
            best_row = i

    return best_row


def _is_pure_number(s: str) -> bool:
    """Check if a string is purely numeric."""
    try:
        float(s.replace(",", ""))
        return True
    except (ValueError, AttributeError):
        return False


def read_csv(file_path: str) -> ReadResult:
    """Read a CSV file with smart dialect detection."""
    metadata = FileMetadata(
        file_path=file_path,
        file_type="csv",
        file_size_bytes=os.path.getsize(file_path),
    )

    # Step 1: Detect encoding
    encoding = detect_encoding(file_path)
    metadata.encoding = encoding

    # Step 2: Detect CSV dialect (delimiter, quoting, etc.)
    delimiter = ","
    try:
        import clevercsv

        dialect = clevercsv.Sniffer().sniff(
            open(file_path, "r", encoding=encoding, errors="replace").read(50_000)
        )
        if dialect:
            delimiter = dialect.delimiter
            logger.info(f"CleverCSV detected delimiter: {repr(delimiter)}")
    except Exception as e:
        logger.warning(f"CleverCSV detection failed, using comma: {e}")
    metadata.delimiter = delimiter

    # Step 3: Read all lines as raw text first, then build DataFrame
    # This avoids pandas skipping lines with different column counts
    try:
        import csv as csv_mod

        with open(file_path, "r", encoding=encoding, errors="replace") as f:
            reader = csv_mod.reader(f, delimiter=delimiter)
            all_rows = list(reader)
    except UnicodeDecodeError:
        logger.warning(f"Encoding {encoding} failed, falling back to latin-1")
        encoding = "latin-1"
        metadata.encoding = encoding
        import csv as csv_mod

        with open(file_path, "r", encoding=encoding, errors="replace") as f:
            reader = csv_mod.reader(f, delimiter=delimiter)
            all_rows = list(reader)

    if not all_rows:
        metadata.issues.append("File is empty")
        return ReadResult(df=pd.DataFrame(), metadata=metadata, sample_markdown="(empty file)")

    # Normalize row lengths to the max column count
    max_cols = max(len(row) for row in all_rows)
    normalized_rows = [
        row + [""] * (max_cols - len(row)) for row in all_rows
    ]

    df_raw = pd.DataFrame(normalized_rows, dtype=str)
    # Replace empty strings with NaN for header detection
    df_raw = df_raw.replace("", np.nan)

    # Step 4: Detect header row
    header_row = _detect_header_row(df_raw)
    metadata.header_row = header_row

    if header_row > 0:
        metadata.issues.append(
            f"Header detected at row {header_row} (not first row)"
        )

    # Set header and data
    headers = df_raw.iloc[header_row].tolist()
    df = df_raw.iloc[header_row + 1 :].copy()
    df.columns = [
        str(h).strip() if pd.notna(h) else f"col_{i}"
        for i, h in enumerate(headers)
    ]
    df = df.reset_index(drop=True)

    # Replace empty strings with NaN
    df = df.replace("", np.nan)

    # Drop completely empty rows and columns
    df = df.dropna(how="all").dropna(axis=1, how="all")
    df = df.reset_index(drop=True)

    # Clean up column names
    df.columns = [str(c).strip() for c in df.columns]

    metadata.num_rows = len(df)
    metadata.num_cols = len(df.columns)

    # Check for issues
    _detect_issues(df, metadata)

    sample_md = _generate_sample_markdown(df)
    schema_text = _generate_schema_text(df)
    return ReadResult(df=df, metadata=metadata, sample_markdown=sample_md, schema_text=schema_text)


def read_excel(file_path: str, sheet_name: Optional[str] = None) -> ReadResult:
    """Read an Excel file, handling merged cells and messy structures.

    Supports:
    - .xlsx, .xlsm (via openpyxl with merged cell handling)
    - .xls (via xlrd + pandas fallback)
    - .xlsb (via pyxlsb if installed, otherwise pandas)
    """
    ext = Path(file_path).suffix.lower()

    metadata = FileMetadata(
        file_path=file_path,
        file_type="excel",
        file_size_bytes=os.path.getsize(file_path),
    )

    if ext == ".xls":
        return _read_xls(file_path, sheet_name, metadata)
    else:
        return _read_xlsx(file_path, sheet_name, metadata)


def _read_xlsx(
    file_path: str, sheet_name: Optional[str], metadata: FileMetadata
) -> ReadResult:
    """Read .xlsx/.xlsm files using openpyxl (supports merged cells)."""
    import openpyxl

    # Step 1: Open workbook to inspect structure
    try:
        wb = openpyxl.load_workbook(file_path, data_only=True)
    except Exception as e:
        logger.warning(f"openpyxl failed to open file: {e}. Trying pandas fallback.")
        return _read_excel_pandas_fallback(file_path, sheet_name, metadata)

    metadata.sheet_names = wb.sheetnames

    # Select sheet
    if sheet_name and sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        metadata.active_sheet = sheet_name
    else:
        ws = wb.active
        metadata.active_sheet = ws.title

    # Step 2: Handle merged cells
    merged_ranges = list(ws.merged_cells.ranges)
    if merged_ranges:
        metadata.has_merged_cells = True
        metadata.issues.append(f"Found {len(merged_ranges)} merged cell ranges")
        # Unmerge and fill
        for merge_range in merged_ranges:
            min_row = merge_range.min_row
            min_col = merge_range.min_col
            top_left_value = ws.cell(row=min_row, column=min_col).value
            ws.unmerge_cells(str(merge_range))
            for row in range(merge_range.min_row, merge_range.max_row + 1):
                for col in range(merge_range.min_col, merge_range.max_col + 1):
                    ws.cell(row=row, column=col).value = top_left_value

    # Step 3: Convert to list of lists
    data = []
    for row in ws.iter_rows(values_only=True):
        data.append([str(v).strip() if v is not None else "" for v in row])

    wb.close()

    return _build_result_from_rows(data, metadata)


def _read_xls(
    file_path: str, sheet_name: Optional[str], metadata: FileMetadata
) -> ReadResult:
    """Read .xls files (old Excel format) using xlrd + pandas."""
    try:
        import xlrd

        # Open with xlrd to get sheet names and check structure
        wb = xlrd.open_workbook(file_path)
        metadata.sheet_names = wb.sheet_names()

        # Select sheet
        if sheet_name and sheet_name in wb.sheet_names():
            ws = wb.sheet_by_name(sheet_name)
            metadata.active_sheet = sheet_name
        else:
            ws = wb.sheet_by_index(0)
            metadata.active_sheet = ws.name

        # Check for merged cells
        if ws.merged_cells:
            metadata.has_merged_cells = True
            metadata.issues.append(
                f"Found {len(ws.merged_cells)} merged cell ranges (.xls format)"
            )

        # Read all data as strings
        data = []
        for row_idx in range(ws.nrows):
            row_data = []
            for col_idx in range(ws.ncols):
                cell = ws.cell(row_idx, col_idx)
                # Handle different xlrd cell types
                if cell.ctype == xlrd.XL_CELL_EMPTY:
                    row_data.append("")
                elif cell.ctype == xlrd.XL_CELL_DATE:
                    # Convert Excel date to string
                    try:
                        date_tuple = xlrd.xldate_as_tuple(cell.value, wb.datemode)
                        from datetime import datetime
                        dt = datetime(*date_tuple)
                        row_data.append(dt.strftime("%Y-%m-%d"))
                    except Exception:
                        row_data.append(str(cell.value))
                elif cell.ctype == xlrd.XL_CELL_NUMBER:
                    # Keep integers as integers, floats as floats
                    val = cell.value
                    if val == int(val):
                        row_data.append(str(int(val)))
                    else:
                        row_data.append(str(val))
                elif cell.ctype == xlrd.XL_CELL_BOOLEAN:
                    row_data.append("True" if cell.value else "False")
                else:
                    row_data.append(str(cell.value).strip())
            data.append(row_data)

        wb.release_resources()
        logger.info(f"Read .xls file with xlrd: {len(data)} rows, sheet='{metadata.active_sheet}'")

    except ImportError:
        logger.warning("xlrd not installed. Trying pandas fallback for .xls file.")
        return _read_excel_pandas_fallback(file_path, sheet_name, metadata)
    except Exception as e:
        logger.warning(f"xlrd failed: {e}. Trying pandas fallback.")
        return _read_excel_pandas_fallback(file_path, sheet_name, metadata)

    return _build_result_from_rows(data, metadata)


def _read_excel_pandas_fallback(
    file_path: str, sheet_name: Optional[str], metadata: FileMetadata
) -> ReadResult:
    """Fallback: read any Excel format using pandas (no merged cell handling)."""
    logger.info("Using pandas fallback to read Excel file")
    metadata.issues.append("Using pandas fallback reader (merged cells may not be handled)")

    try:
        # Determine engine based on extension
        ext = Path(file_path).suffix.lower()
        engine = "xlrd" if ext == ".xls" else "openpyxl"

        # Get sheet names
        xls = pd.ExcelFile(file_path, engine=engine)
        metadata.sheet_names = xls.sheet_names

        target_sheet = sheet_name if sheet_name in xls.sheet_names else xls.sheet_names[0]
        metadata.active_sheet = target_sheet

        df_raw = pd.read_excel(
            file_path,
            sheet_name=target_sheet,
            header=None,
            dtype=str,
            engine=engine,
        )

        # Convert to list of lists for consistent processing
        data = []
        for _, row in df_raw.iterrows():
            data.append([str(v).strip() if pd.notna(v) else "" for v in row])

    except Exception as e:
        logger.error(f"Pandas fallback also failed: {e}")
        metadata.issues.append(f"Failed to read file: {e}")
        return ReadResult(df=pd.DataFrame(), metadata=metadata, sample_markdown="(failed to read)")

    return _build_result_from_rows(data, metadata)


def _build_result_from_rows(data: list[list[str]], metadata: FileMetadata) -> ReadResult:
    """Common logic to build ReadResult from a list of rows (shared by xlsx/xls readers)."""
    if not data:
        metadata.issues.append("Sheet is empty")
        return ReadResult(
            df=pd.DataFrame(), metadata=metadata, sample_markdown="(empty sheet)"
        )

    # Ensure all values are strings for consistent processing
    str_data = []
    for row in data:
        str_row = []
        for val in row:
            if val is None or (isinstance(val, float) and np.isnan(val)):
                str_row.append("")
            else:
                str_row.append(str(val).strip())
        str_data.append(str_row)

    # Normalize row lengths
    max_cols = max(len(row) for row in str_data) if str_data else 0
    normalized = [row + [""] * (max_cols - len(row)) for row in str_data]

    # Create raw DataFrame (all strings)
    df_raw = pd.DataFrame(normalized, dtype=str)

    # Replace empty strings with NaN for header detection
    for col in df_raw.columns:
        df_raw[col] = df_raw[col].where(df_raw[col] != "", other=np.nan)

    header_row = _detect_header_row(df_raw)
    metadata.header_row = header_row

    if header_row > 0:
        metadata.issues.append(
            f"Header detected at row {header_row} (not first row)"
        )

    # Set header and data
    headers = df_raw.iloc[header_row].tolist()
    df = df_raw.iloc[header_row + 1 :].copy()
    df.columns = [
        str(h).strip() if pd.notna(h) and str(h).strip() else f"col_{i}"
        for i, h in enumerate(headers)
    ]
    df = df.reset_index(drop=True)

    # Replace empty strings with NaN
    for col in df.columns:
        df[col] = df[col].where(df[col] != "", other=np.nan)

    # Drop completely empty rows and columns
    df = df.dropna(how="all").dropna(axis=1, how="all")
    df = df.reset_index(drop=True)

    metadata.num_rows = len(df)
    metadata.num_cols = len(df.columns)

    _detect_issues(df, metadata)

    sample_md = _generate_sample_markdown(df)
    schema_text = _generate_schema_text(df)
    return ReadResult(df=df, metadata=metadata, sample_markdown=sample_md, schema_text=schema_text)


def _detect_issues(df: pd.DataFrame, metadata: FileMetadata):
    """Detect common data quality issues."""
    # Missing values
    total_cells = df.shape[0] * df.shape[1]
    missing_count = df.isna().sum().sum()
    if missing_count > 0:
        pct = missing_count / total_cells * 100
        metadata.issues.append(
            f"Missing values: {missing_count}/{total_cells} ({pct:.1f}%)"
        )

    # Duplicate rows
    dup_count = df.duplicated().sum()
    if dup_count > 0:
        metadata.issues.append(f"Duplicate rows: {dup_count}")

    # Columns with mixed types (strings that look like numbers mixed with text)
    for col in df.columns:
        non_null = df[col].dropna()
        if len(non_null) == 0:
            metadata.issues.append(f"Column '{col}' is entirely empty")
            continue

        # Check for inconsistent whitespace in column name
        if str(col) != str(col).strip():
            metadata.issues.append(f"Column '{col}' has leading/trailing whitespace")


def _generate_sample_markdown(
    df: pd.DataFrame, max_rows: int = 10, max_col_width: int = 40
) -> str:
    """Generate a markdown table of the first N rows for LLM analysis."""
    if df.empty:
        return "(empty table)"

    sample = df.head(max_rows).copy()

    # Truncate long values for readability
    def _truncate(x):
        try:
            if x is None or (isinstance(x, float) and np.isnan(x)):
                return x
            s = str(x)
            return s[:max_col_width] + "..." if len(s) > max_col_width else x
        except (TypeError, ValueError):
            return x

    for col in sample.columns:
        sample[col] = sample[col].apply(_truncate)

    md = sample.to_markdown(index=False)

    # Add summary
    summary_lines = [
        f"\n\n**Table Summary**: {len(df)} rows x {len(df.columns)} columns",
        f"**Columns**: {', '.join(df.columns.tolist())}",
    ]

    return md + "\n".join(summary_lines)


def _generate_schema_text(df: pd.DataFrame, max_samples: int = 3) -> str:
    """Generate structured schema description for LLM.

    Provides column name, inferred type, non-null count, and sample values.
    This gives the LLM more precise information than a markdown table alone.
    """
    if df.empty:
        return "(empty table)"

    lines = [
        f"Table Schema: {len(df)} rows x {len(df.columns)} columns",
        "",
        f"{'Column':<25} {'Type':<12} {'Non-Null':<10} {'Samples'}",
        f"{'-'*25} {'-'*12} {'-'*10} {'-'*40}",
    ]

    for col in df.columns:
        series = df[col]
        non_null = series.dropna()
        non_null_count = len(non_null)

        # Infer type
        dtype = _infer_column_type(non_null)

        # Get sample values (unique, non-null)
        unique_vals = non_null.unique()
        samples = [str(v)[:30] for v in unique_vals[:max_samples]]
        sample_str = ", ".join(f'"{s}"' for s in samples)
        if len(unique_vals) > max_samples:
            sample_str += f" ... ({len(unique_vals)} unique)"

        lines.append(
            f"{str(col):<25} {dtype:<12} {non_null_count:<10} {sample_str}"
        )

    return "\n".join(lines)


def _infer_column_type(series: pd.Series) -> str:
    """Infer the semantic type of a column from its values."""
    if len(series) == 0:
        return "empty"

    # Try numeric
    numeric_count = 0
    for val in series:
        try:
            float(str(val).replace(",", ""))
            numeric_count += 1
        except (ValueError, TypeError):
            pass

    if numeric_count > len(series) * 0.8:
        return "numeric"

    # Check for date-like patterns
    date_keywords = ["date", "time", "year", "month", "day"]
    values_str = " ".join(str(v).lower() for v in series.head(5))

    # Check for boolean-like
    unique_lower = set(str(v).lower().strip() for v in series.unique())
    bool_sets = [
        {"true", "false"}, {"yes", "no"}, {"0", "1"},
        {"alive", "dead"}, {"male", "female"}, {"m", "f"},
        {"存活", "死亡"}, {"男", "女"},
    ]
    for bs in bool_sets:
        if unique_lower.issubset(bs | {"nan", "none", "null", ""}):
            return "category"

    # If few unique values relative to total, likely categorical
    if len(series.unique()) < max(5, len(series) * 0.3):
        return "category"

    return "text"


def read_file(file_path: str, sheet_name: Optional[str] = None) -> ReadResult:
    """Read a file (CSV or Excel) with smart format detection.

    Args:
        file_path: Path to the input file
        sheet_name: For Excel files, which sheet to read (default: active sheet)

    Returns:
        ReadResult with DataFrame, metadata, and sample markdown
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    ext = path.suffix.lower()
    logger.info(f"Reading file: {file_path} (type: {ext})")

    if ext in (".xlsx", ".xlsm", ".xlsb"):
        return read_excel(file_path, sheet_name)
    elif ext == ".xls":
        return read_excel(file_path, sheet_name)
    elif ext in (".csv", ".tsv", ".txt", ".dat"):
        return read_csv(file_path)
    else:
        # Try to detect by reading first bytes
        try:
            with open(file_path, "rb") as f:
                header = f.read(8)
            # Excel magic bytes: PK (xlsx/zip) or D0CF11E0 (xls/OLE2)
            if header[:2] == b"PK":
                logger.info(f"Detected ZIP/XLSX format by magic bytes")
                return read_excel(file_path, sheet_name)
            elif header[:4] == b"\xd0\xcf\x11\xe0":
                logger.info(f"Detected OLE2/XLS format by magic bytes")
                return read_excel(file_path, sheet_name)
        except Exception:
            pass

        logger.warning(f"Unknown extension '{ext}', trying CSV reader")
        return read_csv(file_path)
