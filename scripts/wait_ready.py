import time
import httpx
for attempt in range(30):
    try:
        if httpx.get("http://127.0.0.1:8008/api/v1/health", timeout=2).is_success:
            break
    except httpx.HTTPError:
        pass
    time.sleep(1)
else:
    raise SystemExit("API did not become ready")
