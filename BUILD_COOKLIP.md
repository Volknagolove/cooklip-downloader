# Cooklip Build

Сборка делается через `PyInstaller` из:

- [cooklip_gui.py](Z:\metube\cooklip_gui.py)
- [cooklip_gui_ru.py](Z:\metube\cooklip_gui_ru.py)

## Что установить

```powershell
py -m pip install pyinstaller
py -m pip install PySide6 PySide6-Fluent-Widgets websocket-client
```

## Как собрать

```powershell
powershell -ExecutionPolicy Bypass -File .\build_cooklip.ps1
```

Скрипт:

- пересобирает Qt resource-иконку из `cooklip.ico`
- собирает `Cooklip.exe`
- собирает `Cooklip_RU.exe`
- создаёт папки:
  - `release/Cooklip-lite`
  - `release/Cooklip-full`
  - `release/Cooklip-RU-lite`
  - `release/Cooklip-RU-full`
- кладёт в `lite`:
  - `yt-dlp.exe`
  - `deno.exe`
- кладёт в `full`:
  - `yt-dlp.exe`
  - `deno.exe`
  - `ffmpeg.exe`
  - `ffprobe.exe`
- создаёт zip-архивы всех четырёх релизов

## Что получится

- `Cooklip-lite`
- `Cooklip-full`
- `Cooklip-RU-lite`
- `Cooklip-RU-full`

Все пользовательские данные создаются уже при запуске приложения в папке `data` рядом с `exe`, а не попадают в release заранее.
