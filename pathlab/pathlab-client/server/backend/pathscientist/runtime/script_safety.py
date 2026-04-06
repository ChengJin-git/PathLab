"""
Auto Research Agent — Script Safety Analyzer

Pre-execution safety check for AI-generated training scripts.
Inspired by OpenHands SecurityAnalyzer + risk.py: layered risk assessment
catches dangerous patterns before they reach the sandbox.

Rules-based (faster and more reliable than LLM for this task).
"""
from __future__ import annotations

import ast
import logging
import re
from enum import IntEnum

logger = logging.getLogger(__name__)


class ScriptRisk(IntEnum):
    """Risk levels, ordered for max() comparison."""
    LOW = 0
    MEDIUM = 1
    HIGH = 2


# High risk: block execution, ask LLM to rewrite
HIGH_RISK_PATTERNS = [
    (r"subprocess\.(run|call|Popen|check_output)", "subprocess execution"),
    (r"os\.system\(", "os.system call"),
    (r"shutil\.rmtree\(", "recursive directory deletion"),
    (r"open\(.*/etc/", "reading system files"),
    (r"(?<!\w)socket\.", "raw socket access"),
    (r"urllib\.request", "network access via urllib"),
    (r"http\.client", "network access via http.client"),
]

# Medium risk: warn but allow (script runs in sandbox anyway)
MEDIUM_RISK_PATTERNS = [
    (r"(?<!\w)eval\(", "eval() call"),
    (r"__import__\(", "dynamic import"),
    (r"requests\.(get|post|put|delete)\(", "HTTP request (may fail in sandbox)"),
    (r"os\.(remove|unlink)\(", "file deletion"),
    (r"shutil\.(copy|move)\(", "file copy/move"),
    (r"os\.chmod\(", "permission change"),
]


def assess_script_risk(script: str) -> tuple[ScriptRisk, list[str]]:
    """Assess safety risk of an AI-generated training script.

    Inspired by OpenHands SecurityAnalyzer's layered risk assessment,
    but uses regex + AST rules instead of LLM (faster, deterministic).

    Returns:
        (risk_level, list_of_reasons)
    """
    reasons: list[str] = []
    risk = ScriptRisk.LOW

    # Regex pattern checks
    for pattern, desc in HIGH_RISK_PATTERNS:
        matches = re.findall(pattern, script)
        if matches:
            risk = ScriptRisk.HIGH
            reasons.append(f"HIGH: {desc} ({len(matches)}x)")

    if risk < ScriptRisk.HIGH:
        for pattern, desc in MEDIUM_RISK_PATTERNS:
            matches = re.findall(pattern, script)
            if matches:
                risk = max(risk, ScriptRisk.MEDIUM)
                reasons.append(f"MEDIUM: {desc} ({len(matches)}x)")

    # AST-level checks
    try:
        tree = ast.parse(script)
        for node in ast.walk(tree):
            # while True without break → potential infinite loop
            if isinstance(node, ast.While):
                if isinstance(node.test, ast.Constant) and node.test.value is True:
                    has_break = any(isinstance(n, ast.Break) for n in ast.walk(node))
                    if not has_break:
                        risk = max(risk, ScriptRisk.MEDIUM)
                        reasons.append("MEDIUM: while True without break")
    except SyntaxError:
        pass  # syntax errors are caught by _validate_code

    if reasons:
        logger.info(f"[script_safety] Risk={risk.name}, reasons={reasons}")

    return risk, reasons
