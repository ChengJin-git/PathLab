import base64
from pathlib import Path
from functools import lru_cache

from backend.common.config import Config
from .dependencies import logger


DEFAULT_EMAIL_TEMPLATES = {
    "new_user_registration_notice": {
        "subject": "PathLab account application received",
        "html": (
            "<div style='font-family:Arial,sans-serif;max-width:600px;margin:0 auto;'>"
            "{logo_html}"
            "<p>Dear {display_name},</p>"
            "<p>We have received your PathLab account application. "
            "Your request is pending administrator review. You will receive another "
            "email once your account is activated.</p>"
            "<p style='color:#555;'>- PathLab</p>"
            "</div>"
        ),
    },
    "account_activated": {
        "subject": "Your PathLab account has been activated",
        "html": (
            "<div style='font-family:Arial,sans-serif;max-width:600px;margin:0 auto;'>"
            "{logo_html}"
            "<p>Dear {display_name},</p>"
            "<p>Your PathLab account <strong>{username}</strong> has been activated. "
            "You can now log in to the platform.</p>"
            "<p style='color:#555;'>- PathLab</p>"
            "</div>"
        ),
    },
    "task_completed_notice": {
        "subject": "[PathLab] Task completed: {task_name}",
        "html": (
            "<div style='font-family:Arial,sans-serif;max-width:600px;margin:0 auto;'>"
            "{logo_html}"
            "<p>Dear {display_name},</p>"
            "<p>Your task <strong>{task_name}</strong> has completed successfully.</p>"
            "<p style='color:#555;'>- PathLab</p>"
            "</div>"
        ),
    },
    "admin_new_user_registration_notice": {
        "subject": "[PathLab] New account application: {username}",
        "html": (
            "<div style='font-family:Arial,sans-serif;max-width:600px;margin:0 auto;'>"
            "<p style='font-weight:600;color:#1e293b;font-size:16px;'>"
            "New Account Application</p>"
            "<table style='border-collapse:collapse;width:100%;margin:16px 0;'>"
            "<tr><td style='padding:8px 12px;background:#f8fafc;border:1px solid #e2e8f0;font-weight:600;width:140px;'>"
            "Username</td><td style='padding:8px 12px;border:1px solid #e2e8f0;'>{username}</td></tr>"
            "<tr><td style='padding:8px 12px;background:#f8fafc;border:1px solid #e2e8f0;font-weight:600;'>"
            "Display Name</td><td style='padding:8px 12px;border:1px solid #e2e8f0;'>{display_name}</td></tr>"
            "<tr><td style='padding:8px 12px;background:#f8fafc;border:1px solid #e2e8f0;font-weight:600;'>"
            "Contact Email</td><td style='padding:8px 12px;border:1px solid #e2e8f0;'>{registration_email}</td></tr>"
            "</table>"
            "<p>Please review and activate or reject this application in the admin panel.</p>"
            "<p style='color:#555;'>- PathLab</p>"
            "</div>"
        ),
    },
}


_LEGAL_FOOTER_HTML = (
    "<hr style='border:none;border-top:1px solid #e0e0e0;margin:32px 0 16px'>"
    "<p style='font-size:11px;color:#999;line-height:1.6;font-family:Arial,sans-serif;'>"
    "This message contains confidential information intended for a specific individual "
    "and purpose. If you are not the intended recipient, you should delete this message "
    "and notify the sender, "
    "<a href='https://smartlab.cse.ust.hk/' style='color:#999;'>SmartLab</a>, "
    "and The Hong Kong University of Science and Technology (the University) immediately. "
    "Any disclosure, copying, or distribution of this message, or the taking of any action "
    "based on it, is strictly prohibited and may be unlawful.<br><br>"
    "SmartLab and the University specifically deny any responsibility for the accuracy or "
    "quality of information obtained through University E-mail Facilities. Any views and "
    "opinions expressed are only those of the author(s) and do not necessarily represent "
    "those of SmartLab or the University, and neither SmartLab nor the University accepts "
    "liability whatsoever for any losses or damages incurred or caused to any party as a "
    "result of the use of such information."
    "</p>"
)


class _SafeMap(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def _resend_enabled(settings: dict) -> bool:
    return bool(settings.get("resend_enabled") and settings.get("resend_api_key"))


def _merge_templates(settings: dict) -> dict:
    custom = settings.get("email_templates")
    merged = {k: dict(v) for k, v in DEFAULT_EMAIL_TEMPLATES.items()}
    if not isinstance(custom, dict):
        return merged
    for key, payload in custom.items():
        if key not in merged or not isinstance(payload, dict):
            continue
        subject = payload.get("subject")
        html = payload.get("html")
        if isinstance(subject, str) and subject.strip():
            merged[key]["subject"] = subject
        if isinstance(html, str) and html.strip():
            merged[key]["html"] = html
    return merged


@lru_cache(maxsize=1)
def _load_logo_data_uri() -> str:
    image_path = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "renderer"
        / "public"
        / "images"
        / "pathlab-logo.png"
    )
    if not image_path.exists():
        return ""
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _logo_html() -> str:
    logo_url = _load_logo_data_uri()
    if not logo_url:
        return ""
    return (
        f"<img src='{logo_url}' "
        "alt='PathLab' style='height:40px;width:auto;margin-bottom:24px;' /><br>"
    )


def _render(raw: str, context: dict) -> str:
    return raw.format_map(_SafeMap(context))


async def send_templated_email(
    template_key: str,
    to_email: str,
    context: dict,
    for_admin: bool,
) -> None:
    settings = Config.get_global_settings()
    if not _resend_enabled(settings):
        return
    if not to_email:
        logger.info(f"[email:{template_key}] skipped: empty recipient")
        return

    templates = _merge_templates(settings)
    tpl = templates.get(template_key)
    if not tpl:
        logger.warning(f"[email:{template_key}] skipped: template not found")
        return

    payload = {
        **context,
        "logo_html": _logo_html(),
    }
    subject = _render(tpl.get("subject", ""), payload)
    html = _render(tpl.get("html", ""), payload) + _LEGAL_FOOTER_HTML
    if not subject.strip() or not html.strip():
        logger.info(f"[email:{template_key}] skipped: empty rendered content")
        return

    try:
        import resend as _resend

        _resend.api_key = settings["resend_api_key"]
        from_addr = (
            "PathLab Agent <notify@pathub.org>"
            if for_admin
            else "PathLab Admin <noreply@pathhub.org>"
        )
        _resend.Emails.send(
            {
                "from": from_addr,
                "to": [to_email],
                "subject": subject,
                "html": html,
            }
        )
    except Exception as exc:
        logger.warning(f"[email:{template_key}] failed for {to_email}: {exc}")
