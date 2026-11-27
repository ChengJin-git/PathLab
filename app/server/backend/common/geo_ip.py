import asyncio
import ipaddress
import time

import httpx

_ip_cache: dict[str, tuple[bool, float]] = {}
_CACHE_TTL_SECONDS = 3600

_circuit_failures = 0
_circuit_last_failure = 0.0
_CIRCUIT_BREAKER_THRESHOLD = 5
_CIRCUIT_BREAKER_TIMEOUT = 600


async def _fetch_ip_info(ip: str) -> dict:
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(f"http://ip-api.com/json/{ip}?fields=countryCode")
        response.raise_for_status()
        return response.json()


def _is_private_ip(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
        return addr.is_private or addr.is_loopback
    except ValueError:
        return True


def get_client_ip(request) -> str:
    headers = getattr(request, "headers", {})
    
    cf_ip = headers.get("cf-connecting-ip")
    if cf_ip:
        return cf_ip
    
    xff = headers.get("x-forwarded-for")
    if xff:
        for ip in reversed(xff.split(",")):
            ip = ip.strip()
            if ip and not _is_private_ip(ip):
                return ip
    
    xri = headers.get("x-real-ip")
    if xri:
        return xri
    
    client = getattr(request, "client", None)
    if client and hasattr(client, "host"):
        return client.host
    
    return ""


async def is_mainland_china_ip(ip: str) -> bool:
    if not ip or _is_private_ip(ip):
        return False
    
    now = time.time()
    cached = _ip_cache.get(ip)
    if cached and (now - cached[1]) < _CACHE_TTL_SECONDS:
        return cached[0]
    
    global _circuit_failures, _circuit_last_failure
    if _circuit_failures >= _CIRCUIT_BREAKER_THRESHOLD:
        if (now - _circuit_last_failure) < _CIRCUIT_BREAKER_TIMEOUT:
            return False
        else:
            _circuit_failures = 0
    
    try:
        data = await _fetch_ip_info(ip)
        country_code = data.get("countryCode", "")
        is_china = country_code == "CN"
        
        _ip_cache[ip] = (is_china, now)
        return is_china
    except Exception:
        _circuit_failures += 1
        _circuit_last_failure = now
        return False
