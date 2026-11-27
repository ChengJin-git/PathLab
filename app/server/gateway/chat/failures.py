"""Localized operation failures independent of another successful model turn."""

from backend.services.articles.errors import failure_code
from fastapi import HTTPException


def language_index(language):
    return (
        2 if language in {"zh_HK", "zh-HK"} else 1 if language.startswith("zh") else 0
    )


# (verified cause, practical next step), never raw exception strings or URLs.
CAUSES = {
    "access_denied": (
        (
            "The source refused automatic access.",
            "You can upload a copy you can access, or provide another accessible source.",
        ),
        ("来源拒绝了自动访问。", "可以上传你能访问的原文，或提供另一个可访问的来源。"),
        ("來源拒絕了自動存取。", "可以上傳你能存取的原文，或提供另一個可存取的來源。"),
    ),
    "not_found": (
        (
            "The source was not found or has been removed.",
            "Check the original link or upload the document.",
        ),
        ("来源不存在或已被移除。", "请核对原链接，或上传原始文档。"),
        ("來源不存在或已被移除。", "請核對原連結，或上傳原始文件。"),
    ),
    "rate_limited": (
        (
            "The source is limiting requests.",
            "Please retry later; existing results are retained.",
        ),
        ("来源暂时限制了请求频率。", "请稍后重试，已有结果会保留。"),
        ("來源暫時限制了請求頻率。", "請稍後重試，已有結果會保留。"),
    ),
    "request_timeout": (
        (
            "The source did not respond in time.",
            "Retry later, or upload the original document for reading.",
        ),
        ("来源响应超时。", "可以稍后重试，或上传原始文档继续阅读。"),
        ("來源回應逾時。", "可以稍後重試，或上傳原始文件繼續閱讀。"),
    ),
    "network_unreachable": (
        (
            "The source could not be reached.",
            "Check the connection or provide an accessible copy.",
        ),
        ("暂时无法连接到来源。", "请检查连接，或提供可访问的副本。"),
        ("暫時無法連接至來源。", "請檢查連線，或提供可存取的副本。"),
    ),
    "source_unavailable": (
        (
            "The source service is unavailable.",
            "Please retry later or use another source.",
        ),
        ("来源服务暂时不可用。", "请稍后重试，或使用其他来源。"),
        ("來源服務暫時不可用。", "請稍後重試，或使用其他來源。"),
    ),
    "parse_timeout": (
        (
            "The PDF was retrieved, but text extraction timed out.",
            "Retry reading it later, or provide the relevant pages or text.",
        ),
        ("PDF 已取得，但正文解析超时。", "可稍后重试阅读，或提供相关页面、文字。"),
        ("PDF 已取得，但正文解析逾時。", "可稍後重試閱讀，或提供相關頁面、文字。"),
    ),
    "parse_busy": (
        (
            "The document reader is busy.",
            "Please retry reading shortly; do not resubmit the same download.",
        ),
        ("文档读取服务当前繁忙。", "请稍后重试阅读，无需重复提交同一下载。"),
        ("文件讀取服務目前繁忙。", "請稍後重試閱讀，無需重複提交同一下載。"),
    ),
    "parse_failed": (
        (
            "The document text could not be extracted.",
            "Provide a readable PDF or the relevant pages/text.",
        ),
        ("未能提取文档正文。", "可以提供可读取的 PDF 或相关页面、文字。"),
        ("未能擷取文件正文。", "可以提供可讀取的 PDF 或相關頁面、文字。"),
    ),
    "empty_content": (
        (
            "No readable text was returned.",
            "Provide the original document or relevant text.",
        ),
        ("没有取得可读取的正文。", "请提供原始文档或相关文字。"),
        ("沒有取得可讀取的正文。", "請提供原始文件或相關文字。"),
    ),
    "unreadable_page": (
        (
            "The page did not expose readable article text.",
            "Upload the original or provide an accessible full-text link.",
        ),
        ("页面没有提供可提取的正文。", "可以上传原文，或提供可访问的全文链接。"),
        ("頁面沒有提供可擷取的正文。", "可以上傳原文，或提供可存取的全文連結。"),
    ),
    "no_pdf": (
        (
            "No original PDF was available at this source.",
            "Provide a direct PDF link or upload the original; a webpage is not a downloaded PDF.",
        ),
        (
            "没有从该来源取得原始 PDF。",
            "请提供 PDF 直链或上传原文，网页内容不能替代 PDF 下载。",
        ),
        (
            "沒有從該來源取得原始 PDF。",
            "請提供 PDF 直連或上傳原文，網頁內容不能替代 PDF 下載。",
        ),
    ),
    "content_too_large": (
        (
            "The document exceeds the reading size limit.",
            "Provide the relevant pages or a smaller document.",
        ),
        ("文档超过了读取大小限制。", "可以提供相关页面或较小的文档。"),
        ("文件超過了讀取大小限制。", "可以提供相關頁面或較小的文件。"),
    ),
    "blocked_url": (
        (
            "This link cannot be fetched automatically.",
            "Provide a public document link or upload an authorized copy.",
        ),
        ("此链接无法自动获取。", "请提供公开文档链接，或上传有权使用的副本。"),
        ("此連結無法自動取得。", "請提供公開文件連結，或上傳有權使用的副本。"),
    ),
    "disabled": (
        (
            "This capability is disabled in the current workspace.",
            "Enable it in the workspace controls if appropriate, or use the available inputs.",
        ),
        (
            "当前工作区未启用这项能力。",
            "如需使用，可在工作区设置中启用；也可以继续使用已有材料。",
        ),
        (
            "目前工作區未啟用這項能力。",
            "如需使用，可在工作區設定中啟用；也可以繼續使用已有材料。",
        ),
    ),
    "not_configured": (
        (
            "This service has not been configured.",
            "Ask an administrator to configure it; you can continue with existing materials.",
        ),
        ("这项服务尚未配置。", "请联系管理员完成配置，也可以先使用已有材料。"),
        ("這項服務尚未設定。", "請聯絡管理員完成設定，也可以先使用已有材料。"),
    ),
    "permission_denied": (
        (
            "Your current permissions do not allow this operation.",
            "Ask an administrator to check access; existing resources remain available.",
        ),
        ("当前权限不允许执行此操作。", "请联系管理员核对访问权限，已有资源会保留。"),
        ("目前權限不允許執行此操作。", "請聯絡管理員核對存取權限，已有資源會保留。"),
    ),
    "invalid_request": (
        (
            "The requested operation could not be prepared.",
            "Please retry the reply; nothing new was submitted.",
        ),
        ("未能准备好这项操作。", "请重试这条回答，尚未提交新的任务。"),
        ("未能準備好這項操作。", "請重試這條回覆，尚未提交新的任務。"),
    ),
    "resource_changed": (
        (
            "The selected resource changed or is no longer available.",
            "Refresh and select the current resource before retrying.",
        ),
        ("所选资源已变化或不可用。", "请刷新并选择当前资源后重试。"),
        ("所選資源已變更或無法使用。", "請重新整理並選取目前資源後重試。"),
    ),
    "storage_full": (
        (
            "There is not enough storage to save the file.",
            "Ask an administrator to free storage, then retry saving.",
        ),
        ("存储空间不足，文件未能保存。", "请联系管理员清理空间后重试保存。"),
        ("儲存空間不足，檔案未能儲存。", "請聯絡管理員清理空間後重試儲存。"),
    ),
    "storage_failed": (
        (
            "The file could not be saved.",
            "Please retry saving; contact an administrator if this continues.",
        ),
        ("文件未能保存。", "请重试保存；若持续失败，请联系管理员检查存储。"),
        ("檔案未能儲存。", "請重試儲存；若持續失敗，請聯絡管理員檢查儲存。"),
    ),
    "unexpected_error": (
        (
            "The operation could not be completed this time.",
            "Please retry; existing files and results are retained.",
        ),
        ("这次未能完成操作。", "请重试，已有文件和结果会保留。"),
        ("這次未能完成操作。", "請重試，已有檔案和結果會保留。"),
    ),
}

OPERATIONS = {
    "read": ("Document reading incomplete", "文档读取未完成", "文件讀取未完成"),
    "download": ("Document download incomplete", "文档下载未完成", "文件下載未完成"),
    "search": ("Search incomplete", "检索未完成", "檢索未完成"),
    "tool": ("Tool operation incomplete", "工具操作未完成", "工具操作未完成"),
    "context": (
        "Resource lookup incomplete",
        "资源信息读取未完成",
        "資源資訊讀取未完成",
    ),
    "save": ("File delivery incomplete", "文件交付未完成", "檔案交付未完成"),
    "handoff": ("Autonomous task not started", "自主任务未启动", "自主任務未啟動"),
}

OPERATION_CAUSES = {
    ("search", "request_timeout"): (
        (
            "The search service timed out.",
            "Retry later or continue with existing evidence; no new sources were retrieved.",
        ),
        ("检索服务响应超时。", "可稍后重试或先使用已有证据，本次没有取得新来源。"),
        ("檢索服務回應逾時。", "可稍後重試或先使用已有證據，本次沒有取得新來源。"),
    ),
    ("search", "access_denied"): (
        (
            "The search service rejected access.",
            "Ask an administrator to check the connector settings; existing materials remain available.",
        ),
        ("检索服务拒绝了访问。", "请联系管理员检查连接器设置，已有材料仍可使用。"),
        ("檢索服務拒絕了存取。", "請聯絡管理員檢查連接器設定，已有材料仍可使用。"),
    ),
    ("handoff", "rate_limited"): (
        (
            "The task queue is full.",
            "Wait for capacity, or finish/pause an existing task before retrying.",
        ),
        ("当前任务队列已满。", "可等待空位，或结束、暂停已有任务后重试。"),
        ("目前任務佇列已滿。", "可等候空位，或結束、暫停已有任務後重試。"),
    ),
    ("handoff", "source_unavailable"): (
        (
            "The execution service is unavailable.",
            "Check the execution environment in Settings, or retry later.",
        ),
        ("后台执行服务暂时不可用。", "请在设置中检查执行环境，或稍后重试。"),
        ("背景執行服務暫時無法使用。", "請在設定中檢查執行環境，或稍後重試。"),
    ),
}


def exception_code(error):
    if isinstance(error, HTTPException):
        return {
            401: "permission_denied",
            403: "permission_denied",
            404: "not_found",
            409: "resource_changed",
            422: "invalid_request",
            429: "rate_limited",
        }.get(error.status_code, "source_unavailable")
    if isinstance(error, (ValueError, TypeError)):
        return "invalid_request"
    return failure_code(error)


def operation_failure(operation, language, code="unexpected_error", *, title=""):
    index = language_index(language)
    cause, recovery = OPERATION_CAUSES.get(
        (operation, code), CAUSES.get(code, CAUSES["unexpected_error"])
    )[index]
    label = OPERATIONS[operation][index]
    if title:
        label += " · " + " ".join(str(title).split())[:120]
    return {
        "code": code,
        "message": f"{label}：{cause}" if index else f"{label}: {cause}",
        "recovery_hint": recovery,
    }


def failure_text(failure):
    return failure["message"] + " " + failure["recovery_hint"]


def recovery_instruction(failure):
    return (
        "Operation failed; the user has already received this exact notice: "
        + failure_text(failure)
        + "\nUse only completed evidence/files. Do not repeat this notice, retry the identical request, invent missing content, "
        "or auto-start research because of an operational failure. Continue independent parts of the original goal when useful; "
        "otherwise give a concise recovery next step. Do not replace current/source-specific facts with model memory."
    )
