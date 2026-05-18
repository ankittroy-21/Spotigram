"""
Async Core scraping module for Spotigram using aiohttp.

Replaces blocking `requests` usage with a persistent `aiohttp.ClientSession`.
Provides `init_session()` / `close_session()` for lifecycle management and
exposes `get_track()` and `get_playlist_or_album()` as async functions.

Design notes:
- Uses a module-level `ClientSession` to reuse connections and enable HTTP keep-alive.
- Uses an `asyncio.Semaphore` to limit concurrent audio downloads globally.
- Thumbnails are written to temporary files (as before).
"""
import asyncio
import io
import json
import base64
import re
import os
import tempfile
from typing import Callable

import aiohttp
from bs4 import BeautifulSoup

# --- Configuration & Constants ---
DOWNLOAD_DIR = "./downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

API_BASE_URL = "https://spotidown.app"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/134.0.0.0 Safari/537.36"
)

# Concurrency tuning
MAX_CONCURRENT_WORKERS = 5  # per-playlist processing concurrency
GLOBAL_AUDIO_CONCURRENCY = 3  # global simultaneous audio downloads

# Module-level aiohttp session and CSRF cache
_session: aiohttp.ClientSession | None = None
_csrf: dict | None = None

# Global semaphore to throttle audio downloads
_download_semaphore: asyncio.Semaphore | None = None


async def init_session():
    """Initializes the persistent aiohttp ClientSession and semaphore."""
    global _session, _download_semaphore
    if _session is None:
        connector = aiohttp.TCPConnector(limit_per_host=MAX_CONCURRENT_WORKERS)
        _session = aiohttp.ClientSession(connector=connector, headers={"User-Agent": USER_AGENT})
    if _download_semaphore is None:
        _download_semaphore = asyncio.Semaphore(GLOBAL_AUDIO_CONCURRENCY)


async def close_session():
    """Closes the aiohttp session if present."""
    global _session
    if _session is not None:
        await _session.close()
        _session = None


async def _ensure_csrf():
    """Fetches the landing page and extracts the hidden CSRF input used by the API."""
    global _csrf, _session
    if _csrf is not None:
        return
    if _session is None:
        await init_session()

    async with _session.get(API_BASE_URL + "/en2", timeout=15) as resp:
        text = await resp.text()
    soup = BeautifulSoup(text, "html.parser")
    hidden_input = soup.find("input", {"type": "hidden", "name": re.compile(r"^_")})
    if hidden_input and hidden_input.get("name") and hidden_input.get("value"):
        _csrf = {hidden_input["name"]: hidden_input["value"]}
    else:
        _csrf = {}


async def _fetch_download_action(spotify_url: str) -> str:
    """Submits the Spotify URL and retrieves the HTML containing download forms."""
    await _ensure_csrf()
    assert _session is not None
    data = {"url": spotify_url, "g-recaptcha-response": "faketoken", **(_csrf or {})}
    async with _session.post(API_BASE_URL + "/action", data=data, timeout=20) as resp:
        resp_json = await resp.json()
    if resp_json.get("error"):
        raise Exception(resp_json.get("message", "Unknown API error occurred"))
    return resp_json["data"]


def _parse_html_forms(html_content: str):
    """Parses the response HTML to find all track download forms and thumbnail."""
    soup = BeautifulSoup(html_content, "html.parser")
    forms = soup.find_all("form", {"name": "submitspurl"})
    parsed_forms = []

    for form in forms:
        fields = {}
        for inp in form.find_all("input"):
            if inp.get("name"):
                fields[inp["name"]] = inp.get("value", "")
        parsed_forms.append(fields)

    img_tag = soup.find("img")
    fallback_thumbnail = img_tag["src"] if img_tag else None
    return parsed_forms, fallback_thumbnail


async def _download_thumbnail(url: str, track_name: str) -> str | None:
    """
    Downloads the album art to a temporary file and returns its path.
    """
    if not url or not url.startswith("http"):
        return None
    if _session is None:
        await init_session()
    try:
        async with _session.get(url, timeout=15) as r:
            content = await r.read()
        if not content:
            return None
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
        try:
            tmp.write(content)
            tmp.flush()
        finally:
            tmp.close()
        return tmp.name if os.path.getsize(tmp.name) > 0 else None
    except Exception:
        return None


async def _download_audio_to_memory(url: str) -> io.BytesIO:
    """
    Streams the audio file directly into a BytesIO buffer — no disk I/O.
    Uses a global semaphore to limit concurrent downloads.
    """
    global _download_semaphore
    if _download_semaphore is None:
        await init_session()

    acquired = await _download_semaphore.acquire()
    try:
        buf = io.BytesIO()
        assert _session is not None
        async with _session.get(url, timeout=120) as r:
            r.raise_for_status()
            async for chunk in r.content.iter_chunked(128 * 1024):
                if chunk:
                    buf.write(chunk)
        if buf.tell() == 0:
            raise RuntimeError("Downloaded audio buffer is empty")
        buf.seek(0)
        return buf
    finally:
        # release regardless of success/failure
        _download_semaphore.release()


async def _process_single_track(form_data: dict, index: int, fallback_thumb: str | None = None):
    """
    Handles the extraction and downloading of a single audio file asynchronously.

    Returns:
        (index, file_name, title, artist, audio_bytes: BytesIO | None, thumb_path: str | None, error: str | None)
    """
    try:
        track_info = json.loads(base64.b64decode(form_data.get("data", "")).decode())
        title = track_info.get("name", f"Track {index + 1}")
        raw_artist = track_info.get("artist", "")
        if raw_artist and "," in raw_artist:
            artist_list = [a.strip() for a in raw_artist.split(",")]
            artist = ", ".join(artist_list[:2])
        else:
            artist = raw_artist
        file_name = f"{title} - {artist}" if artist else title
        thumb_url = track_info.get("cover") or track_info.get("image") or track_info.get("thumb") or fallback_thumb
    except Exception:
        title, artist, file_name, thumb_url = f"Track {index + 1}", "", f"Track {index + 1}", fallback_thumb

    # Request detailed track page
    assert _session is not None
    async with _session.post(API_BASE_URL + "/action/track", data=form_data, timeout=30) as resp:
        resp_json = await resp.json()
    if resp_json.get("error"):
        return index, file_name, title, artist, None, None, resp_json.get("message")

    soup = BeautifulSoup(resp_json["data"], "html.parser")

    img_tag = soup.find("img")
    if img_tag and not thumb_url:
        thumb_url = img_tag.get("src")

    download_link = None
    target_link = soup.find("a", href=re.compile(r"/dl\?token=|rapid\.spotidown"))
    if target_link:
        download_link = target_link["href"]
        if download_link.startswith("/"):
            download_link = API_BASE_URL + download_link
    else:
        for a_tag in soup.find_all("a", href=re.compile(r"https?://")):
            download_link = a_tag["href"]
            break

    if not download_link:
        return index, file_name, title, artist, None, None, "No valid download link found"

    # Concurrent audio + thumbnail fetch
    audio_buf = None
    thumb_path = None
    audio_error = None

    tasks = [asyncio.create_task(_download_audio_to_memory(download_link)), asyncio.create_task(_download_thumbnail(thumb_url, file_name))]
    done, pending = await asyncio.wait(tasks, return_when=asyncio.ALL_COMPLETED)

    for t in done:
        try:
            res = t.result()
            if isinstance(res, io.BytesIO):
                audio_buf = res
            elif isinstance(res, str) or res is None:
                thumb_path = res
        except Exception as e:
            # If audio task failed, mark audio_error; thumbnail failures are non-fatal
            if t is tasks[0]:
                audio_error = f"Download failed: {e}"

    if audio_error:
        return index, file_name, title, artist, None, None, audio_error

    return index, file_name, title, artist, audio_buf, thumb_path, None


async def get_track(spotify_url: str):
    """
    Public function: Fetches a single Spotify track asynchronously.
    Returns: (file_name, title, artist, audio_bytes: BytesIO, thumb_path: str | None)
    """
    if _session is None:
        await init_session()
    html_content = await _fetch_download_action(spotify_url)
    forms, fallback_thumb = _parse_html_forms(html_content)
    if not forms:
        raise Exception("No track data found on the server.")
    index, file_name, title, artist, audio_buf, thumb_path, error = await _process_single_track(forms[0], 0, fallback_thumb)
    if error:
        raise Exception(error)
    return file_name, title, artist, audio_buf, thumb_path


async def get_playlist_or_album(spotify_url: str, on_result_callback: Callable | None = None):
    """
    Public function: Fetches a playlist/album using limited concurrency.

    If `on_result_callback` is provided it will be called for each completed track with
    the signature `(index, total, file_name, title, artist, audio_buf, thumb_path, error)`.
    The callback may be either a coroutine function or a regular function.
    """
    if _session is None:
        await init_session()

    html_content = await _fetch_download_action(spotify_url)
    forms, fallback_thumb = _parse_html_forms(html_content)
    total_tracks = len(forms)

    sem = asyncio.Semaphore(MAX_CONCURRENT_WORKERS)

    async def worker(form, idx):
        async with sem:
            return await _process_single_track(form, idx, fallback_thumb)

    tasks = [asyncio.create_task(worker(form, i)) for i, form in enumerate(forms)]

    for coro in asyncio.as_completed(tasks):
        index, file_name, title, artist, audio_buf, thumb_path, error = await coro
        if on_result_callback:
            if asyncio.iscoroutinefunction(on_result_callback):
                await on_result_callback(index, total_tracks, file_name, title, artist, audio_buf, thumb_path, error)
            else:
                # synchronous callback is allowed
                on_result_callback(index, total_tracks, file_name, title, artist, audio_buf, thumb_path, error)
