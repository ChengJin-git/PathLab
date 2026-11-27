"""Server-side execution-card boundary; natural-language decisions stay with the LLM."""

import re

GPU_TAGS = (
    "TASK_CONFIG",
    "SUBMIT_TASK",
    "ANALYSIS_CONFIG",
    "BATCH_INFERENCE_CONFIG",
    "PATCH_INFERENCE",
    "QUICK_ANALYSIS_CONFIG",
    "SUBMIT_ANALYSIS",
    "SUBMIT_BATCH_INFERENCE",
    "RESEARCH_RUN",
)


def strip_execution_cards(content, language):
    blocked = any(f"[{tag}]" in content for tag in GPU_TAGS)
    if re.search(r'\[NAVIGATE\].*?"type"\s*:\s*"research"', content, re.S):
        blocked = True
    if not blocked:
        return content
    return {
        "en": "Your current guest account cannot submit GPU or autonomous tasks. Please contact an administrator to enable access. I can help you prepare the analysis plan or explain existing results.",
        "zh_CN": "你当前使用的是访客账号，暂时没有提交 GPU 或自动任务的权限。请联系管理员开通；我可以先帮你整理分析方案或解读已有结果。",
        "zh_HK": "你目前使用的是訪客帳號，暫時沒有提交 GPU 或自動任務的權限。請聯絡管理員開通；我可以先協助整理分析方案或解讀已有結果。",
    }[language]
