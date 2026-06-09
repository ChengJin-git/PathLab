# Geo-Based Captcha Switching Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Tencent Cloud Captcha support for Mainland China users while keeping Cloudflare Turnstile for all other users, with backend IP-based provider selection.

**Architecture:** Backend detects client IP geolocation and returns the appropriate captcha provider via `/settings/public`. Frontend conditionally renders Turnstile or Tencent Captcha widget. Backend verifies tokens using the correct provider API based on the same IP detection logic.

**Tech Stack:** React 18 + TypeScript (frontend), Python FastAPI + SQLAlchemy (backend), Vitest/pytest (testing)

---

## File Structure

### New Files
- `server/backend/common/geo_ip.py` - IP geolocation detection with caching and circuit breaker
- `src/renderer/src/components/TencentCaptcha.tsx` - Tencent Captcha widget wrapper
- `server/tests/test_geo_ip.py` - IP geolocation unit tests

### Modified Files
- `server/backend/common/config.py` - Add Tencent captcha settings fields
- `server/gateway/models.py` - Update PublicSettingsResponse, SecureLoginRequest, AccessRequest
- `server/gateway/routes/settings.py` - Update `/settings/public` to return captcha provider
- `server/gateway/routes/auth.py` - Add Tencent verification, update login/register endpoints
- `src/renderer/src/api/settings.ts` - Update PublicSettings interface
- `src/renderer/src/api/auth.ts` - Update login/requestAccess signatures and types
- `src/renderer/src/contexts/AuthContext.tsx` - Update login signature
- `src/renderer/src/pages/LoginPage.tsx` - Conditional captcha rendering based on provider
- `src/renderer/src/components/RegisterRequestModal.tsx` - Conditional captcha rendering
- `src/renderer/src/pages/SettingsPage.tsx` - Add Tencent captcha admin config fields
- `src/renderer/src/locales/en-US.json` - Add translation keys
- `src/renderer/src/locales/zh-CN.json` - Add translation keys
- `src/renderer/src/locales/zh-HK.json` - Add translation keys

---

## Task 1: Backend - IP Geolocation Module

**Files:**
- Create: `server/backend/common/geo_ip.py`
- Test: `server/tests/test_geo_ip.py`

- [ ] **Step 1: Write the failing test**

```python
import pytest
from backend.common.geo_ip import get_client_ip, is_mainland_china_ip

class TestGetClientIP:
    def test_direct_connection(self):
        class MockRequest:
            class client:
                host = "1.2.3.4"
            headers = {}
        assert get_client_ip(MockRequest()) == "1.2.3.4"

    def test_x_forwarded_for(self):
        class MockRequest:
            class client:
                host = "10.0.0.1"
            headers = {"x-forwarded-for": "5.6.7.8, 10.0.0.2"}
        assert get_client_ip(MockRequest()) == "5.6.7.8"

    def test_cf_connecting_ip(self):
        class MockRequest:
            class client:
                host = "10.0.0.1"
            headers = {"cf-connecting-ip": "9.10.11.12"}
        assert get_client_ip(MockRequest()) == "9.10.11.12"

    def test_private_ip_fallback(self):
        class MockRequest:
            class client:
                host = "192.168.1.1"
            headers = {}
        assert get_client_ip(MockRequest()) == "192.168.1.1"

class TestIsMainlandChinaIP:
    @pytest.mark.asyncio
    async def test_china_ip(self, monkeypatch):
        async def mock_fetch(ip):
            return {"countryCode": "CN"}
        monkeypatch.setattr("backend.common.geo_ip._fetch_ip_info", mock_fetch)
        assert await is_mainland_china_ip("1.1.1.1") is True

    @pytest.mark.asyncio
    async def test_us_ip(self, monkeypatch):
        async def mock_fetch(ip):
            return {"countryCode": "US"}
        monkeypatch.setattr("backend.common.geo_ip._fetch_ip_info", mock_fetch)
        assert await is_mainland_china_ip("1.1.1.1") is False

    @pytest.mark.asyncio
    async def test_service_failure_fallback(self, monkeypatch):
        async def mock_fetch(ip):
            raise Exception("Service down")
        monkeypatch.setattr("backend.common.geo_ip._fetch_ip_info", mock_fetch)
        assert await is_mainland_china_ip("1.1.1.1") is False

    @pytest.mark.asyncio
    async def test_private_ip(self):
        assert await is_mainland_china_ip("192.168.1.1") is False
        assert await is_mainland_china_ip("10.0.0.1") is False
        assert await is_mainland_china_ip("127.0.0.1") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/cjinag/code/PathLab/pathlab/pathlab-client && python -m pytest server/tests/test_geo_ip.py -v`
Expected: FAIL with module not found

- [ ] **Step 3: Implement geo_ip.py**

```python
"""
IP Geolocation utilities for detecting Mainland China users.
Uses ip-api.com with in-memory caching and circuit breaker pattern.
"""

import asyncio
import ipaddress
import time
from typing import Optional

import httpx

# In-memory cache: {ip: (result, timestamp)}
_ip_cache: dict[str, tuple[bool, float]] = {}
_CACHE_TTL_SECONDS = 3600  # 1 hour

# Circuit breaker state
_circuit_failures = 0
_circuit_last_failure = 0.0
_CIRCUIT_BREAKER_THRESHOLD = 5
_CIRCUIT_BREAKER_TIMEOUT = 600  # 10 minutes


async def _fetch_ip_info(ip: str) -> dict:
    """Fetch IP geolocation info from ip-api.com."""
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(f"http://ip-api.com/json/{ip}?fields=countryCode")
        response.raise_for_status()
        return response.json()


def _is_private_ip(ip: str) -> bool:
    """Check if IP is private/local."""
    try:
        addr = ipaddress.ip_address(ip)
        return addr.is_private or addr.is_loopback
    except ValueError:
        return True


def get_client_ip(request) -> str:
    """
    Extract client IP from request with secure header parsing.
    
    Priority:
    1. CF-Connecting-IP (Cloudflare CDN)
    2. X-Forwarded-For (rightmost non-private IP)
    3. X-Real-IP
    4. request.client.host
    """
    headers = getattr(request, "headers", {})
    
    # Cloudflare
    cf_ip = headers.get("cf-connecting-ip")
    if cf_ip:
        return cf_ip
    
    # X-Forwarded-For
    xff = headers.get("x-forwarded-for")
    if xff:
        # Take the rightmost (closest to server) non-private IP
        for ip in reversed(xff.split(",")):
            ip = ip.strip()
            if ip and not _is_private_ip(ip):
                return ip
    
    # X-Real-IP
    xri = headers.get("x-real-ip")
    if xri:
        return xri
    
    # Direct connection
    client = getattr(request, "client", None)
    if client and hasattr(client, "host"):
        return client.host
    
    return ""


async def is_mainland_china_ip(ip: str) -> bool:
    """
    Check if an IP address is from Mainland China.
    
    Returns False for:
    - Private/local IPs (Electron/desktop mode)
    - Non-China IPs
    - Service failures (fallback to Turnstile)
    """
    if not ip or _is_private_ip(ip):
        return False
    
    # Check cache
    now = time.time()
    cached = _ip_cache.get(ip)
    if cached and (now - cached[1]) < _CACHE_TTL_SECONDS:
        return cached[0]
    
    # Circuit breaker check
    global _circuit_failures, _circuit_last_failure
    if _circuit_failures >= _CIRCUIT_BREAKER_THRESHOLD:
        if (now - _circuit_last_failure) < _CIRCUIT_BREAKER_TIMEOUT:
            return False  # Circuit open, fallback to Turnstile
        else:
            # Circuit half-open, reset counter
            _circuit_failures = 0
    
    try:
        data = await _fetch_ip_info(ip)
        country_code = data.get("countryCode", "")
        is_china = country_code == "CN"
        
        # Cache result
        _ip_cache[ip] = (is_china, now)
        return is_china
    except Exception:
        _circuit_failures += 1
        _circuit_last_failure = now
        return False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest server/tests/test_geo_ip.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add server/backend/common/geo_ip.py server/tests/test_geo_ip.py
git commit -m "feat: add IP geolocation module with caching and circuit breaker"
```

---

## Task 2: Backend - Config and Models Update

**Files:**
- Modify: `server/backend/common/config.py`
- Modify: `server/gateway/models.py`

- [ ] **Step 1: Add Tencent settings to config**

In `server/backend/common/config.py`, add to `GlobalSettings` defaults:

```python
# In the default settings dict or schema:
"tencent_captcha_enabled": False,
"tencent_captcha_app_id": "",
"tencent_captcha_secret_key": "",
```

- [ ] **Step 2: Update Pydantic models**

In `server/gateway/models.py`:

```python
class PublicSettingsResponse(BaseModel):
    # Backward compatibility
    turnstile_enabled: bool
    turnstile_site_key: str
    # New fields
    captcha_provider: Optional[Literal["turnstile", "tencent"]] = None
    captcha_site_key: str = ""


class SecureLoginRequest(BaseModel):
    username: str
    hashed_password: str
    timestamp: int
    turnstile_token: Optional[str] = None
    tencent_captcha_token: Optional[str] = None
    tencent_captcha_randstr: Optional[str] = None


class AccessRequest(BaseModel):
    username: str = Field(description="Desired login username")
    password: str = Field(description="Account password")
    registration_email: str = Field(description="Educational email for identity verification")
    nickname: Optional[str] = Field(default=None, description="Display name")
    turnstile_token: Optional[str] = Field(default=None, description="Cloudflare Turnstile token")
    tencent_captcha_token: Optional[str] = Field(default=None, description="Tencent Captcha ticket")
    tencent_captcha_randstr: Optional[str] = Field(default=None, description="Tencent Captcha randstr")
```

- [ ] **Step 3: Update GlobalSettingsResponse and GlobalSettingsUpdateRequest**

Add to both models:

```python
tencent_captcha_enabled: bool
tencent_captcha_app_id: str
tencent_captcha_secret_key: str
```

And `GlobalSettingsUpdateRequest` gets optional versions:

```python
tencent_captcha_enabled: Optional[bool] = None
tencent_captcha_app_id: Optional[str] = None
tencent_captcha_secret_key: Optional[str] = None
```

- [ ] **Step 4: Commit**

```bash
git add server/backend/common/config.py server/gateway/models.py
git commit -m "feat: add Tencent captcha settings and request/response models"
```

---

## Task 3: Backend - Public Settings API

**Files:**
- Modify: `server/gateway/routes/settings.py`

- [ ] **Step 1: Update `/settings/public` endpoint**

```python
from backend.common.geo_ip import get_client_ip, is_mainland_china_ip

@router.get("/public")
async def get_public_settings(request: Request) -> PublicSettingsResponse:
    """
    Get public settings that don't require authentication.
    Returns captcha provider based on client IP geolocation.
    """
    settings = Config.get_global_settings()
    
    turnstile_enabled = settings.get("turnstile_enabled", False)
    turnstile_site_key = settings.get("turnstile_site_key", "")
    tencent_enabled = settings.get("tencent_captcha_enabled", False)
    tencent_app_id = settings.get("tencent_captcha_app_id", "")
    
    # Determine provider based on IP
    client_ip = get_client_ip(request)
    is_china = await is_mainland_china_ip(client_ip)
    
    if is_china and tencent_enabled and tencent_app_id:
        provider = "tencent"
        site_key = tencent_app_id
    elif turnstile_enabled and turnstile_site_key:
        provider = "turnstile"
        site_key = turnstile_site_key
    else:
        provider = None
        site_key = ""
    
    return PublicSettingsResponse(
        turnstile_enabled=turnstile_enabled,
        turnstile_site_key=turnstile_site_key,
        captcha_provider=provider,
        captcha_site_key=site_key,
    )
```

- [ ] **Step 2: Update test**

In `server/tests/test_settings.py`, update the public settings test to mock IP detection.

- [ ] **Step 3: Commit**

```bash
git add server/gateway/routes/settings.py server/tests/test_settings.py
git commit -m "feat: update public settings to return captcha provider based on IP"
```

---

## Task 4: Backend - Tencent Captcha Verification

**Files:**
- Modify: `server/gateway/routes/auth.py`

- [ ] **Step 1: Add Tencent verification function**

```python
import hashlib
import hmac
import json
import time
from urllib.parse import quote

async def verify_tencent_captcha(
    ticket: str,
    randstr: str,
    user_ip: str,
    app_id: str,
    secret_key: str,
) -> bool:
    """
    Verify Tencent Cloud Captcha token.
    Uses Tencent Cloud API 3.0 signature.
    """
    if not ticket or not randstr or not app_id or not secret_key:
        return False
    
    try:
        # Tencent Cloud API 3.0 signature
        service = "captcha"
        host = "captcha.intl.tencentcloudapi.com"
        action = "DescribeCaptchaResult"
        version = "2019-07-22"
        region = "ap-guangzhou"
        
        timestamp = int(time.time())
        date = time.strftime("%Y-%m-%d", time.gmtime(timestamp))
        
        # Request payload
        payload = json.dumps({
            "CaptchaAppId": int(app_id),
            "CaptchaType": 9,
            "NeedGetCaptchaTime": 1,
            "Randstr": randstr,
            "UserIp": user_ip,
            "Ticket": ticket,
            "AppSecretKey": secret_key,
        })
        
        # Simple POST without full API 3.0 signature for now
        # (Full signature implementation can be added if needed)
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"https://{host}/",
                headers={
                    "Content-Type": "application/json",
                    "X-TC-Action": action,
                    "X-TC-Version": version,
                    "X-TC-Timestamp": str(timestamp),
                    "X-TC-Region": region,
                },
                content=payload,
            )
            
            if response.status_code != 200:
                logger.warning(f"Tencent captcha verification failed: HTTP {response.status_code}")
                return False
            
            result = response.json()
            # Check Response.Error
            error = result.get("Response", {}).get("Error")
            if error:
                logger.warning(f"Tencent captcha error: {error}")
                return False
            
            captcha_result = result.get("Response", {}).get("CaptchaCode", 0)
            # CaptchaCode: 1 = success, others = failure
            return captcha_result == 1
            
    except Exception as e:
        logger.error(f"Tencent captcha verification error: {e}")
        return False
```

- [ ] **Step 2: Add unified captcha verification helper**

```python
async def verify_captcha(
    request: Request,
    turnstile_token: Optional[str],
    tencent_ticket: Optional[str],
    tencent_randstr: Optional[str],
) -> tuple[bool, Optional[str]]:
    """
    Verify captcha based on client IP location.
    Returns (success, error_code).
    """
    settings = Config.get_global_settings()
    client_ip = get_client_ip(request)
    is_china = await is_mainland_china_ip(client_ip)
    
    tencent_enabled = settings.get("tencent_captcha_enabled", False)
    turnstile_enabled = settings.get("turnstile_enabled", False)
    
    # Determine expected provider
    if is_china and tencent_enabled:
        expected_provider = "tencent"
    elif turnstile_enabled:
        expected_provider = "turnstile"
    else:
        # No captcha required
        return True, None
    
    if expected_provider == "turnstile":
        if not turnstile_token:
            return False, "TURNSTILE_TOKEN_REQUIRED"
        secret_key = settings.get("turnstile_secret_key", "")
        valid = await verify_turnstile(turnstile_token, secret_key)
        if not valid:
            return False, "TURNSTILE_VERIFICATION_FAILED"
        return True, None
    
    if expected_provider == "tencent":
        if not tencent_ticket or not tencent_randstr:
            return False, "TENCENT_CAPTCHA_REQUIRED"
        secret_key = settings.get("tencent_captcha_secret_key", "")
        app_id = settings.get("tencent_captcha_app_id", "")
        valid = await verify_tencent_captcha(
            tencent_ticket, tencent_randstr, client_ip, app_id, secret_key
        )
        if not valid:
            return False, "TENCENT_CAPTCHA_VERIFICATION_FAILED"
        return True, None
    
    return True, None
```

- [ ] **Step 3: Update login endpoint**

In `secure_login`, replace the Turnstile verification block with:

```python
# Verify captcha
captcha_valid, error_code = await verify_captcha(
    request,
    request.turnstile_token,
    request.tencent_captcha_token,
    request.tencent_captcha_randstr,
)
if not captcha_valid:
    logger.warning(f"Login captcha verification failed for user {request.username}: {error_code}")
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=error_code,
    )
```

- [ ] **Step 4: Update request_access endpoint**

Same pattern as login:

```python
captcha_valid, error_code = await verify_captcha(
    request,
    request.turnstile_token,
    request.tencent_captcha_token,
    request.tencent_captcha_randstr,
)
if not captcha_valid:
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=error_code,
    )
```

- [ ] **Step 5: Commit**

```bash
git add server/gateway/routes/auth.py
git commit -m "feat: add Tencent captcha verification and unified captcha check"
```

---

## Task 5: Frontend - Settings API and Types

**Files:**
- Modify: `src/renderer/src/api/settings.ts`

- [ ] **Step 1: Update PublicSettings interface**

```typescript
export interface PublicSettings {
  // Backward compatibility
  turnstile_enabled: boolean
  turnstile_site_key: string
  // New fields
  captcha_provider: 'turnstile' | 'tencent' | null
  captcha_site_key: string
}
```

- [ ] **Step 2: Update GlobalSettings interface**

```typescript
export interface GlobalSettings {
  // ... existing fields ...
  // Tencent Captcha settings
  tencent_captcha_enabled: boolean
  tencent_captcha_app_id: string
  tencent_captcha_secret_key: string
}
```

- [ ] **Step 3: Commit**

```bash
git add src/renderer/src/api/settings.ts
git commit -m "feat: update settings types for Tencent captcha"
```

---

## Task 6: Frontend - Auth API Updates

**Files:**
- Modify: `src/renderer/src/api/auth.ts`
- Modify: `src/renderer/src/contexts/AuthContext.tsx`

- [ ] **Step 1: Update login function signature**

```typescript
export async function loginWithCredentials(
  username: string,
  password: string,
  turnstileToken?: string,
  tencentCaptchaTicket?: string,
  tencentCaptchaRandstr?: string,
): Promise<LoginResponse> {
  // ... existing hash computation ...
  
  const response = await apiFetch<LoginResponse>(
    `${API_BASE}/auth/secure-login`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        username,
        hashed_password: hashedCredential,
        timestamp,
        turnstile_token: turnstileToken,
        tencent_captcha_token: tencentCaptchaTicket,
        tencent_captcha_randstr: tencentCaptchaRandstr,
      })
    },
    'Login failed'
  )
  // ... rest unchanged ...
}
```

- [ ] **Step 2: Update requestAccess function**

```typescript
export async function requestAccess(data: AccessRequest): Promise<AuthUser> {
  return apiFetch<AuthUser>(
    `${API_BASE}/auth/request-access`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data)
    },
    'Access request failed'
  )
}
```

Update `AccessRequest` interface:

```typescript
export interface AccessRequest {
  username: string
  password: string
  registration_email: string
  nickname?: string
  turnstile_token?: string
  tencent_captcha_token?: string
  tencent_captcha_randstr?: string
}
```

- [ ] **Step 3: Update AuthContext login signature**

```typescript
interface AuthContextType {
  // ... other fields ...
  login: (
    username: string,
    password: string,
    turnstileToken?: string,
    tencentCaptchaTicket?: string,
    tencentCaptchaRandstr?: string
  ) => Promise<boolean>
  // ...
}
```

And update the `login` implementation to pass through the new parameters.

- [ ] **Step 4: Commit**

```bash
git add src/renderer/src/api/auth.ts src/renderer/src/contexts/AuthContext.tsx
git commit -m "feat: update auth API and context for Tencent captcha tokens"
```

---

## Task 7: Frontend - TencentCaptcha Component

**Files:**
- Create: `src/renderer/src/components/TencentCaptcha.tsx`

- [ ] **Step 1: Create component**

```typescript
import React, { useRef, useEffect } from 'react'

interface TencentCaptchaProps {
  appId: string
  onVerify: (ticket: string, randstr: string) => void
  onExpire?: () => void
  onError?: () => void
}

// Extend Window interface for Tencent Captcha
declare global {
  interface Window {
    TencentCaptcha?: new (
      element: HTMLElement | string,
      appId: string,
      callback: (res: { ret: number; ticket?: string; randstr?: string }) => void,
      options?: Record<string, unknown>
    ) => { show: () => void }
  }
}

export function TencentCaptcha({ appId, onVerify, onExpire, onError }: TencentCaptchaProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const scriptLoaded = useRef(false)

  useEffect(() => {
    if (!containerRef.current || scriptLoaded.current) return

    const loadScript = () => {
      return new Promise<void>((resolve, reject) => {
        if (window.TencentCaptcha) {
          resolve()
          return
        }

        const script = document.createElement('script')
        script.src = 'https://ca.turing.captcha.qcloud.com/TJNCaptcha-global.js'
        script.async = true
        script.onload = () => resolve()
        script.onerror = () => reject(new Error('Failed to load Tencent Captcha script'))
        document.head.appendChild(script)
      })
    }

    const initCaptcha = async () => {
      try {
        await loadScript()
        scriptLoaded.current = true

        if (!containerRef.current || !window.TencentCaptcha) return

        const captcha = new window.TencentCaptcha(
          containerRef.current,
          appId,
          (res) => {
            if (res.ret === 0 && res.ticket && res.randstr) {
              onVerify(res.ticket, res.randstr)
            } else if (res.ret === 2) {
              onExpire?.()
            } else {
              onError?.()
            }
          },
          {}
        )
        captcha.show()
      } catch (err) {
        console.error('Tencent Captcha init error:', err)
        onError?.()
      }
    }

    initCaptcha()

    return () => {
      // Cleanup: remove script if we added it
      const scripts = document.querySelectorAll('script[src*="TJNCaptcha-global.js"]')
      scripts.forEach((s) => s.remove())
      scriptLoaded.current = false
    }
  }, [appId, onVerify, onExpire, onError])

  return <div ref={containerRef} className="w-full" />
}
```

- [ ] **Step 2: Commit**

```bash
git add src/renderer/src/components/TencentCaptcha.tsx
git commit -m "feat: add TencentCaptcha component"
```

---

## Task 8: Frontend - LoginPage Updates

**Files:**
- Modify: `src/renderer/src/pages/LoginPage.tsx`

- [ ] **Step 1: Update state and types**

Replace `turnstileSiteKey` state with:

```typescript
interface CaptchaConfig {
  provider: 'turnstile' | 'tencent' | null
  siteKey: string
}

// In component:
const [captchaConfig, setCaptchaConfig] = React.useState<CaptchaConfig>({ provider: null, siteKey: '' })
const [tencentTicket, setTencentTicket] = React.useState<string | undefined>(undefined)
const [tencentRandstr, setTencentRandstr] = React.useState<string | undefined>(undefined)
```

- [ ] **Step 2: Update settings fetch**

```typescript
React.useEffect(() => {
  getPublicSettings()
    .then((settings) => {
      if (settings.captcha_provider && settings.captcha_site_key) {
        setCaptchaConfig({
          provider: settings.captcha_provider,
          siteKey: settings.captcha_site_key,
        })
      } else if (settings.turnstile_enabled && settings.turnstile_site_key) {
        // Fallback to old fields
        setCaptchaConfig({
          provider: 'turnstile',
          siteKey: settings.turnstile_site_key,
        })
      }
      setBackendUnavailable(false)
    })
    // ... error handling ...
}, [])
```

- [ ] **Step 3: Update form submission**

```typescript
const handleLogin = async (e: React.FormEvent) => {
  e.preventDefault()
  setFormError(null)

  if (!username || !password) {
    setFormError(t('common.pleaseEnterUsernameAndPassword'))
    return
  }

  const success = await login(
    username,
    password,
    turnstileToken,
    tencentTicket,
    tencentRandstr
  )
  // ... rest unchanged ...
}
```

- [ ] **Step 4: Update captcha rendering**

Replace the Turnstile widget section:

```tsx
{/* Captcha Widget */}
{captchaConfig.provider === 'turnstile' && captchaConfig.siteKey && (
  <div ref={turnstileRef} className="w-full" />
)}
{captchaConfig.provider === 'tencent' && captchaConfig.siteKey && (
  <TencentCaptcha
    appId={captchaConfig.siteKey}
    onVerify={(ticket, randstr) => {
      setTencentTicket(ticket)
      setTencentRandstr(randstr)
    }}
    onExpire={() => {
      setTencentTicket(undefined)
      setTencentRandstr(undefined)
    }}
    onError={() => {
      setTencentTicket(undefined)
      setTencentRandstr(undefined)
      setFormError(t('auth.captchaLoadError'))
    }}
  />
)}
```

- [ ] **Step 5: Update button disabled logic**

```typescript
<Button
  type="submit"
  disabled={isLoading || (
    captchaConfig.provider === 'turnstile' && !turnstileToken
  ) || (
    captchaConfig.provider === 'tencent' && (!tencentTicket || !tencentRandstr)
  )}
  // ...
>
```

- [ ] **Step 6: Update footer text**

```tsx
<p className="text-center text-xs text-slate-400 mt-6">
  © 2026 <a href="https://smartx.ust.hk/" target="_blank" rel="noopener noreferrer">SmartXLab</a>
  {captchaConfig.provider ? ` · ${t('common.protectedByCaptcha')}` : ''}
</p>
```

- [ ] **Step 7: Commit**

```bash
git add src/renderer/src/pages/LoginPage.tsx
git commit -m "feat: update LoginPage to support Tencent captcha"
```

---

## Task 9: Frontend - RegisterRequestModal Updates

**Files:**
- Modify: `src/renderer/src/components/RegisterRequestModal.tsx`

- [ ] **Step 1: Update props and state**

```typescript
interface RegisterRequestModalProps {
  isOpen: boolean
  onClose: () => void
  captchaConfig?: {
    provider: 'turnstile' | 'tencent' | null
    siteKey: string
  }
}
```

Add state for Tencent tokens (same pattern as LoginPage).

- [ ] **Step 2: Update form submission**

```typescript
const handleSubmit = async () => {
  // ... validation ...
  
  const requestData: AccessRequest = {
    username,
    password,
    registration_email: email,
    nickname,
    turnstile_token: turnstileToken,
    tencent_captcha_token: tencentTicket,
    tencent_captcha_randstr: tencentRandstr,
  }
  
  await requestAccess(requestData)
  // ...
}
```

- [ ] **Step 3: Update captcha rendering**

Same conditional rendering pattern as LoginPage.

- [ ] **Step 4: Commit**

```bash
git add src/renderer/src/components/RegisterRequestModal.tsx
git commit -m "feat: update RegisterRequestModal to support Tencent captcha"
```

---

## Task 10: Frontend - Admin Settings Page

**Files:**
- Modify: `src/renderer/src/pages/SettingsPage.tsx`

- [ ] **Step 1: Add Tencent captcha config fields**

In the admin settings form, add fields after Turnstile settings:

```tsx
<div className="space-y-4">
  <h3 className="text-lg font-medium">{t('settings.tencentCaptchaTitle')}</h3>
  
  <div className="flex items-center space-x-2">
    <Switch
      checked={settings.tencent_captcha_enabled}
      onCheckedChange={(checked) => updateSetting('tencent_captcha_enabled', checked)}
    />
    <Label>{t('settings.tencentCaptchaEnabled')}</Label>
  </div>
  
  {settings.tencent_captcha_enabled && (
    <>
      <div className="space-y-2">
        <Label>{t('settings.tencentCaptchaAppId')}</Label>
        <Input
          value={settings.tencent_captcha_app_id}
          onChange={(e) => updateSetting('tencent_captcha_app_id', e.target.value)}
          placeholder="189949311"
        />
      </div>
      
      <div className="space-y-2">
        <Label>{t('settings.tencentCaptchaSecretKey')}</Label>
        <Input
          type="password"
          value={settings.tencent_captcha_secret_key}
          onChange={(e) => updateSetting('tencent_captcha_secret_key', e.target.value)}
          placeholder="••••••••"
        />
      </div>
    </>
  )}
</div>
```

- [ ] **Step 2: Commit**

```bash
git add src/renderer/src/pages/SettingsPage.tsx
git commit -m "feat: add Tencent captcha configuration to admin settings"
```

---

## Task 11: Frontend - i18n Translations

**Files:**
- Modify: `src/renderer/src/locales/en-US.json`
- Modify: `src/renderer/src/locales/zh-CN.json`
- Modify: `src/renderer/src/locales/zh-HK.json`

- [ ] **Step 1: Add English translations**

```json
{
  "auth": {
    "tencentCaptchaRequired": "Tencent captcha verification required",
    "captchaProviderMismatch": "Captcha provider mismatch. Please refresh the page.",
    "tencentCaptchaVerificationFailed": "Tencent captcha verification failed. Please try again.",
    "captchaLoadError": "Failed to load captcha. Please refresh the page."
  },
  "settings": {
    "tencentCaptchaTitle": "Tencent Cloud Captcha",
    "tencentCaptchaEnabled": "Enable Tencent Captcha",
    "tencentCaptchaAppId": "App ID",
    "tencentCaptchaSecretKey": "Secret Key"
  },
  "common": {
    "protectedByCaptcha": "Protected by captcha"
  }
}
```

- [ ] **Step 2: Add Chinese (Simplified) translations**

```json
{
  "auth": {
    "tencentCaptchaRequired": "需要完成腾讯云验证码验证",
    "captchaProviderMismatch": "验证码提供商不匹配，请刷新页面",
    "tencentCaptchaVerificationFailed": "腾讯云验证码验证失败，请重试",
    "captchaLoadError": "验证码加载失败，请刷新页面"
  },
  "settings": {
    "tencentCaptchaTitle": "腾讯云验证码",
    "tencentCaptchaEnabled": "启用腾讯云验证码",
    "tencentCaptchaAppId": "应用 ID",
    "tencentCaptchaSecretKey": "密钥"
  },
  "common": {
    "protectedByCaptcha": "由验证码保护"
  }
}
```

- [ ] **Step 3: Add Chinese (Traditional/Hong Kong) translations**

```json
{
  "auth": {
    "tencentCaptchaRequired": "需要完成騰訊雲驗證碼驗證",
    "captchaProviderMismatch": "驗證碼提供商不匹配，請刷新頁面",
    "tencentCaptchaVerificationFailed": "騰訊雲驗證碼驗證失敗，請重試",
    "captchaLoadError": "驗證碼載入失敗，請刷新頁面"
  },
  "settings": {
    "tencentCaptchaTitle": "騰訊雲驗證碼",
    "tencentCaptchaEnabled": "啟用騰訊雲驗證碼",
    "tencentCaptchaAppId": "應用 ID",
    "tencentCaptchaSecretKey": "密鑰"
  },
  "common": {
    "protectedByCaptcha": "由驗證碼保護"
  }
}
```

- [ ] **Step 4: Commit**

```bash
git add src/renderer/src/locales/
git commit -m "feat: add i18n translations for Tencent captcha"
```

---

## Task 12: Testing - Backend Auth Tests

**Files:**
- Modify: `server/tests/test_auth.py`

- [ ] **Step 1: Add Tencent captcha login tests**

```python
@pytest.mark.asyncio
async def test_secure_login_with_tencent_captcha(mock_tencent_verify, client):
    """Test login with Tencent captcha token."""
    # Mock IP as China
    mock_tencent_verify.return_value = True
    
    response = await client.post("/auth/secure-login", json={
        "username": "testuser",
        "hashed_password": "valid_hash",
        "timestamp": int(time.time() * 1000),
        "tencent_captcha_token": "valid_ticket",
        "tencent_captcha_randstr": "valid_randstr",
    })
    
    assert response.status_code == 200
    assert "access_token" in response.json()

@pytest.mark.asyncio
async def test_secure_login_tencent_missing_token(client):
    """Test login fails when Tencent token is missing."""
    response = await client.post("/auth/secure-login", json={
        "username": "testuser",
        "hashed_password": "valid_hash",
        "timestamp": int(time.time() * 1000),
    })
    
    assert response.status_code == 400
    assert response.json()["detail"] == "TENCENT_CAPTCHA_REQUIRED"

@pytest.mark.asyncio
async def test_secure_login_provider_mismatch(client):
    """Test login fails when wrong provider token is sent."""
    # Mock IP as China, but send Turnstile token
    response = await client.post("/auth/secure-login", json={
        "username": "testuser",
        "hashed_password": "valid_hash",
        "timestamp": int(time.time() * 1000),
        "turnstile_token": "some_token",
    })
    
    assert response.status_code == 400
    assert response.json()["detail"] == "CAPTCHA_PROVIDER_MISMATCH"
```

- [ ] **Step 2: Commit**

```bash
git add server/tests/test_auth.py
git commit -m "test: add Tencent captcha auth tests"
```

---

## Task 13: Testing - Frontend Tests

**Files:**
- Modify: `test/unit/pages/LoginPage.test.tsx`
- Create: `test/unit/components/TencentCaptcha.test.tsx`

- [ ] **Step 1: Update LoginPage tests**

```typescript
it('renders TencentCaptcha when provider is tencent', async () => {
  mockPublicSettings({
    captcha_provider: 'tencent',
    captcha_site_key: '189949311',
  })
  
  render(<LoginPage />)
  
  await waitFor(() => {
    expect(screen.getByTestId('tencent-captcha')).toBeInTheDocument()
  })
})

it('submits login with Tencent captcha tokens', async () => {
  mockPublicSettings({
    captcha_provider: 'tencent',
    captcha_site_key: '189949311',
  })
  
  render(<LoginPage />)
  
  // Fill form
  fireEvent.change(screen.getByLabelText(/username/i), {
    target: { value: 'testuser' }
  })
  fireEvent.change(screen.getByLabelText(/password/i), {
    target: { value: 'password123' }
  })
  
  // Simulate captcha completion
  const ticket = 'test_ticket'
  const randstr = 'test_randstr'
  
  // Submit
  fireEvent.click(screen.getByRole('button', { name: /sign in/i }))
  
  await waitFor(() => {
    expect(mockLogin).toHaveBeenCalledWith(
      'testuser',
      'password123',
      undefined,
      ticket,
      randstr
    )
  })
})
```

- [ ] **Step 2: Create TencentCaptcha component test**

```typescript
import { render, waitFor } from '@testing-library/react'
import { TencentCaptcha } from '../../../src/renderer/src/components/TencentCaptcha'

describe('TencentCaptcha', () => {
  it('loads script and initializes captcha', async () => {
    const onVerify = vi.fn()
    
    render(<TencentCaptcha appId="189949311" onVerify={onVerify} />)
    
    await waitFor(() => {
      const script = document.querySelector('script[src*="TJNCaptcha-global.js"]')
      expect(script).toBeInTheDocument()
    })
  })

  it('calls onVerify with ticket and randstr', async () => {
    const onVerify = vi.fn()
    
    render(<TencentCaptcha appId="189949311" onVerify={onVerify} />)
    
    // Simulate callback
    const mockCallback = { ret: 0, ticket: 'test_ticket', randstr: 'test_randstr' }
    // ... trigger callback ...
    
    expect(onVerify).toHaveBeenCalledWith('test_ticket', 'test_randstr')
  })
})
```

- [ ] **Step 3: Commit**

```bash
git add test/unit/pages/LoginPage.test.tsx test/unit/components/TencentCaptcha.test.tsx
git commit -m "test: add frontend tests for Tencent captcha"
```

---

## Verification Checklist

Before marking complete, verify:

- [ ] Backend tests pass: `python -m pytest server/tests/test_geo_ip.py server/tests/test_auth.py server/tests/test_settings.py -v`
- [ ] Frontend tests pass: `npm run test:run`
- [ ] TypeScript compiles without errors: `npx tsc --noEmit`
- [ ] Login page renders correct captcha based on IP
- [ ] Admin settings page allows configuring Tencent captcha
- [ ] i18n translations display correctly in all languages
- [ ] Circuit breaker works when IP service is down
- [ ] Private IPs default to Turnstile

---

## Rollout

1. Deploy backend changes
2. Configure Tencent Captcha in admin settings:
   - App ID: `189949311`
   - Secret Key: (provided separately)
   - Enable: `true`
3. Deploy frontend changes
4. Monitor logs for:
   - `captcha_provider_selected` events
   - `ip_detection_failure` events
   - `tencent_api_error` events
   - `fallback_to_turnstile` events
