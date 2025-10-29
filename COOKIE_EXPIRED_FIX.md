# Cookie/Permission Error Fix

## Problem
The XiaoHongShu API was returning cookie/permission related error codes that were not being properly handled by the crawler, causing it to fail instead of automatically switching to a new cookie.

### Error Codes Handled:
- **-100**: 登录已过期 (Login expired)
- **-101**: 未登录 (Not logged in)
- **-102**: 登录状态失效 (Login state invalid)
- **-104**: 账号没有权限访问 (Account has no permission)

## Solution
Added automatic cookie switching when login expires by:

1. **Modified `client.py`**: Added detection for error code `-100` to raise `CookieBlockedException`
2. **Modified `core.py`**: Added `CookieBlockedException` handling in all API call locations to trigger automatic cookie switching

## Changes Made

### 1. `media_platform/xhs/client.py`
- Added handling for error codes `-100`, `-101`, `-102`, `-104` (all cookie/permission related)
- When detected, raises `CookieBlockedException` to trigger automatic cookie switching
- This integrates with the existing cookie pool management system

### 2. `media_platform/xhs/core.py`
- Imported `CookieBlockedException` from `tools.cookie_guard`
- Added exception handling in 3 key methods:
  - `search()` - keyword search
  - `get_note_detail_async_task()` - note detail fetching
  - `get_comments()` - comment fetching

## How It Works

When the API returns any cookie/permission error code (`-100`, `-101`, `-102`, `-104`):
1. Client raises `CookieBlockedException`
2. Crawler catches the exception
3. Calls `cookie_pool_manager.handle_cookie_blocked()` to switch to next available cookie
4. Retries the request with the new cookie (up to 3 attempts)
5. Logs the cookie switch with emoji indicators (🔐 for cookie issues, ✅ for success, ❌ for failure)

## Configuration Requirements

Make sure these settings are enabled in `config/base_config.py`:
- `ENABLE_COOKIE_POOL = True` - Enable cookie pool
- `ENABLE_COOKIE_AUTO_SWITCH = True` - Enable automatic cookie switching
- Multiple cookies should be configured in the cookie pool

## Testing
After these changes, when a cookie expires:
- The system will automatically detect it
- Switch to the next available cookie
- Continue crawling without manual intervention
- Log clear messages about the cookie switch process
