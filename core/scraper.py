"""
Core scraping module for Spotigram.
Handles bypassing DRM via spotidown.app and downloading audio files in parallel.
"""
import os
import re
import json
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
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
MAX_CONCURRENT_WORKERS = 5

# --- Core Scraper Logic ---

def _create_session() -> requests.Session:
    """Initializes a session and extracts the hidden CSRF token."""
    session = requests.Session()
    session.headers.update({
        "User-Agent": USER_AGENT,
        "Referer": API_BASE_URL + "/en2",
        "X-Requested-With": "XMLHttpRequest",
    })
    response = session.get(API_BASE_URL + "/en2", timeout=15)
    soup = BeautifulSoup(response.text, "html.parser")
    hidden_input = soup.find("input", {"type": "hidden", "name": re.compile(r"^_")})
    session._csrf = {hidden_input["name"]: hidden_input["value"]}
    return session

def _fetch_download_action(session: requests.Session, spotify_url: str) -> str:
    """Submits the Spotify URL and retrieves the HTML containing download forms."""
    response = session.post(API_BASE_URL + "/action", data={
        "url": spotify_url,
        "g-recaptcha-response": "faketoken",
        **session._csrf,
    }, timeout=20)
    resp_json = response.json()
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

def _download_thumbnail(url: str, track_name: str) -> str | None:
    """Downloads the album art to be used as a Telegram thumbnail."""
    if not url or not url.startswith("http"):
        return None
    try:
        safe_name = re.sub(r'[\\/*?:"<>|]', "", track_name)[:80]
        file_path = os.path.join(DOWNLOAD_DIR, f"{safe_name}_thumb.jpg")
        with requests.get(url, timeout=15, headers={"User-Agent": USER_AGENT}) as r:
            r.raise_for_status()
            with open(file_path, "wb") as f:
                f.write(r.content)
        return file_path if os.path.getsize(file_path) > 0 else None
    except Exception:
        return None

def _download_audio_file(url: str, track_name: str) -> str:
    """Streams and saves the actual .mp3 file."""
    safe_name = re.sub(r'[\\/*?:"<>|]', "", track_name)[:100]
    file_path = os.path.join(DOWNLOAD_DIR, f"{safe_name}.mp3")
    with requests.get(url, stream=True, timeout=120, headers={"User-Agent": USER_AGENT}) as r:
        r.raise_for_status()
        with open(file_path, "wb") as f:
            for chunk in r.iter_content(128 * 1024):
                if chunk:
                    f.write(chunk)
    if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
        raise RuntimeError("Downloaded file is empty")
    return file_path

def _process_single_track(session: requests.Session, form_data: dict, index: int, fallback_thumb: str | None = None):
    """Handles the extraction and downloading of a single audio file."""
    try:
        track_info = json.loads(base64.b64decode(form_data.get("data", "")).decode())
        title = track_info.get("name", f"Track {index + 1}")
        raw_artist = track_info.get("artist", "")
        if raw_artist and "," in raw_artist:
            # Split the string by comma, clean up spaces, and keep only the first two
            artist_list = [a.strip() for a in raw_artist.split(",")]
            artist = ", ".join(artist_list[:2])
        else:
            artist = raw_artist
        file_name = f"{title} - {artist}" if artist else title
        thumb_url = track_info.get("cover") or track_info.get("image") or track_info.get("thumb") or fallback_thumb
    except Exception:
        title, artist, file_name, thumb_url = f"Track {index + 1}", "", f"Track {index + 1}", fallback_thumb

    response = session.post(API_BASE_URL + "/action/track", data=form_data, timeout=30)
    resp_json = response.json()
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

    try:
        local_audio_path = _download_audio_file(download_link, file_name)
    except Exception as e:
        return index, file_name, title, artist, None, None, f"Download failed: {e}"

    local_thumb_path = _download_thumbnail(thumb_url, file_name)
    return index, file_name, title, artist, local_audio_path, local_thumb_path, None

# --- Main Exported Functions ---

def get_track(spotify_url: str):
    """Public function: Fetches a single Spotify track."""
    session = _create_session()
    html_content = _fetch_download_action(session, spotify_url)
    forms, fallback_thumb = _parse_html_forms(html_content)
    if not forms:
        raise Exception("No track data found on the server.")
    _, file_name, title, artist, audio_path, thumb_path, error = _process_single_track(session, forms[0], 0, fallback_thumb)
    if error:
        raise Exception(error)
    return file_name, title, artist, audio_path, thumb_path

def get_playlist_or_album(spotify_url: str, on_result_callback=None):
    """Public function: Fetches a playlist/album using concurrent threads."""
    session = _create_session()
    html_content = _fetch_download_action(session, spotify_url)
    forms, fallback_thumb = _parse_html_forms(html_content)
    total_tracks = len(forms)

    with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_WORKERS) as pool:
        futures = {
            pool.submit(_process_single_track, session, form, i, fallback_thumb): i
            for i, form in enumerate(forms)
        }
        for future in as_completed(futures):
            index, file_name, title, artist, audio_path, thumb_path, error = future.result()
            if on_result_callback:
                on_result_callback(index, total_tracks, file_name, title, artist, audio_path, thumb_path, error)