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


APP_NAME = "Cooklip Downloader RU"
APP_ID = "Cooklip.RU"
APP_ICON_FILE = "cooklip.ico"
SETTINGS_FILE = "cooklip_settings.json"
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
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(f"{APP_ID}.App")
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


def hidden_subprocess_kwargs():
    kwargs = {}
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        kwargs["startupinfo"] = startupinfo
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return kwargs


def clean_path_string(value: str | None) -> str:
    if value is None:
        return ""
    return str(value).strip().strip('"').strip("'")


def normalize_path(value: str | None) -> str:
    cleaned = clean_path_string(value)
    if not cleaned:
        return ""
    return str(Path(cleaned).expanduser())


def ensure_parent_dir(path: str | Path):
    Path(path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)


def ensure_dir(path: str | Path):
    Path(path).expanduser().mkdir(parents=True, exist_ok=True)


def load_settings():
    candidates = [
        SETTINGS_PATH,
        LEGACY_APP_STATE_SETTINGS_PATH,
        LEGACY_SETTINGS_PATH,
    ]

    for path in candidates:
        if path.exists():
            try:
                with path.open("r", encoding="utf-8") as fh:
                    data = json.load(fh)
                    if isinstance(data, dict):
                        return data
            except Exception:
                continue
    return {}


def save_settings(data: dict):
    ensure_dir(APP_STATE_DIR)
    with SETTINGS_PATH.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)


def history_file_path() -> Path:
    return APP_STATE_DIR / "download_history.json"


def load_download_history() -> list[dict[str, str]]:
    path = history_file_path()
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
    except Exception:
        pass
    return []


def save_download_history(items: list[dict[str, str]]):
    ensure_dir(APP_STATE_DIR)
    with history_file_path().open("w", encoding="utf-8") as fh:
        json.dump(items, fh, ensure_ascii=False, indent=2)


def shell_open(path: str):
    target = normalize_path(path)
    if not target:
        raise FileNotFoundError("Путь не указан.")
    os.startfile(target)


def shell_open_url(url: str):
    os.startfile(url)


def open_folder(path: str):
    target = normalize_path(path)
    if not target:
        raise FileNotFoundError("Папка не указана.")
    Path(target).mkdir(parents=True, exist_ok=True)
    os.startfile(target)


def file_exists(path: str | None) -> bool:
    target = normalize_path(path)
    return bool(target) and Path(target).exists()


def file_name_from_path(path: str | None) -> str:
    target = normalize_path(path)
    if not target:
        return ""
    return Path(target).name


def folder_from_path(path: str | None) -> str:
    target = normalize_path(path)
    if not target:
        return ""
    return str(Path(target).parent)


def elide_middle(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    if max_chars <= 3:
        return "." * max_chars
    half = (max_chars - 3) // 2
    return text[:half] + "..." + text[-(max_chars - 3 - half):]


def ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def is_playlist_url(url: str) -> bool:
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    return bool(qs.get("list"))


def is_watch_with_playlist(url: str) -> bool:
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    return bool(qs.get("v")) and bool(qs.get("list"))


def detect_url_mode(url: str) -> str:
    if is_watch_with_playlist(url):
        return "video_in_playlist"
    if is_playlist_url(url):
        return "playlist"
    return "single"


def format_sort_for_quality(quality: str) -> str | None:
    quality = (quality or "").strip().lower()
    if not quality or quality == "best":
        return None
    if quality.endswith("p") and quality[:-1].isdigit():
        return f"res:{quality[:-1]}"
    if quality.endswith("k") and quality[:-1].isdigit():
        return None
    return None


def audio_quality_arg(quality: str) -> str:
    quality = (quality or "").strip().lower()
    if not quality or quality == "best":
        return "0"
    if quality.endswith("k") and quality[:-1].isdigit():
        return quality[:-1]
    return "0"


def cookies_contain_authorization(cookies: list[dict]) -> bool:
    auth_cookie_names = {
        "sid",
        "__secure-1psid",
        "__secure-3psid",
        "hsid",
        "ssid",
        "apisid",
        "sapisid",
        "__secure-1psidts",
        "__secure-3psidts",
        "login_info",
    }
    auth_domains = ("youtube.com", "google.com")

    for cookie in cookies:
        name = str(cookie.get("name", "")).lower()
        domain = str(cookie.get("domain", "")).lower()
        if name in auth_cookie_names and any(d in domain for d in auth_domains):
            return True
    return False


def export_cookies_from_edge(cookies_path: str) -> dict[str, object]:
    cookies_path = normalize_path(cookies_path)
    if not cookies_path:
        raise RuntimeError("Не указан путь к cookies.txt")

    ensure_parent_dir(cookies_path)

    with urlopen(EDGE_LIST_URL, timeout=3) as response:
        pages = json.loads(response.read().decode("utf-8"))

    page = None
    for item in pages:
        url = str(item.get("url", ""))
        if "youtube.com" in url or "google.com" in url:
            page = item
            break
    if not page and pages:
        page = pages[0]
    if not page:
        raise RuntimeError("Не найдена page-вкладка Edge по порту 9222")

    ws_url = page.get("webSocketDebuggerUrl")
    if not ws_url:
        raise RuntimeError("У страницы Edge нет webSocketDebuggerUrl")

    ws = websocket.create_connection(ws_url, timeout=5)
    try:
        ws.send(json.dumps({"id": 1, "method": "Network.enable"}))
        ws.recv()
        ws.send(json.dumps({"id": 2, "method": "Network.getAllCookies"}))
        raw = json.loads(ws.recv())
        cookies = raw.get("result", {}).get("cookies", [])
    finally:
        ws.close()

    authorized = cookies_contain_authorization(cookies)

    lines = [
        "# Netscape HTTP Cookie File",
        "# This file is generated by yt-dlp.  Do not edit.",
        "",
    ]

    for cookie in cookies:
        domain = cookie.get("domain", "")
        include_subdomains = "TRUE" if str(domain).startswith(".") else "FALSE"
        path = cookie.get("path", "/")
        secure = "TRUE" if cookie.get("secure") else "FALSE"
        expires = int(cookie.get("expires", 0) or 0)
        name = cookie.get("name", "")
        value = cookie.get("value", "")
        lines.append("\t".join([
            str(domain),
            include_subdomains,
            str(path),
            secure,
            str(expires),
            str(name),
            str(value),
        ]))

    with open(cookies_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")

    return {"written": len(cookies), "authorized": authorized}


def explain_cookie_refresh_error(message: str) -> str:
    text = (message or "").lower()
    if "page tab" in text or "page-вкладка" in text:
        return "Не удалось найти открытую вкладку Edge. Сначала запустите Edge для куков и дождитесь открытия страницы."
    if "127.0.0.1:9222" in text or "connection refused" in text:
        return "Не удалось подключиться к Edge DevTools. Сначала нажмите 'Запустить Edge для куков'."
    if "websocket" in text:
        return "Не удалось получить куки через DevTools Edge. Попробуйте снова после авторизации."
    if "cookies.txt" in text or "путь" in text:
        return "Не удалось сохранить cookies.txt. Проверьте путь к файлу куков."
    return f"Не удалось обновить куки: {message}"


def explain_download_error(log_text: str, return_code: int | None = None, downloaded_paths: list[str] | None = None) -> str:
    text = (log_text or "").lower()
    downloaded_paths = downloaded_paths or []

    if downloaded_paths and is_partial_playlist_success(log_text):
        return explain_partial_playlist_success(log_text, len(downloaded_paths))

    if "requested format is not available" in text:
        return "Выбранное качество недоступно для этого видео. Попробуйте другой формат или качество."
    if "ffmpeg is not installed" in text or "ffprobe or avprobe not found" in text:
        return "Не найден ffmpeg. Для этого формата или режима нужна full-версия с ffmpeg."
    if "sign in to confirm your age" in text or "use --cookies-from-browser or --cookies" in text:
        return "Для этого видео нужна авторизация. Обновите куки и попробуйте снова."
    if "video unavailable" in text:
        return "Видео недоступно. Проверьте ссылку и убедитесь, что ролик ещё существует и доступен в вашем регионе."
    if "members-only" in text or "join this channel" in text:
        return "Это видео доступно только подписчикам или участникам. Нужна авторизация с подходящим доступом."
    if "private video" in text:
        return "Видео приватное. Нужна авторизация владельца или доступ к приватному ролику."
    if "unsupported url" in text or "no suitable extractor" in text:
        return "Эта ссылка не поддерживается текущей версией yt-dlp."
    if "unable to download api page" in text or "unable to download webpage" in text or "http error 403" in text:
        return "Не удалось получить данные страницы. Возможно, нужен свежий cookies.txt или сайт временно блокирует запрос."
    if "timed out" in text or "timeout" in text:
        return "Сайт не ответил вовремя. Попробуйте снова позже."
    if "permission denied" in text or "access is denied" in text:
        return "Нет доступа к папке или файлу. Попробуйте другую папку загрузки."
    if "the system cannot find the path specified" in text or "no such file or directory" in text:
        return "Не найден путь к файлу или папке. Проверьте папку загрузки и путь к cookies.txt."
    if "unable to extract" in text or "please update" in text:
        return "Похоже, сайту нужна более новая версия yt-dlp. Обновите yt-dlp и попробуйте снова."
    if return_code and return_code != 0:
        return "Загрузка завершилась с ошибкой. Подробности смотрите в логе."
    return "Не удалось скачать файл. Подробности смотрите в логе."


def is_partial_playlist_success(log_text: str) -> bool:
    text = (log_text or "").lower()
    return "finished downloading playlist" in text and (
        "unavailable videos are hidden" in text or "video unavailable" in text
    )


def explain_partial_playlist_success(log_text: str, downloaded_count: int) -> str:
    _ = log_text
    if downloaded_count > 0:
        return "Загрузка плейлиста завершена. Доступные ролики сохранены, недоступные элементы были пропущены."
    return "Плейлист обработан, но доступных роликов для скачивания не найдено."


def read_final_path_markers(marker_path: str) -> list[str]:
    marker_path = normalize_path(marker_path)
    if not marker_path or not Path(marker_path).exists():
        return []

    result = []
    try:
        with open(marker_path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    parsed = json.loads(line)
                    if isinstance(parsed, str) and parsed:
                        result.append(normalize_path(parsed))
                except Exception:
                    continue
    except Exception:
        return []

    return [p for p in result if p]


def create_marker_file_path() -> str:
    return str(Path(tempfile.gettempdir()) / f"yt_cookie_downloader_{uuid.uuid4().hex}.jsonl")


def launch_edge_command() -> list[str]:
    edge = find_edge_executable()
    user_data = APP_STATE_DIR / "edge-profile"
    ensure_dir(user_data)
    return [
        edge,
        "--remote-debugging-port=9222",
        f"--user-data-dir={user_data}",
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    ]


def launch_edge_for_cookies():
    command = launch_edge_command()
    subprocess.Popen(command, **hidden_subprocess_kwargs())


def find_edge_executable() -> str:
    candidates = [
        os.environ.get("PROGRAMFILES(X86)", "") + r"\Microsoft\Edge\Application\msedge.exe",
        os.environ.get("PROGRAMFILES", "") + r"\Microsoft\Edge\Application\msedge.exe",
        os.environ.get("LOCALAPPDATA", "") + r"\Microsoft\Edge\Application\msedge.exe",
    ]
    for candidate in candidates:
        candidate = candidate.strip()
        if candidate and Path(candidate).exists():
            return candidate
    raise FileNotFoundError("Не удалось найти Microsoft Edge.")


_EXEC_CACHE: dict[str, str | None] = {}


def _search_local_binary(names: list[str]) -> str | None:
    for directory in LOCAL_EXEC_DIRS:
        for name in names:
            candidate = directory / name
            if candidate.exists():
                return str(candidate.resolve())
    return None


def _search_system_binary(names: list[str]) -> str | None:
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    extra = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Links",
        Path.home() / "AppData" / "Local" / "Microsoft" / "WinGet" / "Links",
    ]
    for directory in extra:
        for name in names:
            candidate = directory / name
            if candidate.exists():
                return str(candidate.resolve())
    return None


def find_binary(kind: str) -> str | None:
    key = kind.lower()
    if key in _EXEC_CACHE:
        return _EXEC_CACHE[key]

    mapping = {
        "yt-dlp": ["yt-dlp.exe", "yt-dlp"],
        "ffmpeg": ["ffmpeg.exe", "ffmpeg"],
        "ffprobe": ["ffprobe.exe", "ffprobe"],
        "deno": ["deno.exe", "deno"],
    }
    names = mapping.get(key, [kind])

    path = _search_local_binary(names)
    if not path:
        path = _search_system_binary(names)

    _EXEC_CACHE[key] = path
    return path


def dependencies_status() -> dict[str, bool]:
    return {
        "yt-dlp": bool(find_binary("yt-dlp")),
        "ffmpeg": bool(find_binary("ffmpeg")),
    }


def build_yt_dlp_command(
    url: str,
    download_dir: str,
    cookies_file: str,
    fmt: str,
    quality: str,
    marker_file: str,
    playlist_mode: str = "auto",
) -> list[str]:
    url = clean_path_string(url)
    download_dir = normalize_path(download_dir)
    cookies_file = normalize_path(cookies_file)
    marker_file = normalize_path(marker_file)

    yt_dlp = find_binary("yt-dlp")
    if not yt_dlp:
        raise FileNotFoundError("yt-dlp не найден.")

    ensure_dir(download_dir)
    ensure_parent_dir(cookies_file)
    ensure_parent_dir(marker_file)

    args = [yt_dlp]
    if cookies_file:
        args += ["--cookies", cookies_file]
    args += ["-P", download_dir]

    is_audio = fmt in AUDIO_FORMATS
    if is_audio:
        args += ["-x", "--audio-format", fmt, "--audio-quality", audio_quality_arg(quality)]

    if playlist_mode == "single":
        args.append("--no-playlist")
    elif playlist_mode == "playlist":
        args.append("--yes-playlist")
    else:
        url_mode = detect_url_mode(url)
        if url_mode == "playlist":
            args.append("--yes-playlist")
        else:
            args.append("--no-playlist")

    args += ["--print-to-file", "after_move:%(filepath)j", marker_file]

    if not is_audio:
        sort_key = format_sort_for_quality(quality)
        if fmt in VIDEO_FORMATS:
            format_selector = f"bv*+ba/b[ext={fmt}] / b"
        else:
            format_selector = "bv*+ba/b"
        args += ["-f", format_selector]
        if sort_key:
            args += ["-S", sort_key]

    args.append(url)
    return args


def build_powershell_command(arg_list: list[str]) -> str:
    escaped = []
    for arg in arg_list:
        if any(ch in str(arg) for ch in " '()[]{}&;,$"):
            escaped.append("& " + ps_quote(arg) if not escaped else ps_quote(arg))
        else:
            escaped.append("& " + arg if not escaped else arg)
    return (
        "[Console]::InputEncoding = [System.Text.UTF8Encoding]::new(); "
        "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new(); "
        "$OutputEncoding = [System.Text.UTF8Encoding]::new(); "
        "chcp 65001 > $null; "
        + " ".join(escaped)
    )
