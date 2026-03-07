# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import logging
from typing import Any
from typing import List, Optional, Type

from langchain_core.callbacks import (
    AsyncCallbackManagerForToolRun,
    CallbackManagerForToolRun,
)
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from src.config.tools import SELECTED_RAG_PROVIDER
from src.rag import Document, Resource, Retriever, build_retriever
from src.tools.result_utils import (
    MIN_RETRIEVER_CONTENT_LENGTH,
    TOOL_STATUS_NO_RESULTS,
    TOOL_STATUS_SUCCESS,
    build_tool_result,
)

logger = logging.getLogger(__name__)


class RetrieverInput(BaseModel):
    keywords: str = Field(description="search keywords to look up")


class RetrieverTool(BaseTool):
    name: str = "local_search_tool"
    description: str = "Useful for retrieving information from the file with `rag://` uri prefix, it should be higher priority than the web search or writing code. Input should be a search keywords."
    args_schema: Type[BaseModel] = RetrieverInput

    retriever: Retriever = Field(default_factory=Retriever)
    resources: list[Resource] = Field(default_factory=list)

    def _format_documents_result(self, documents: list[dict[str, Any]], keywords: str) -> str:
        useful_documents = [
            doc
            for doc in documents
            if isinstance(doc, dict)
            and isinstance(doc.get("content"), str)
            and len(doc["content"].strip()) >= MIN_RETRIEVER_CONTENT_LENGTH
        ]
        if not documents:
            return build_tool_result(
                tool=self.name,
                status=TOOL_STATUS_NO_RESULTS,
                reason="no_matches",
                summary="No relevant local documents were found.",
                valid_for_research=False,
                data={"keywords": keywords, "documents": [], "counts": {"total": 0, "useful": 0}},
            )
        return build_tool_result(
            tool=self.name,
            status=TOOL_STATUS_SUCCESS if useful_documents else TOOL_STATUS_NO_RESULTS,
            reason=None if useful_documents else "insufficient_documents",
            summary="Local retrieval completed." if useful_documents else "Documents were found, but none contained enough useful content.",
            valid_for_research=bool(useful_documents),
            data={
                "keywords": keywords,
                "documents": documents,
                "counts": {"total": len(documents), "useful": len(useful_documents)},
            },
        )

    def _run(
        self,
        keywords: str,
        run_manager: Optional[CallbackManagerForToolRun] = None,
    ) -> list[Document]:
        logger.info(
            f"Retriever tool query: {keywords}", extra={"resources": self.resources}
        )
        documents = self.retriever.query_relevant_documents(keywords, self.resources)
        return self._format_documents_result([doc.to_dict() for doc in documents], keywords)

    async def _arun(
        self,
        keywords: str,
        run_manager: Optional[AsyncCallbackManagerForToolRun] = None,
    ) -> list[Document]:
        logger.info(
            f"Retriever tool query: {keywords}", extra={"resources": self.resources}
        )
        documents = await self.retriever.query_relevant_documents_async(
            keywords, self.resources
        )
        return self._format_documents_result([doc.to_dict() for doc in documents], keywords)


def get_retriever_tool(resources: List[Resource]) -> RetrieverTool | None:
    if not resources:
        return None
    logger.info(f"create retriever tool: {SELECTED_RAG_PROVIDER}")
    retriever = build_retriever()

    if not retriever:
        return None
    return RetrieverTool(retriever=retriever, resources=resources)
