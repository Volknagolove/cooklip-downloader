#!/usr/bin/env python3
import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
import ctypes
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from urllib.request import urlopen

import websocket


APP_NAME = "Cooklip Downloader"
APP_ID = "Cooklip.EN"
APP_ICON_FILE = "cooklip.ico"
SETTINGS_FILE = "cooklip_settings_en.json"
LEGACY_SETTINGS_FILE = "yt_cookie_downloader_settings.json"
DEFAULT_COOKIES_FILE = "cookies.txt"
EDGE_DEBUG_HOST = "127.0.0.1"
DEFAULT_EDGE_DEBUG_PORT = 9222
EDGE_URLS = [
    "https://www.youtube.com/",
    "https://accounts.google.com/",
    "https://www.google.com/",
]
VIDEO_FORMATS = ["mp4", "mkv", "webm"]
AUDIO_FORMATS = ["mp3", "m4a", "opus", "wav"]
VIDEO_QUALITIES = ["best", "2160p", "1440p", "1080p", "720p", "480p", "360p"]
AUDIO_QUALITIES = ["best", "320k", "256k", "192k", "128k"]


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def app_state_dir() -> Path:
    return app_dir() / "data"


def legacy_app_state_dir() -> Path:
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / APP_ID
    return app_dir() / ".cooklip"


def default_download_dir() -> Path:
    downloads = Path.home() / "Downloads"
    if downloads.exists():
        return downloads
    return app_dir()


def icon_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve()
    return APP_DIR / APP_ICON_FILE


def set_windows_app_id():
    if os.name != "nt":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(f"{APP_ID}.EN.App")
    except Exception:
        pass


APP_DIR = app_dir()
APP_STATE_DIR = app_state_dir()
LEGACY_APP_STATE_DIR = legacy_app_state_dir()
SETTINGS_PATH = APP_STATE_DIR / SETTINGS_FILE
LEGACY_SETTINGS_PATH = APP_DIR / LEGACY_SETTINGS_FILE
LEGACY_COOKIES_PATH = APP_DIR / DEFAULT_COOKIES_FILE
LEGACY_APP_STATE_SETTINGS_PATH = LEGACY_APP_STATE_DIR / SETTINGS_FILE
LOCAL_EXEC_DIRS = [
    APP_DIR / "bin",
    APP_DIR,
]
EXEC_CACHE: dict[str, str | None] = {
    "yt_dlp": None,
    "ffmpeg": None,
    "deno": None,
    "edge": None,
}

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
STARTF_USESHOWWINDOW = getattr(subprocess, "STARTF_USESHOWWINDOW", 0)
SW_HIDE = 0


def normalize_edge_debug_port(value) -> int:
    try:
        port = int(str(value).strip())
    except (TypeError, ValueError):
        return DEFAULT_EDGE_DEBUG_PORT
    if 1 <= port <= 65535:
        return port
    return DEFAULT_EDGE_DEBUG_PORT


def edge_list_url(port: int | None = None) -> str:
    port = normalize_edge_debug_port(port)
    return f"http://{EDGE_DEBUG_HOST}:{port}/json/list"


def edge_origin(port: int | None = None) -> str:
    port = normalize_edge_debug_port(port)
    return f"http://{EDGE_DEBUG_HOST}:{port}"


def default_settings():
    return {
        "download_dir": str(default_download_dir()),
        "cookies_path": str(APP_STATE_DIR / DEFAULT_COOKIES_FILE),
        "edge_debug_port": DEFAULT_EDGE_DEBUG_PORT,
        "format_type": "mp4",
        "quality": "best",
        "url": "",
        "downloads_history": [],
    }


def load_settings():
    settings_path = SETTINGS_PATH
    if not settings_path.exists():
        if LEGACY_APP_STATE_SETTINGS_PATH.exists():
            settings_path = LEGACY_APP_STATE_SETTINGS_PATH
        else:
            settings_path = LEGACY_SETTINGS_PATH
    if settings_path.exists():
        try:
            data = json.loads(settings_path.read_text(encoding="utf-8"))
            base = default_settings()
            base.update(data)
            if not data.get("cookies_path") or str(data.get("cookies_path")).strip() in {
                str(LEGACY_COOKIES_PATH),
                str(APP_DIR / DEFAULT_COOKIES_FILE),
                str(LEGACY_APP_STATE_DIR / DEFAULT_COOKIES_FILE),
            }:
                base["cookies_path"] = str(APP_STATE_DIR / DEFAULT_COOKIES_FILE)
            base["edge_debug_port"] = normalize_edge_debug_port(base.get("edge_debug_port"))
            return base
        except Exception:
            pass
    return default_settings()


def save_settings(data: dict):
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def bool_str(v):
    return "TRUE" if v else "FALSE"


def local_executable_candidates(*names: str) -> list[str]:
    candidates: list[str] = []
    for directory in LOCAL_EXEC_DIRS:
        for name in names:
            if not name:
                continue
            path = directory / name
            candidates.append(str(path))
            if not name.lower().endswith(".exe"):
                candidates.append(str(directory / f"{name}.exe"))
    return candidates


def hidden_subprocess_kwargs() -> dict:
    kwargs: dict = {}
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = SW_HIDE
        kwargs["startupinfo"] = startupinfo
        if CREATE_NO_WINDOW:
            kwargs["creationflags"] = CREATE_NO_WINDOW
    return kwargs


def resolve_executable(cache_key: str, direct_names: list[str], candidate_paths: list[str], lookup_names: list[str]) -> str | None:
    cached = EXEC_CACHE.get(cache_key)
    if cached:
        return cached

    candidates: list[str] = []

    candidates.extend(p for p in candidate_paths if p)

    for name in direct_names:
        found = shutil.which(name)
        if found:
            candidates.append(found)

    for name in lookup_names:
        for cmd in (
            ["where.exe", name],
            ["powershell", "-NoProfile", "-Command", f"(Get-Command {name} -ErrorAction SilentlyContinue).Source"],
        ):
            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    shell=False,
                    **hidden_subprocess_kwargs(),
                )
                if result.returncode == 0 and result.stdout:
                    for line in result.stdout.splitlines():
                        line = line.strip().strip('"')
                        if line:
                            candidates.append(line)
            except Exception:
                pass

    seen = set()
    for candidate in candidates:
        candidate = str(Path(candidate))
        if candidate in seen:
            continue
        seen.add(candidate)
        if Path(candidate).exists():
            EXEC_CACHE[cache_key] = candidate
            return candidate

    return None


def resolve_ffmpeg_executable() -> str | None:
    return resolve_executable(
        "ffmpeg",
        ["ffmpeg"],
        [
            *local_executable_candidates("ffmpeg", "ffmpeg.exe"),
            os.path.expandvars(r"%LocalAppData%\Microsoft\WinGet\Packages\yt-dlp.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-N-123778-g3b55818764-win64-gpl\bin\ffmpeg.exe"),
            os.path.expandvars(r"%LocalAppData%\Microsoft\WinGet\Links\ffmpeg.exe"),
            os.path.expandvars(r"%UserProfile%\AppData\Local\Microsoft\WinGet\Links\ffmpeg.exe"),
        ],
        ["ffmpeg"],
    )


def resolve_deno_executable() -> str | None:
    return resolve_executable(
        "deno",
        ["deno"],
        [
            *local_executable_candidates("deno", "deno.exe"),
            os.path.expandvars(r"%LocalAppData%\Microsoft\WinGet\Links\deno.exe"),
            os.path.expandvars(r"%UserProfile%\AppData\Local\Microsoft\WinGet\Links\deno.exe"),
        ],
        ["deno"],
    )


def resolve_ytdlp_executable() -> str:
    resolved = resolve_executable(
        "yt_dlp",
        ["yt-dlp"],
        [
            *local_executable_candidates("yt-dlp", "yt-dlp.exe"),
            os.path.expandvars(r"%LocalAppData%\Microsoft\WinGet\Links\yt-dlp.exe"),
            os.path.expandvars(r"%UserProfile%\AppData\Local\Microsoft\WinGet\Links\yt-dlp.exe"),
            os.path.expandvars(r"%ProgramFiles%\yt-dlp\yt-dlp.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\yt-dlp\yt-dlp.exe"),
        ],
        ["yt-dlp"],
    )
    return resolved or "yt-dlp"


def find_ytdlp_executable() -> str | None:
    return resolve_executable(
        "yt_dlp",
        ["yt-dlp"],
        [
            *local_executable_candidates("yt-dlp", "yt-dlp.exe"),
            os.path.expandvars(r"%LocalAppData%\Microsoft\WinGet\Links\yt-dlp.exe"),
            os.path.expandvars(r"%UserProfile%\AppData\Local\Microsoft\WinGet\Links\yt-dlp.exe"),
            os.path.expandvars(r"%ProgramFiles%\yt-dlp\yt-dlp.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\yt-dlp\yt-dlp.exe"),
        ],
        ["yt-dlp"],
    )


def cookie_to_netscape(cookie):
    domain = cookie.get("domain", "")
    include_subdomains = domain.startswith(".")
    path = cookie.get("path", "/")
    secure = cookie.get("secure", False)
    expires = cookie.get("expires")

    if expires is None or expires < 0:
        expires = 0
    else:
        expires = int(expires)

    name = cookie.get("name", "")
    value = cookie.get("value", "")

    return "\t".join([
        domain,
        bool_str(include_subdomains),
        path,
        bool_str(secure),
        str(expires),
        name,
        value,
    ])


def cookies_contain_authorization(cookies: list[dict]) -> bool:
    auth_names = {
        "SID",
        "__Secure-1PSID",
        "__Secure-3PSID",
        "HSID",
        "SSID",
        "SAPISID",
        "__Secure-1PAPISID",
        "__Secure-3PAPISID",
        "APISID",
        "LOGIN_INFO",
    }
    auth_domains = (
        "youtube.com",
        "google.com",
        "accounts.google.com",
    )

    for cookie in cookies:
        name = (cookie.get("name") or "").strip()
        domain = (cookie.get("domain") or "").lstrip(".").lower()
        if name in auth_names and any(domain.endswith(d) for d in auth_domains):
            return True
    return False


def get_page_ws_debugger_url(port: int | None = None):
    with urlopen(edge_list_url(port)) as r:
        targets = json.loads(r.read().decode("utf-8"))

    for target in targets:
        if target.get("type") == "page" and "youtube.com" in (target.get("url") or ""):
            return target["webSocketDebuggerUrl"]

    for target in targets:
        if target.get("type") == "page" and target.get("webSocketDebuggerUrl"):
            return target["webSocketDebuggerUrl"]

    raise RuntimeError("No page tab was found in Edge DevTools. Open YouTube in Edge launched with remote debugging.")


def cdp_call(ws, method, params=None, msg_id=1):
    payload = {
        "id": msg_id,
        "method": method,
        "params": params or {},
    }
    ws.send(json.dumps(payload))
    while True:
        raw = ws.recv()
        msg = json.loads(raw)
        if msg.get("id") == msg_id:
            if "error" in msg:
                raise RuntimeError(msg["error"])
            return msg.get("result", {})


def export_cookies_from_edge(output_path: Path, port: int | None = None):
    port = normalize_edge_debug_port(port)
    ws_url = get_page_ws_debugger_url(port)
    ws = websocket.create_connection(ws_url, origin=edge_origin(port))
    try:
        cdp_call(ws, "Network.enable", {}, 1)
        result = cdp_call(ws, "Network.getCookies", {"urls": EDGE_URLS}, 2)
        cookies = result.get("cookies", [])

        seen = set()
        lines = [
            "# Netscape HTTP Cookie File",
            "# Exported from Microsoft Edge via DevTools Protocol",
            "",
        ]

        written = 0
        for cookie in cookies:
            key = (cookie.get("domain"), cookie.get("path"), cookie.get("name"))
            if key in seen:
                continue
            seen.add(key)
            lines.append(cookie_to_netscape(cookie))
            written += 1

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
        return {
            "written": written,
            "authorized": cookies_contain_authorization(cookies),
        }
    finally:
        ws.close()


def find_edge_path() -> str | None:
    return resolve_executable(
        "edge",
        ["msedge"],
        [
            os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
            os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
            os.path.expandvars(r"%LocalAppData%\Microsoft\Edge\Application\msedge.exe"),
        ],
        ["msedge"],
    )


def is_audio_format(format_type: str) -> bool:
    return format_type in AUDIO_FORMATS


def get_quality_values(format_type: str) -> list[str]:
    return AUDIO_QUALITIES if is_audio_format(format_type) else VIDEO_QUALITIES


def get_format_string(format_type: str, quality: str) -> str:
    if is_audio_format(format_type):
        return ""
    if quality == "best":
        return "bv*+ba/b"
    if quality == "2160p":
        return "bestvideo[height<=2160]+bestaudio/best[height<=2160]/best"
    if quality == "1440p":
        return "bestvideo[height<=1440]+bestaudio/best[height<=1440]/best"
    if quality == "1080p":
        return "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best"
    if quality == "720p":
        return "bestvideo[height<=720]+bestaudio/best[height<=720]/best"
    if quality == "480p":
        return "bestvideo[height<=480]+bestaudio/best[height<=480]/best"
    if quality == "360p":
        return "bestvideo[height<=360]+bestaudio/best[height<=360]/best"
    return "bv*+ba/b"


def powershell_quote(value: str) -> str:
    return '"' + value.replace('"', '`"') + '"'


def get_audio_quality_value(quality: str) -> str:
    if quality == "best":
        return "0"
    return quality.lower()


def detect_playlist_mode(url: str) -> str:
    try:
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        has_list = bool(params.get("list"))
        has_video = bool(params.get("v"))
        if has_list and has_video:
            return "mixed"
        if has_list:
            return "playlist"
    except Exception:
        pass
    return "single"


def wrap_powershell_utf8(command: str) -> str:
    prefix = (
        "[Console]::InputEncoding = [System.Text.UTF8Encoding]::new(); "
        "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new(); "
        "$OutputEncoding = [System.Text.UTF8Encoding]::new(); "
        "chcp 65001 > $null; "
    )
    return prefix + command


def build_powershell_command(
    url: str,
    cookies_path: str,
    download_dir: str,
    format_type: str,
    quality: str,
    final_path_file: str | None = None,
    playlist_mode: str = "single",
) -> str:
    exe = resolve_ytdlp_executable()
    exe_ps = powershell_quote(exe)
    print_args = []
    if final_path_file:
        print_args = [
            "--print-to-file",
            powershell_quote("after_move:%(filepath)j"),
            powershell_quote(final_path_file),
        ]
    else:
        print_args = [
            "--print",
            powershell_quote("after_move:FINAL_FILE:%(filepath)s"),
        ]
    playlist_args = []
    if playlist_mode == "single":
        playlist_args = ["--no-playlist"]
    elif playlist_mode == "playlist":
        playlist_args = ["--yes-playlist"]

    if is_audio_format(format_type):
        parts = [
            "&", exe_ps,
            "--cookies", powershell_quote(cookies_path),
            "-P", powershell_quote(download_dir),
            "-x",
            *playlist_args,
            *print_args,
            "--audio-format", format_type,
            "--audio-quality", get_audio_quality_value(quality),
            powershell_quote(url),
        ]
    else:
        fmt = get_format_string(format_type, quality)
        parts = [
            "&", exe_ps,
            "--cookies", powershell_quote(cookies_path),
            "-P", powershell_quote(download_dir),
            *playlist_args,
            *print_args,
            "-f", powershell_quote(fmt),
            "--merge-output-format", format_type,
            powershell_quote(url),
        ]
    return wrap_powershell_utf8(" ".join(parts))


def create_final_path_marker() -> Path:
    return Path(tempfile.gettempdir()) / f"yt_cookie_downloader_{uuid.uuid4().hex}.jsonl"


def read_final_path_markers(marker_path: Path) -> list[str]:
    if not marker_path.exists():
        return []
    results: list[str] = []
    try:
        lines = marker_path.read_text(encoding="utf-8", errors="replace").splitlines()
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, str) and value.strip():
                results.append(value.strip())
    except Exception:
        return []
    finally:
        try:
            marker_path.unlink(missing_ok=True)
        except Exception:
            pass
    deduped: list[str] = []
    seen = set()
    for value in results:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def read_final_path_marker(marker_path: Path) -> str | None:
    values = read_final_path_markers(marker_path)
    return values[-1] if values else None


def describe_missing_dependencies(format_type: str) -> list[str]:
    missing = []
    ytdlp = find_ytdlp_executable()
    if not ytdlp:
        missing.append("yt-dlp")
    if not resolve_ffmpeg_executable():
        missing.append("ffmpeg")
    return missing


def explain_cookie_refresh_error(error: Exception, port: int | None = None) -> str:
    port = normalize_edge_debug_port(port)
    text = str(error).lower()
    if "connection refused" in text or f"{EDGE_DEBUG_HOST}:{port}" in text:
        return (
            f"Could not connect to Edge DevTools on port {port}. "
            "Launch Edge for cookies using the app button and open a YouTube tab."
        )
    if "page tab" in text or "page-вкладка" in text or "websocketdebuggerurl" in text:
        return (
            "No suitable YouTube tab was found in Edge. "
            "Open YouTube in the Edge window launched for cookies and try again."
        )
    if "forbidden" in text or "403" in text:
        return "Edge denied access to DevTools. Try launching Edge for cookies again from the app."
    return f"Failed to refresh cookies: {error}"


def is_partial_playlist_success(return_code: int, output_lines: list[str]) -> bool:
    if return_code == 0:
        return False
    combined = "\n".join(output_lines).lower()
    return (
        "finished downloading playlist" in combined
        and (
            "video unavailable" in combined
            or "unavailable videos are hidden" in combined
            or "downloading item" in combined
        )
    )


def explain_partial_playlist_success(output_lines: list[str]) -> str:
    combined = "\n".join(output_lines).lower()
    if "unavailable videos are hidden" in combined or "video unavailable" in combined:
        return (
            "Playlist download finished. Available items were saved, "
            "and unavailable items were skipped."
        )
    return "Playlist download finished. Some items were skipped."


def explain_download_failure(return_code: int, output_lines: list[str], format_type: str) -> str:
    combined = "\n".join(output_lines[-80:]).lower()

    if "ffmpeg is not installed" in combined or "ffprobe and ffmpeg not found" in combined:
        return "ffmpeg was not found. It is required to merge video and audio or convert to the selected format."
    if "unable to extract uploader id" in combined or "unable to extract initial data" in combined:
        return "YouTube changed the page or the site responded unexpectedly. Try updating yt-dlp and try again."
    if "requested format is not available" in combined:
        return "The selected quality or format is not available for this video. Try a lower quality or use best."
    if "private video" in combined:
        return "This is a private video. It cannot be downloaded without access to an account that has permission to view it."
    if "video unavailable" in combined:
        return "The video is unavailable. Check the link and make sure the video still exists and is available in your region."
    if "this video is not available" in combined:
        return "The video is currently unavailable. Check the link, regional restrictions, or the video status."
    if "members-only" in combined or "join this channel" in combined:
        return "This video is available only to subscribers or channel members. Valid account cookies with access are required."
    if "sign in to confirm your age" in combined or "use --cookies" in combined:
        return "This video appears to require authorization. Refresh cookies from Edge and try again."
    if "nsig extraction failed" in combined:
        return "Failed to handle YouTube protection. Updating yt-dlp to a newer version usually helps."
    if "unable to download webpage" in combined or "http error 403" in combined or "http error 429" in combined:
        return "The site rejected the request. Refreshing cookies or trying again later usually helps."
    if "timed out" in combined or "timeout" in combined:
        return "The request timed out. Check your internet connection and try again."
    if "proxy" in combined and "error" in combined:
        return "There is a problem with proxy settings. Check the system proxy or disable it."
    if "permission denied" in combined or "access is denied" in combined:
        return "Access to the destination folder or file was denied. Try a different download folder."
    if "no such file or directory" in combined:
        return "The save path was not found. Check the download folder and the path to cookies.txt."
    if "is not recognized as the name of a cmdlet" in combined or "could not find executable" in combined:
        return "yt-dlp was not found on the system. Check the installation or place yt-dlp.exe next to the app."
    if return_code < 0:
        return "The download was stopped by the user."
    if is_audio_format(format_type):
        return f"Failed to download or convert audio. Exit code: {return_code}."
    return f"Failed to download video. Exit code: {return_code}."


def schedule_on_ui(widget, attr_name: str, callback, delay_ms: int = 120):
    pending = getattr(widget, attr_name, None)
    if pending:
        try:
            widget.after_cancel(pending)
        except Exception:
            pass
    setattr(widget, attr_name, widget.after(delay_ms, callback))


