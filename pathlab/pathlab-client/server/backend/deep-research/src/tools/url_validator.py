# Copyright (c) 2025 PathLab
# URL validation tools for verifying link accessibility

import asyncio
import json
import logging
from typing import Optional, Type

import aiohttp
import requests
from langchain_core.callbacks import (
    AsyncCallbackManagerForToolRun,
    CallbackManagerForToolRun,
)
from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field
from src.tools.result_utils import (
    TOOL_STATUS_ERROR,
    TOOL_STATUS_SUCCESS,
    build_tool_result,
    parse_tool_result,
)

logger = logging.getLogger(__name__)

# Default timeout for URL validation
DEFAULT_TIMEOUT = 10

# User agent to avoid being blocked
DEFAULT_USER_AGENT = "Mozilla/5.0 (compatible; PathLab-LinkValidator/1.0)"


class URLValidationInput(BaseModel):
    """Input for URL validation."""
    url: str = Field(
        description="The URL to validate for accessibility"
    )


class URLValidationResult(BaseModel):
    """Result of URL validation."""
    url: str
    is_valid: bool
    status_code: Optional[int] = None
    error: Optional[str] = None
    final_url: Optional[str] = None  # If redirected
    content_type: Optional[str] = None


class ValidateURLTool(BaseTool):
    """Tool for validating if a URL is accessible."""
    
    name: str = "validate_url"
    description: str = (
        "Validate if a URL is accessible (returns HTTP 2xx/3xx). "
        "Use this to verify download links or references before including them in reports. "
        "Returns validation result with status code and any errors."
    )
    args_schema: Type[BaseModel] = URLValidationInput
    
    def _validate_url(self, url: str) -> dict:
        """Validate a single URL synchronously."""
        try:
            # Use HEAD request first (faster, no content download)
            response = requests.head(
                url,
                timeout=DEFAULT_TIMEOUT,
                allow_redirects=True,
                headers={"User-Agent": DEFAULT_USER_AGENT}
            )
            
            # Some servers don't support HEAD, fallback to GET
            if response.status_code == 405:
                response = requests.get(
                    url,
                    timeout=DEFAULT_TIMEOUT,
                    allow_redirects=True,
                    headers={"User-Agent": DEFAULT_USER_AGENT},
                    stream=True  # Don't download full content
                )
            
            is_valid = response.status_code < 400
            result = {
                "url": url,
                "is_valid": is_valid,
                "status_code": response.status_code,
            }
            
            # Add final URL if redirected
            if response.url != url:
                result["final_url"] = response.url
            
            # Add content type if available
            content_type = response.headers.get("Content-Type")
            if content_type:
                result["content_type"] = content_type.split(";")[0].strip()
            
            if not is_valid:
                result["error"] = f"HTTP {response.status_code}"
                
            return result
            
        except requests.Timeout:
            return {
                "url": url, 
                "is_valid": False, 
                "error": "Request timed out"
            }
        except requests.ConnectionError as e:
            return {
                "url": url, 
                "is_valid": False, 
                "error": f"Connection failed: {str(e)[:100]}"
            }
        except requests.RequestException as e:
            return {
                "url": url, 
                "is_valid": False, 
                "error": f"Request error: {str(e)[:100]}"
            }
        except Exception as e:
            logger.error(f"Unexpected error validating URL {url}: {e}")
            return {
                "url": url, 
                "is_valid": False, 
                "error": f"Unexpected error: {str(e)[:100]}"
            }
    
    def _run(
        self,
        url: str,
        run_manager: Optional[CallbackManagerForToolRun] = None,
    ) -> str:
        """Synchronous URL validation."""
        result = self._validate_url(url)
        return self._format_tool_result(result)
    
    async def _arun(
        self,
        url: str,
        run_manager: Optional[AsyncCallbackManagerForToolRun] = None,
    ) -> str:
        """Asynchronous URL validation."""
        try:
            timeout = aiohttp.ClientTimeout(total=DEFAULT_TIMEOUT)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                # Try HEAD first
                try:
                    async with session.head(
                        url,
                        allow_redirects=True,
                        headers={"User-Agent": DEFAULT_USER_AGENT}
                    ) as response:
                        # If HEAD returns 405, try GET
                        if response.status == 405:
                            async with session.get(
                                url,
                                allow_redirects=True,
                                headers={"User-Agent": DEFAULT_USER_AGENT}
                            ) as get_response:
                                return self._format_response(url, get_response)
                        return self._format_response(url, response)
                except aiohttp.ClientError:
                    # Fallback to GET if HEAD fails
                    async with session.get(
                        url,
                        allow_redirects=True,
                        headers={"User-Agent": DEFAULT_USER_AGENT}
                    ) as response:
                        return self._format_response(url, response)
                        
        except asyncio.TimeoutError:
            return self._format_tool_result({
                "url": url,
                "is_valid": False,
                "error": "Request timed out"
            })
        except aiohttp.ClientError as e:
            return self._format_tool_result({
                "url": url,
                "is_valid": False,
                "error": f"Connection failed: {str(e)[:100]}"
            })
        except Exception as e:
            logger.error(f"Unexpected error validating URL {url}: {e}")
            return self._format_tool_result({
                "url": url,
                "is_valid": False,
                "error": f"Unexpected error: {str(e)[:100]}"
            })
    
    def _format_response(self, original_url: str, response) -> str:
        """Format the validation response."""
        is_valid = response.status < 400
        result = {
            "url": original_url,
            "is_valid": is_valid,
            "status_code": response.status,
        }
        
        # Add final URL if redirected
        final_url = str(response.url)
        if final_url != original_url:
            result["final_url"] = final_url
        
        # Add content type
        content_type = response.headers.get("Content-Type")
        if content_type:
            result["content_type"] = content_type.split(";")[0].strip()
        
        if not is_valid:
            result["error"] = f"HTTP {response.status}"
            
        return self._format_tool_result(result)

    def _format_tool_result(self, result: dict) -> str:
        is_valid = bool(result.get("is_valid"))
        return build_tool_result(
            tool=self.name,
            status=TOOL_STATUS_SUCCESS if is_valid else TOOL_STATUS_ERROR,
            reason=None if is_valid else "validation_failed",
            summary="Source verified." if is_valid else (result.get("error") or "Source validation failed."),
            valid_for_research=False,
            data=result,
        )


# ============== Batch Validation ==============

class BatchURLValidationInput(BaseModel):
    """Input for batch URL validation."""
    urls: str = Field(
        description="Comma-separated list of URLs to validate, or a JSON array of URLs"
    )


class ValidateURLsBatchTool(BaseTool):
    """Tool for validating multiple URLs at once."""
    
    name: str = "validate_urls_batch"
    description: str = (
        "Validate multiple URLs at once for accessibility. "
        "Input can be comma-separated URLs or a JSON array. "
        "Returns validation results for all URLs."
    )
    args_schema: Type[BaseModel] = BatchURLValidationInput
    
    def _parse_urls(self, urls_input: str) -> list[str]:
        """Parse URLs from input string."""
        # Try JSON array first
        try:
            parsed = json.loads(urls_input)
            if isinstance(parsed, list):
                return [str(url).strip() for url in parsed if url]
        except json.JSONDecodeError:
            pass
        
        # Fallback to comma-separated
        return [url.strip() for url in urls_input.split(",") if url.strip()]
    
    def _run(
        self,
        urls: str,
        run_manager: Optional[CallbackManagerForToolRun] = None,
    ) -> str:
        """Synchronous batch validation."""
        url_list = self._parse_urls(urls)
        
        if not url_list:
            return build_tool_result(
                tool=self.name,
                status=TOOL_STATUS_ERROR,
                reason="invalid_input",
                summary="No valid URLs were provided.",
                valid_for_research=False,
                data={"results": []},
            )
        
        validator = ValidateURLTool()
        results = []
        
        for url in url_list[:10]:  # Limit to 10 URLs
            result_str = validator._run(url)
            parsed = parse_tool_result(result_str, validator.name)
            results.append(parsed.get("data", parsed) if isinstance(parsed, dict) else {"url": url, "is_valid": False})
        
        summary = {
            "total": len(results),
            "valid": sum(1 for r in results if r.get("is_valid")),
            "invalid": sum(1 for r in results if not r.get("is_valid")),
            "results": results
        }
        
        return build_tool_result(
            tool=self.name,
            status=TOOL_STATUS_SUCCESS if summary["valid"] else TOOL_STATUS_ERROR,
            reason=None if summary["valid"] else "validation_failed",
            summary=f"Validated {summary['total']} URL(s).",
            valid_for_research=False,
            data=summary,
        )
    
    async def _arun(
        self,
        urls: str,
        run_manager: Optional[AsyncCallbackManagerForToolRun] = None,
    ) -> str:
        """Asynchronous batch validation (concurrent)."""
        url_list = self._parse_urls(urls)
        
        if not url_list:
            return build_tool_result(
                tool=self.name,
                status=TOOL_STATUS_ERROR,
                reason="invalid_input",
                summary="No valid URLs were provided.",
                valid_for_research=False,
                data={"results": []},
            )
        
        # Limit to 10 URLs to avoid overwhelming servers
        url_list = url_list[:10]
        
        async def validate_single(url: str) -> dict:
            validator = ValidateURLTool()
            result_str = await validator._arun(url)
            parsed = parse_tool_result(result_str, validator.name)
            return parsed.get("data", parsed) if isinstance(parsed, dict) else {"url": url, "is_valid": False}
        
        # Run all validations concurrently
        results = await asyncio.gather(
            *[validate_single(url) for url in url_list],
            return_exceptions=True
        )
        
        # Handle any exceptions
        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                processed_results.append({
                    "url": url_list[i],
                    "is_valid": False,
                    "error": str(result)
                })
            else:
                processed_results.append(result)
        
        summary = {
            "total": len(processed_results),
            "valid": sum(1 for r in processed_results if r.get("is_valid")),
            "invalid": sum(1 for r in processed_results if not r.get("is_valid")),
            "results": processed_results
        }
        
        return build_tool_result(
            tool=self.name,
            status=TOOL_STATUS_SUCCESS if summary["valid"] else TOOL_STATUS_ERROR,
            reason=None if summary["valid"] else "validation_failed",
            summary=f"Validated {summary['total']} URL(s).",
            valid_for_research=False,
            data=summary,
        )


# ============== Factory Functions ==============

def get_url_validator_tool() -> ValidateURLTool:
    """Get the single URL validator tool."""
    return ValidateURLTool()
