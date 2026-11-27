import httpx

from audyssey.settings import Settings

# Connection set from the UI: one tools server for all four tools. Process-wide, because
# the remote clients read their settings on every call. ponytail: one app per process.
_override = ("", "")


def set_override(url: str, token: str) -> None:
    global _override
    _override = (url, token)


def override() -> tuple[str, str]:
    return _override


def with_override(settings: Settings) -> Settings:
    """Settings with the UI connection applied: all four tools remote at one URL."""
    url, token = _override
    if not url:
        return settings
    update = {
        "separator": "remote",
        "separator_url": url,
        "filter": "remote",
        "filter_url": url,
        "grounder": "remote",
        "grounding_url": url,
        "generator": "remote",
        "generator_url": url,
    }
    if token:
        update["tool_token"] = token
    return settings.model_copy(update=update)


def remote_settings() -> Settings:
    return with_override(Settings())


def post(
    url: str,
    path: str,
    files: dict[str, tuple[str, bytes, str]],
    data: dict[str, str],
    token: str,
    timeout: float,
) -> httpx.Response:
    base = httpx.URL(url)
    endpoint = base.copy_with(path=base.path.rstrip("/") + path)
    display_url = endpoint.copy_with(
        username=None, password=None, query=None, fragment=None
    )
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        response = httpx.post(
            endpoint, files=files, data=data, headers=headers, timeout=timeout
        )
    except httpx.RequestError as exc:
        # Transport messages and response bodies may contain credentials.
        raise RuntimeError(
            f"tool server {display_url} failed: {type(exc).__name__}"
        ) from None
    if not response.is_success:
        raise RuntimeError(f"tool server {display_url} failed: {response.status_code}")
    return response
