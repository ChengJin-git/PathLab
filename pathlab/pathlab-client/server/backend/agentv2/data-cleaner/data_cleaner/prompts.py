"""Centralized prompt management for PathLab Data Cleaner.

All prompts, helper functions, preset rules, and error fix templates
are maintained here for easy review and modification.
"""

from dataclasses import dataclass
from pathlib import Path

# Base directory for bundled templates
_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"


# ═══════════════════════════════════════════════════════════════
# 1. HELPER FUNCTIONS (injected into every generated script)
# ═══════════════════════════════════════════════════════════════

HELPER_FUNCTIONS = '''\
# ── Pre-defined helper functions (do NOT redefine) ──

def standardize_nulls(df):
    """Replace common null-like strings with proper NaN across all columns."""
    import numpy as np
    null_values = ["", "NA", "N/A", "n/a", "NULL", "null", "None", "none",
                   "nan", "NaN", "NAN", "-", "--", ".", "未知", "不详", "无"]
    for col in df.columns:
        df[col] = df[col].apply(
            lambda x: np.nan if (isinstance(x, str) and x.strip() in null_values) else x
        )
    return df

def standardize_gender(value):
    """Standardize gender values to Male/Female."""
    if not isinstance(value, str):
        return value
    v = value.strip().lower()
    if v in ("female", "f", "女", "女性"):
        return "Female"
    elif v in ("male", "m", "男", "男性"):
        return "Male"
    return value

def safe_numeric(value):
    """Convert a value to float, returning NaN if not possible."""
    import numpy as np
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return np.nan
    try:
        return float(str(value).replace(",", "").strip())
    except (ValueError, TypeError):
        return np.nan

def join_group_values(series, sep="/"):
    """Join non-null unique values in a Series with separator."""
    unique = series.dropna().unique()
    return sep.join(str(v) for v in unique) if len(unique) > 0 else None

def save_result(df, output_path, result_summary=""):
    """Save DataFrame to CSV and print summary."""
    df.to_csv(output_path, index=False)
    print(f"Saved to: {output_path}")
    print(f"Output: {len(df)} rows x {len(df.columns)} columns")
    print(f"Columns: {list(df.columns)}")
    if result_summary:
        print(result_summary)
'''


# ═══════════════════════════════════════════════════════════════
# 2. SYSTEM PROMPTS
# ═══════════════════════════════════════════════════════════════

CODEGEN_SYSTEM_PROMPT = """\
You are a senior Python data engineer. Generate a complete, self-contained
Python script that reads a messy data file and outputs a clean CSV.

## Rules

1. The script MUST read from the input path and save using `save_result(df, output_path)`.
2. Use ONLY: pandas, numpy, re, datetime, os, pathlib (already imported).
3. Do NOT use network calls, subprocess, or file deletion.
4. The following helper functions are ALREADY DEFINED (use them, do NOT redefine):
   - `standardize_nulls(df)` - replace null-like strings with NaN
   - `standardize_gender(value)` - normalize gender to Male/Female
   - `safe_numeric(value)` - safely convert to float
   - `join_group_values(series, sep="/")` - join unique non-null values
   - `save_result(df, output_path, result_summary="")` - save and print summary
5. Return ONLY the Python code. No explanations, no markdown fences.
6. Use the Schema section to understand column types precisely.
"""

TEMPLATE_SYSTEM_PROMPT = """\
You are a senior Python data engineer. Generate a complete, self-contained
Python script that transforms messy input data to EXACTLY match a template format.

## Rules

1. The script MUST read from input path and save using `save_result(df, output_path)`.
2. Use ONLY: pandas, numpy, re, datetime, os, pathlib.
3. Do NOT use network calls, subprocess, or file deletion.
4. The following helper functions are ALREADY DEFINED (use them, do NOT redefine):
   - `standardize_nulls(df)` - replace null-like strings with NaN
   - `standardize_gender(value)` - normalize gender to Male/Female
   - `safe_numeric(value)` - safely convert to float
   - `join_group_values(series, sep="/")` - join unique non-null values for multi-slide grouping
   - `save_result(df, output_path, result_summary="")` - save and print summary
5. Return ONLY the Python code. No explanations, no markdown fences.
6. Output MUST have the exact same columns (name + order) as the template.
7. For the `split` column: leave EMPTY. Post-processing assigns train/val/test.

## Mapping Strategy
- Match input columns to template columns by SEMANTIC meaning
- Transform values to match template's formatting conventions
- If no match for a template column, fill with NaN
- Drop columns not in the template
"""


# ═══════════════════════════════════════════════════════════════
# 3. USER PROMPT TEMPLATES
# ═══════════════════════════════════════════════════════════════

CODEGEN_USER_TEMPLATE = """\
Generate a cleaning script for this data.

## Paths
- Input: {input_path}
- Output: {output_path}

## Input Schema
{schema_text}

## Sample Data (first rows)
{sample_markdown}

## Analysis
{analysis_json}

Write the script. Use pre-defined helpers. Call `save_result(df, output_path)` at the end.
"""

TEMPLATE_USER_TEMPLATE = """\
Transform input to match the template.

## Paths
- Input: {input_path}
- Output: {output_path}

## Template (target format)
{template_schema}
{template_markdown}

## Input Schema
{schema_text}

## Input Sample Data
{sample_markdown}

## Analysis
{analysis_json}

## Rules
{extra_rules}

Write the transformation script. Use pre-defined helpers. Call `save_result(df, output_path)` at the end.
"""


# ═══════════════════════════════════════════════════════════════
# 4. ERROR FIX PROMPTS (typed by error category)
# ═══════════════════════════════════════════════════════════════

FIX_PARSE_ERROR_PROMPT = """\
The script failed with a FILE PARSING error:

```
{error}
```

The input file has ALREADY been pre-parsed into a clean CSV by our reader.
It is a standard CSV with header in row 0, comma-delimited, UTF-8 encoded.
Use `pd.read_csv(input_path)` with NO extra parameters (no skiprows, no header, no engine).

Previous script:
```python
{previous_code}
```

Fix and return ONLY the corrected Python code.
"""

FIX_TYPE_ERROR_PROMPT = """\
The script failed with a TYPE/VALUE error:

```
{error}
```

Common fixes:
- Use `.astype(str)` before string operations on mixed-type columns
- Use `safe_numeric(value)` instead of direct `float()` or `int()` conversion
- Check for NaN before comparisons: `if pd.notna(x):`
- Use `.fillna("")` before string join operations

Previous script:
```python
{previous_code}
```

Fix and return ONLY the corrected Python code.
"""

FIX_KEY_ERROR_PROMPT = """\
The script failed with a KEY/COLUMN error:

```
{error}
```

The input DataFrame has these columns: {available_columns}

Common fixes:
- Check column name spelling (case-sensitive)
- Use `df.columns` to verify actual column names
- Use fuzzy matching if column names have extra whitespace

Previous script:
```python
{previous_code}
```

Fix and return ONLY the corrected Python code.
"""

FIX_GENERIC_ERROR_PROMPT = """\
The script failed with an error:

```
{error}
```

Analysis of the data:
{analysis_json}

Previous script:
```python
{previous_code}
```

Fix and return ONLY the corrected Python code.
"""


# ═══════════════════════════════════════════════════════════════
# 5. PRESET RULES (task-specific transformation instructions)
# ═══════════════════════════════════════════════════════════════

WSI_CLASSIFICATION_RULES = """\
## Data Transformation Rules

### filename column
- Map from the WSI file column (look for columns containing .svs, .tiff, .ndpi, .mrxs filenames)
- Normalize to lowercase
- If a case_id has MULTIPLE slides (multiple rows with same case_id), GROUP them into ONE row
  and JOIN all filenames with "/" separator (e.g., "slide1.svs/slide2.svs/slide3.svs")
- Keep only the filename (not full path)

### split column
- Leave EMPTY (set to empty string). A separate post-processing step will assign train/val/test splits.
- Do NOT assign split values yourself.

### label column
- Map from diagnosis/label column
- Standardize cancer type labels:
  - Tumor-related diagnoses -> "Tumor" (e.g., IDC, DCIS, carcinoma, cancer, adenocarcinoma, SCC)
  - Normal/benign -> "Normal" (e.g., normal, benign, healthy, control)
  - If ambiguous, keep the original cleaned value
- Use title case (e.g., "Tumor", "Normal", "Adenocarcinoma")

### case_id column
- Map from patient ID column
- Standardize to uppercase
- Remove leading/trailing whitespace
- Replace NULL/null/NA/nan with proper NaN

### age column
- Must be numeric (integer or float)
- Parse Chinese age text (e.g., "六十七岁" -> 67)
- Remove non-numeric values, convert to NaN if invalid

### gender column
- Standardize to: "Male" or "Female" using `standardize_gender()`
- Unknown/missing -> NaN

### source column
- Extract cancer type / tissue origin from diagnosis
- Examples: "Breast Cancer - IDC" -> "Breast", "Lung adenocarcinoma" -> "Lung"
- If only one cancer type in the dataset, use that for all rows
- If unclear, use "Unknown"

### Grouping by case_id (IMPORTANT)
- First clean all columns individually
- Then group by case_id: use `join_group_values()` for wsi_file, take FIRST non-null value for other columns
- When aggregating, do NOT use string "first" — use actual first non-null value:
  ```python
  grouped = df.groupby('case_id').agg({
      'wsi_file': lambda x: join_group_values(x, '/'),
      'cancer_type': lambda x: x.dropna().iloc[0] if len(x.dropna()) > 0 else None,
      # ... same pattern for other columns
  }).reset_index()
  ```

### General
- Remove completely duplicate rows BEFORE grouping by case_id
- Remove rows where both wsi_file and case_id are missing/NaN
- Use `standardize_nulls(df)` first to clean all null-like values
- Use `safe_numeric()` for age and survival_months conversion
- Use `standardize_gender()` for sex column
"""

WSI_SURVIVAL_RULES = """\
## Data Transformation Rules

### filename column
- Map from WSI file column, normalize to lowercase
- If multiple slides per case, join with "/" separator using `join_group_values()`

### split column
- Leave EMPTY for post-processing assignment

### label column
- Map from diagnosis column, standardize to title case

### case_id column
- Map from patient ID, standardize to uppercase

### age column
- Numeric only, use `safe_numeric()`

### gender column
- Standardize using `standardize_gender()`

### survival_months column
- Must be numeric (float), use `safe_numeric()`
- Convert from days to months if values seem too large (> 200 likely days)

### vital_status column
- Standardize to: "Alive" or "Dead"
- Map: alive/living/存活/0 -> "Alive", dead/deceased/死亡/已故/1 -> "Dead"

### source column
- Extract tissue/cancer type from diagnosis

### General
- Use `standardize_nulls(df)` first
- Remove duplicate rows before grouping
"""

WSI_SEGMENTATION_RULES = """\
## Data Transformation Rules

### filename column
- Map from WSI file column, normalize to lowercase
- If multiple slides per case, join with "/" separator using `join_group_values()`

### split column
- Leave EMPTY for post-processing assignment

### mask_filename column
- Map from mask/annotation file column
- Should correspond to the WSI filename

### label column
- Map from diagnosis or annotation type column
- Standardize annotation categories

### case_id column
- Map from patient ID, standardize to uppercase

### source column
- Extract tissue/cancer type from diagnosis

### General
- Use `standardize_nulls(df)` first
- Remove duplicate rows before grouping
"""


# ═══════════════════════════════════════════════════════════════
# 6. PRESET REGISTRY
# ═══════════════════════════════════════════════════════════════

@dataclass
class Preset:
    """A built-in rule preset."""
    name: str
    description: str
    rules: str
    template_path: str = ""
    split_ratio: str = "7:1:2"
    no_split: bool = False


PRESETS = {
    "wsi": Preset(
        name="wsi",
        description="WSI classification (patient_id, wsi_file, cancer_type, tnm_stage, age, sex, ...)",
        rules=WSI_CLASSIFICATION_RULES,
        template_path=str(_TEMPLATES_DIR / "wsi_classification.csv"),
        split_ratio="7:1:2",
    ),
    "wsi-survival": Preset(
        name="wsi-survival",
        description="WSI with survival data (adds survival_months, vital_status)",
        rules=WSI_SURVIVAL_RULES,
        split_ratio="7:1:2",
    ),
    "wsi-seg": Preset(
        name="wsi-seg",
        description="WSI segmentation (adds mask_filename)",
        rules=WSI_SEGMENTATION_RULES,
        split_ratio="7:1:2",
    ),
}


def get_preset(name: str) -> Preset:
    """Get a preset by name."""
    if name not in PRESETS:
        available = ", ".join(PRESETS.keys())
        raise ValueError(f"Unknown preset '{name}'. Available: {available}")
    return PRESETS[name]


def list_presets() -> str:
    """List all available presets as formatted text."""
    lines = ["Available presets:", ""]
    for name, preset in PRESETS.items():
        lines.append(f"  {name:15s} - {preset.description}")
    return "\n".join(lines)
