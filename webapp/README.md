# Playlist Stitcher Web App

A separate web version of the playlist downloader and merger.

## Run locally

```bash
cd webapp
pip install -r requirements.txt
streamlit run streamlit_app.py
```

## What it does

- Accepts a YouTube playlist URL
- Downloads the playlist on the server or local machine
- Merges the videos with FFmpeg or MoviePy
- Returns the final merged file as a browser download
- Supports an optional max-videos limit for quick tests and smaller hosted runs

## Free hosting options

Good free-tier options for this app:

- Streamlit Community Cloud
- Hugging Face Spaces

For hosting, push the `webapp/` folder into a separate repository or subdirectory and connect it to the platform.

## Notes

- This web app is separate from the Windows `.exe` version.
- Large playlists may take time and may be limited by the free host's runtime or memory limits.
- For quick testing, set "Max videos to process" to 1.
