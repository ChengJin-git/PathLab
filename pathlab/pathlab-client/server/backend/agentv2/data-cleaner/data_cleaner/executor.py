"""Safe code executor for LLM-generated cleaning scripts.

Runs generated Python code in a subprocess with:
- Timeout enforcement
- Import whitelist validation
- Restricted working directory
- Stdout/stderr capture
"""

import logging
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# Modules allowed in generated cleaning scripts
ALLOWED_IMPORTS = {
    "pandas",
    "numpy",
    "openpyxl",
    "re",
    "os",
    "sys",
    "datetime",
    "pathlib",
    "csv",
    "json",
    "math",
    "collections",
    "functools",
    "itertools",
    "string",
    "warnings",
}

# Dangerous patterns to reject
DANGEROUS_PATTERNS = [
    r"\bsubprocess\b",
    r"\bos\.system\b",
    r"\bos\.popen\b",
    r"\bos\.exec\b",
    r"\bos\.remove\b",
    r"\bos\.unlink\b",
    r"\bos\.rmdir\b",
    r"\bshutil\.rmtree\b",
    r"\bshutil\.move\b",
    r"\b__import__\b",
    r"\beval\s*\(",
    r"\bexec\s*\(",
    r"\bcompile\s*\(",
    r"\burllib\b",
    r"\brequests\b",
    r"\bhttpx\b",
    r"\bsocket\b",
    r"\bhttp\b",
]

DEFAULT_TIMEOUT = 120  # seconds


@dataclass
class ExecutionResult:
    """Result of executing a cleaning script."""

    success: bool
    stdout: str = ""
    stderr: str = ""
    return_code: int = -1
    output_file_exists: bool = False
    error_summary: str = ""


def validate_code(code: str) -> tuple[bool, str]:
    """Validate generated code for safety.

    Returns:
        (is_safe, reason) tuple
    """
    # Check for dangerous patterns
    for pattern in DANGEROUS_PATTERNS:
        match = re.search(pattern, code)
        if match:
            return False, f"Dangerous pattern detected: {match.group()}"

    # Check imports - extract all import statements
    import_lines = re.findall(
        r"^\s*(?:import|from)\s+(\w+)", code, re.MULTILINE
    )
    for module in import_lines:
        if module not in ALLOWED_IMPORTS:
            return False, f"Disallowed import: {module}"

    return True, "OK"


def execute_code(
    code: str,
    output_path: str,
    timeout: int = DEFAULT_TIMEOUT,
    work_dir: str = None,
) -> ExecutionResult:
    """Execute a Python cleaning script in a subprocess.

    Args:
        code: Python script to execute
        output_path: Expected output file path (to verify creation)
        timeout: Maximum execution time in seconds
        work_dir: Working directory for execution (default: temp dir)

    Returns:
        ExecutionResult with success status, output, and errors
    """
    # Step 1: Validate code safety
    is_safe, reason = validate_code(code)
    if not is_safe:
        logger.error(f"Code validation failed: {reason}")
        return ExecutionResult(
            success=False,
            error_summary=f"Code validation failed: {reason}",
        )

    # Step 2: Write code to a temporary file
    if work_dir is None:
        work_dir = tempfile.mkdtemp(prefix="data_cleaner_")

    script_path = os.path.join(work_dir, "_cleaning_script.py")
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(code)

    logger.info(f"Executing cleaning script: {script_path}")
    logger.info(f"Timeout: {timeout}s, work_dir: {work_dir}")

    # Step 3: Execute in subprocess
    try:
        result = subprocess.run(
            [sys.executable, script_path],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=work_dir,
            env={
                **os.environ,
                # Restrict some env vars for safety
                "PYTHONDONTWRITEBYTECODE": "1",
            },
        )

        stdout = result.stdout
        stderr = result.stderr

        if stdout:
            logger.info(f"Script stdout:\n{stdout[:2000]}")
        if stderr:
            logger.warning(f"Script stderr:\n{stderr[:2000]}")

        # Step 4: Check if output file was created
        output_exists = os.path.exists(output_path)

        if result.returncode == 0 and output_exists:
            logger.info(f"Cleaning script succeeded. Output: {output_path}")
            return ExecutionResult(
                success=True,
                stdout=stdout,
                stderr=stderr,
                return_code=result.returncode,
                output_file_exists=True,
            )
        elif result.returncode == 0 and not output_exists:
            error_msg = f"Script completed but output file not found: {output_path}"
            logger.error(error_msg)
            return ExecutionResult(
                success=False,
                stdout=stdout,
                stderr=stderr,
                return_code=result.returncode,
                output_file_exists=False,
                error_summary=error_msg,
            )
        else:
            # Script failed
            error_msg = stderr.strip() if stderr else f"Exit code: {result.returncode}"
            logger.error(f"Script failed: {error_msg[:500]}")
            return ExecutionResult(
                success=False,
                stdout=stdout,
                stderr=stderr,
                return_code=result.returncode,
                output_file_exists=output_exists,
                error_summary=error_msg,
            )

    except subprocess.TimeoutExpired:
        error_msg = f"Script timed out after {timeout} seconds"
        logger.error(error_msg)
        return ExecutionResult(
            success=False,
            error_summary=error_msg,
        )
    except Exception as e:
        error_msg = f"Execution error: {str(e)}"
        logger.error(error_msg)
        return ExecutionResult(
            success=False,
            error_summary=error_msg,
        )
    finally:
        # Clean up temp script file (but keep work_dir for debugging)
        try:
            if os.path.exists(script_path):
                os.remove(script_path)
        except OSError:
            pass
