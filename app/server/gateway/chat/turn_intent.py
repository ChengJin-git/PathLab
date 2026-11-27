"""Cheap routing for standalone introduction and inventory questions.

Full matches keep specific dataset questions and mixed action requests on the
normal workflow path. These routes do not generate canned answers.
"""

import re
from typing import Literal


def _normalized(text: str) -> str:
    return re.sub(r"[\s?!？！，,。.!]+", " ", text.casefold()).strip()


def is_assistant_introduction(text: str) -> bool:
    normalized = _normalized(text)
    return bool(
        re.fullmatch(
            r"(?:你好\s*)?(?:请|請)?(?:你是谁|你是誰|你是什么助手|你是什麼助手|"
            r"介绍一下你自己|介紹一下你自己|介绍一下自己|介紹一下自己|你能做什么|你能做什麼|你能帮我做什么|你能幫我做什麼)"
            r"|(?:hi\s+|hello\s+)?(?:who are you|introduce yourself|what can you do|what can you help me with)",
            normalized,
        )
    )


def dataset_overview_kind(text: str) -> Literal["count", "list"] | None:
    normalized = _normalized(text)
    subject = r"(?:(?:我|我们|我們)(?:现在|現在|目前|当前|當前)?(?:一共|总共|總共)?(?:有|能看到|可以用|能用)?|(?:当前|當前|这个|這個)工作区(?:里|裡)?(?:有)?)"
    resource = r"(?:数据集|資料集|数据|資料|图像|影像|图片|圖片|切片)(?:和(?:图像|影像|图片|圖片|切片))?"
    if re.fullmatch(subject + r"(?:多少|几个|幾個|几张|幾張)" + resource, normalized):
        return "count"
    if re.fullmatch(subject + r"(?:哪些|什么|什麼|啥)" + resource, normalized):
        return "list"
    if re.fullmatch(
        r"(?:请|請)?(?:列出|看看|看一下)(?:我的|当前|當前)?(?:全部|所有)?(?:数据集|資料集|数据|資料)",
        normalized,
    ):
        return "list"
    resources = r"(?:data\s*sets?|data|images|slides)"
    if re.fullmatch(
        r"how (?:many|much) "
        + resources
        + r" (?:do (?:i|we) have|are (?:there|available)(?: in (?:this|my|the) workspace)?)",
        normalized,
    ):
        return "count"
    if re.fullmatch(
        r"(?:what|which) "
        + resources
        + r" (?:do (?:i|we) have|are available(?: to me)?)",
        normalized,
    ):
        return "list"
    if re.fullmatch(
        r"(?:please )?(?:list|show)(?: me)? (?:my|our|all(?: my)?|available) "
        + resources,
        normalized,
    ):
        return "list"
    return None
