# Geo-Based Captcha Switching Design

## Overview

Switch between Cloudflare Turnstile and Tencent Cloud Captcha based on the user's geographic location (IP address). Mainland China users get Tencent Captcha for better connectivity; all other users continue using Cloudflare Turnstile.

## Goals

- Improve captcha experience for Mainland China users (Cloudflare has poor connectivity in China)
- Maintain existing Turnstile behavior for non-China users
- Support both login page and registration request modal
- Keep configuration dynamic via admin settings (no hardcoded secrets)

## Non-Goals

- Replace Turnstile entirely
- Support other captcha providers
- Frontend IP detection (all detection happens on backend)

## Architecture

### Backend Changes

#### 1. Configuration Extension

Add Tencent Captcha settings to `GlobalSettings`:

```python
tencent_captcha_enabled: bool
tencent_captcha_app_id: str
tencent_captcha_secret_key: str
```

#### 2. IP Geolocation Detection

Create `backend/common/geo_ip.py`:

```python
def get_client_ip(request) -> str:
    """
    Extract client IP from request headers.
    
    Priority:
    1. CF-Connecting-IP (if behind Cloudflare CDN)
    2. X-Forwarded-For (rightmost non-private IP, only if behind known proxy)
    3. X-Real-IP
    4. request.client.host (direct connection)
    
    For private IPs (10.x, 172.16-31.x, 192.168.x, 127.x), default to Turnstile.
    """

def is_mainland_china_ip(ip: str) -> bool:
    """
    Check if an IP address is from Mainland China.
    Uses ip-api.com or similar free service with caching.
    Falls back to Turnstile if detection fails.
    """
```

Implementation approach:
- Use `ip-api.com` (free, no API key needed, 45 requests/min limit)
- Cache results in memory with TTL (e.g., 1 hour) to avoid rate limits
- For private IPs (desktop/Electron mode), default to Turnstile
- If service is down or rate limited, fallback to Turnstile
- **Circuit breaker**: After 5 consecutive failures, skip IP detection for 10 minutes and default to Turnstile

#### 3. Public Settings API Update

Update `/settings/public` to return captcha provider info:

```python
class PublicSettingsResponse(BaseModel):
    captcha_provider: Literal["turnstile", "tencent"] | None
    captcha_site_key: str  # Turnstile site key or Tencent app ID
```

The backend determines the provider by:
1. Checking if Tencent Captcha is enabled in settings
2. Getting client IP via `get_client_ip(request)` with secure header parsing
3. Calling `is_mainland_china_ip(client_ip)`
4. If China IP and Tencent enabled → return `tencent` provider
5. Otherwise → return `turnstile` provider (if enabled)
6. If IP detection fails → fallback to Turnstile (never disable captcha if enabled in settings)

#### 4. Captcha Verification Abstraction

Create unified verification function in `routes/auth.py`:

```python
async def verify_captcha_token(
    token: str | None,
    provider: Literal["turnstile", "tencent"],
    settings: dict
) -> bool:
    """Verify captcha token based on provider type."""
```

For Tencent Captcha:
- Call `captcha.intl.tencentcloudapi.com` API
- Use API 3.0 signature (Tencent Cloud standard)
- POST to `DescribeCaptchaResult`
- Required params: `CaptchaAppId`, `AppSecretKey`, `Ticket`, `Randstr`, `UserIp`

#### 5. Login & Registration API Updates

Update `SecureLoginRequest` and `AccessRequest` models:

```python
class SecureLoginRequest(BaseModel):
    username: str
    hashed_password: str
    timestamp: int
    turnstile_token: Optional[str] = None  # Turnstile token (when provider is turnstile)
    tencent_captcha_token: Optional[str] = None  # Tencent ticket (when provider is tencent)
    tencent_captcha_randstr: Optional[str] = None  # Tencent randstr (when provider is tencent)
```

In `secure_login` and `request_access` endpoints:
1. Determine expected provider from client IP (same logic as `/settings/public`)
2. If provider is `turnstile` → verify `turnstile_token`
3. If provider is `tencent` → verify `tencent_captcha_token` + `tencent_captcha_randstr`
4. Return appropriate error if wrong provider or missing token

**Validation rules:**
- If provider is `turnstile` and `turnstile_token` is missing → `TURNSTILE_TOKEN_REQUIRED`
- If provider is `tencent` and `tencent_captcha_token` or `tencent_captcha_randstr` is missing → `TENCENT_CAPTCHA_REQUIRED`
- If client sends Turnstile token but backend expects Tencent → `CAPTCHA_PROVIDER_MISMATCH`
- If client sends Tencent token but backend expects Turnstile → `CAPTCHA_PROVIDER_MISMATCH`

### Frontend Changes

#### 1. Settings API Update

Update `api/settings.ts`:

```typescript
export interface PublicSettings {
  captcha_provider: 'turnstile' | 'tencent' | null
  captcha_site_key: string
}
```

#### 2. TencentCaptcha Component

Create `src/renderer/src/components/TencentCaptcha.tsx`:

```typescript
interface TencentCaptchaProps {
  appId: string
  onVerify: (ticket: string, randstr: string) => void
  onExpire?: () => void
  onError?: () => void
}
```

Implementation:
- Load script from `https://ca.turing.captcha.qcloud.com/TJNCaptcha-global.js`
- Render captcha widget in a div
- Call `new TencentCaptcha(element, appId, callback, {}).show()`
- Handle callback: extract `ticket` (token) and `randstr`
- Cleanup on unmount

#### 3. LoginPage Updates

In `LoginPage.tsx`:
- Replace `turnstileSiteKey` state with `captchaConfig` state
- Fetch from updated `/settings/public` API
- Conditionally render:
  - `TurnstileWidget` if `captcha_provider === 'turnstile'`
  - `TencentCaptcha` if `captcha_provider === 'tencent'`
- Pass appropriate token to `login()` call
- Update button disabled logic

#### 4. AuthContext & API Updates

Update `AuthContext.tsx`:
```typescript
login: (username: string, password: string, turnstileToken?: string, tencentCaptchaTicket?: string, tencentCaptchaRandstr?: string) => Promise<boolean>
```

Update `api/auth.ts`:
```typescript
export async function loginWithCredentials(
  username: string,
  password: string,
  turnstileToken?: string,
  tencentCaptchaTicket?: string,
  tencentCaptchaRandstr?: string,
): Promise<LoginResponse>
```

#### 5. RegisterRequestModal Updates

Same pattern as LoginPage:
- Accept `captchaConfig` prop
- Conditionally render Turnstile or Tencent Captcha
- Pass appropriate token in `requestAccess` call

## Data Flow

```
User visits /login
    ↓
Frontend calls GET /settings/public
    ↓
Backend detects client IP → is_mainland_china_ip(ip)
    ↓
Backend returns { captcha_provider: "tencent", captcha_site_key: "189949311" }
    ↓
Frontend renders TencentCaptcha component
    ↓
User completes captcha → callback with (ticket, randstr)
    ↓
User submits login form
    ↓
Frontend POST /auth/secure-login with { ..., tencent_captcha_token: ticket, tencent_captcha_randstr: randstr }
    ↓
Backend verifies: is_mainland_china_ip(ip) → tencent → verify with Tencent API
    ↓
Login proceeds normally
```

## Error Handling

### Backend

- IP detection service failure → fallback to Turnstile
- Tencent API failure → log error, return verification failed
- Missing token when required → 400 with specific error code
- Wrong provider token (e.g., user sends Turnstile token but backend expects Tencent) → 400

### Frontend

- Settings API failure → fallback to Turnstile (never disable captcha if enabled in settings)
- Tencent script load failure → show error message, allow retry
- Captcha expiration → clear token, re-render widget
- Wrong provider response → log error, show generic captcha error to user

## Testing Strategy

### Backend Tests

1. `test_geo_ip.py`:
   - Test `is_mainland_china_ip` with known China IPs
   - Test with non-China IPs
   - Test with private IPs
   - Test service failure fallback

2. `test_auth.py`:
   - Test login with Tencent captcha (mock Tencent API)
   - Test login with Turnstile captcha (existing)
   - Test wrong provider token rejection
   - Test missing token when required

3. `test_settings.py`:
   - Test `/settings/public` returns correct provider based on IP

### Frontend Tests

1. `LoginPage.test.tsx`:
   - Test rendering TencentCaptcha when provider is tencent
   - Test rendering Turnstile when provider is turnstile
   - Test login with Tencent captcha token

2. `TencentCaptcha.test.tsx`:
   - Test script loading
   - Test callback handling
   - Test cleanup on unmount

## Security Considerations

1. **IP spoofing**: Use `X-Forwarded-For` carefully, trust only last hop if behind CDN/proxy
2. **Token reuse**: Both Turnstile and Tencent tokens are single-use; reset after failed login
3. **Rate limiting**: IP detection API has rate limits; implement caching
4. **Secret storage**: Tencent secret key stored in backend settings, never exposed to frontend

## Rollout Plan

1. Deploy backend changes (new settings fields, IP detection, verification)
2. Configure Tencent Captcha in admin settings (app_id, secret_key, enable)
3. Deploy frontend changes
4. Monitor logs for IP detection accuracy and Tencent API errors

## Files to Modify

### Backend
- `server/backend/common/config.py` - Add Tencent settings
- `server/backend/common/geo_ip.py` - NEW: IP geolocation
- `server/gateway/models.py` - Update request/response models
- `server/gateway/routes/settings.py` - Update public settings endpoint
- `server/gateway/routes/auth.py` - Add Tencent verification, update login/register

### Frontend
- `src/renderer/src/api/settings.ts` - Update PublicSettings interface
- `src/renderer/src/api/auth.ts` - Update login/requestAccess signatures
- `src/renderer/src/contexts/AuthContext.tsx` - Update login signature
- `src/renderer/src/components/TencentCaptcha.tsx` - NEW
- `src/renderer/src/pages/LoginPage.tsx` - Conditional captcha rendering
- `src/renderer/src/components/RegisterRequestModal.tsx` - Conditional captcha rendering
- `src/renderer/src/pages/SettingsPage.tsx` - Add Tencent captcha config fields to admin UI
- `src/renderer/src/locales/en-US.json`, `zh-CN.json`, `zh-HK.json` - Add new translation keys:
  - `auth.tencentCaptchaRequired`
  - `auth.captchaProviderMismatch`
  - `auth.tencentCaptchaVerificationFailed`
  - `settings.tencentCaptchaEnabled`
  - `settings.tencentCaptchaAppId`
  - `settings.tencentCaptchaSecretKey`

## Decisions

1. **Captcha flags**: Keep `turnstile_enabled` and add `tencent_captcha_enabled`. No separate `captcha_enabled` flag. Each provider can be independently enabled/disabled.
2. **Electron mode**: For private IPs (10.x, 172.16-31.x, 192.168.x, 127.x), always default to Turnstile since there's no geo-location concern in desktop mode.
3. **Caching**: Use in-memory cache with TTL (1 hour) for IP→country results. If Gateway runs multiple workers, each worker has its own cache. This is acceptable since the cache is just an optimization.
4. **Tencent endpoint**: Use `captcha.intl.tencentcloudapi.com` (international version) for all users. The user's location doesn't affect which Tencent endpoint to use.

## Monitoring

Track these metrics in logs:
- `captcha_provider_selected` - Which provider was selected for each request
- `ip_detection_failure` - When IP geolocation service fails
- `tencent_api_latency` - Tencent captcha verification response time
- `tencent_api_error` - Tencent API errors with error codes
- `fallback_to_turnstile` - When falling back to Turnstile due to errors

## Open Questions

1. Should we add a `captcha_enabled` flag separate from provider-specific flags, or keep `turnstile_enabled` and add `tencent_captcha_enabled`?
2. For Electron desktop mode (private IPs), should we always use Turnstile since there's no geo-location concern?
3. Should we cache IP→country results in Redis instead of in-memory to share across Gateway workers?
