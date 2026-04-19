# Cooklip Build

The build script creates all four release variants:

- `Cooklip-lite`
- `Cooklip-full`
- `Cooklip-EN-lite`
- `Cooklip-EN-full`

## Requirements

```powershell
py -m pip install pyinstaller
py -m pip install PySide6 PySide6-Fluent-Widgets websocket-client
```

The build also expects these tools to be available locally or in `bin/`:

- `yt-dlp.exe`
- `ffmpeg.exe`
- `ffprobe.exe`

## Build Command

```powershell
powershell -ExecutionPolicy Bypass -File .\build_cooklip.ps1
```

## What The Script Does

- regenerates the Qt resource module from `cooklip.ico`
- builds English and Russian executables with `PyInstaller`
- creates `lite` and `full` release folders
- puts `yt-dlp.exe` into `lite` and `full`
- puts `ffmpeg.exe` and `ffprobe.exe` into `full`
- creates zip archives for all release variants

## Notes

User data is not included in releases. The app creates its own `data/` folder on first run.
