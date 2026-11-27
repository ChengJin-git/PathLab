"""Language selection for the capability-based prompt composer."""
import re

_CJK = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")
_TRADITIONAL = frozenset("書學國會點說開認車錢醫電對陽圖從問個與長設還進關頭種達區計資遠際幾時論環廠節權備術確機園間變報職記連構業總愛選裝層歷華發師議響單識這裡來為麼現證幫實網頁訓練資料標註")


def detect_language(text: str) -> str:
    characters = _CJK.findall(text or "")
    visible = re.sub(r"\s", "", text or "")
    if not visible or len(characters) / len(visible) < 0.3:
        return "en"
    return "zh_HK" if sum(char in _TRADITIONAL for char in characters) / len(characters) >= 0.3 else "zh_CN"
