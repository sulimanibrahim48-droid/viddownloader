# 🎬 Playlist Stitcher

A clean desktop application that downloads playlists and merges them into a single, seamless video file.

## Features

- Modern dark-themed GUI built with `customtkinter`
- Downloads entire playlists using `yt-dlp`
- Lossless FFmpeg concatenation (instant, no re-encoding)
- MoviePy fallback for mixed-format playlists
- Auto-detects the Downloads folder for saving
- Automated cleanup of temporary files

## Download

👉 **[Download PlaylistStitcher.exe from Releases](../../releases/latest)**

Just download and double-click — no installation required!

## Usage

1. Paste a playlist URL
2. Click **Download & Merge Playlist**
3. Wait for the process to complete
4. Your merged video will be saved in your Downloads folder

## Building from Source

If you want to run from source code instead:

```bash
pip install -r requirements.txt
python playlist_stitcher.py
```

## License

Free to use and share.
