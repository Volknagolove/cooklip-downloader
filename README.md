# Cooklip Downloader

Cooklip Downloader is a desktop GUI for `yt-dlp` with Microsoft Edge cookie support. It can download video, audio, or playlists from YouTube, Twitch, TikTok, and many other platforms supported by `yt-dlp`.

## Features

- download video or audio from a link
- download playlists
- refresh `cookies.txt` from Microsoft Edge
- choose format and quality
- keep a history of downloaded files
- portable `data/` folder next to the app
- English default GUI and separate Russian GUI versions
- built with Python, PySide6, QFluentWidgets, `yt-dlp`, and `ffmpeg`

## Interface

![Cooklip Screenshot](docs/screenshot-main.png)

## Project Files

- `cooklip_core.py` - English core logic
- `cooklip_gui.py` - English GUI
- `cooklip_core_ru.py` - Russian core logic
- `cooklip_gui_ru.py` - Russian GUI
- `cooklip_resources.qrc` - Qt resource definition
- `cooklip_resources_rc.py` - generated Qt resource module
- `cooklip.ico` - application icon
- `build_cooklip.ps1` - build script for all release variants

## Release Variants

### Lite

- includes the app executable
- includes `yt-dlp.exe`
- does not include `ffmpeg`

### Full

- includes the app executable
- includes `yt-dlp.exe`
- includes `ffmpeg.exe`
- includes `ffprobe.exe`

## Portable Data

Cooklip stores user files next to the app in a `data` folder:

- settings: `data/cooklip_settings.json`
- cookies: `data/cookies.txt`

This keeps the app portable and makes cookies easy to find and replace.

## Build

See `BUILD_COOKLIP.md` for build instructions.

