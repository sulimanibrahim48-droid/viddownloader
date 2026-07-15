from __future__ import annotations

import os
import re
import uuid
import shutil
import asyncio
import threading
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlunparse, urlparse
from typing import Dict
import socket

import uvicorn
from fastapi import FastAPI, Form, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from yt_dlp import YoutubeDL

# Define constants
VIDEO_EXTENSIONS = {'.mp4', '.mkv', '.webm', '.mov', '.m4v', '.avi', '.flv'}

# Initialize FastAPI app
app = FastAPI(title="Playlist Stitcher API", version="1.0.0")

# Store background tasks and their active connections/status
class TaskContext:
    def __init__(self, loop: asyncio.AbstractEventLoop):
        self.loop = loop
        self.queue = asyncio.Queue()
        self.logs = []
        self.percent = 0.0
        self.status = "Pending"
        self.error = None
        self.success = False
        self.download_url = None
        self.filename = None
        self.file_size = 0.0
        self.done = False

    def _put_event(self, event_type: str, data):
        item = {"event": event_type, "data": data}
        self.loop.call_soon_threadsafe(self.queue.put_nowait, item)

    def add_log(self, message: str):
        self.logs.append(message)
        self._put_event("log", message)

    def update_progress(self, percent: float, status: str):
        self.percent = percent
        self.status = status
        self._put_event("progress", {"percent": percent, "status": status})

    def set_success(self, download_url: str, filename: str, file_size: float):
        self.success = True
        self.download_url = download_url
        self.filename = filename
        self.file_size = file_size
        self.done = True
        self._put_event("success", {"download_url": download_url, "filename": filename, "size_mb": file_size})
        # Put sentinel
        self.loop.call_soon_threadsafe(self.queue.put_nowait, None)

    def set_error(self, error_msg: str):
        self.error = error_msg
        self.done = True
        self._put_event("error", error_msg)
        # Put sentinel
        self.loop.call_soon_threadsafe(self.queue.put_nowait, None)

# In-memory storage for active tasks
tasks: Dict[str, TaskContext] = {}
# Maps task_id -> output video file Path
task_files: Dict[str, Path] = {}

# --- HELPER FUNCTIONS ---

def normalize_playlist_url(url: str) -> str:
    parsed = urlparse(url.strip())
    query = parse_qs(parsed.query)
    list_id = (query.get('list') or [None])[0]

    if not list_id:
        return url.strip()

    host = parsed.netloc.lower()
    path = parsed.path.lower()
    if 'youtube.com' in host and path == '/watch':
        return urlunparse(
            (
                parsed.scheme or 'https',
                'www.youtube.com',
                '/playlist',
                '',
                urlencode({'list': list_id}),
                '',
            )
        )
    return url.strip()


def get_source_kind(url: str) -> tuple[str, bool]:
    parsed = urlparse(url.strip())
    query = parse_qs(parsed.query)
    list_id = (query.get('list') or [None])[0]

    if not list_id:
        return url.strip(), True

    host = parsed.netloc.lower()
    path = parsed.path.lower()
    if 'youtube.com' in host and path == '/watch':
        return normalize_playlist_url(url), False

    return url.strip(), False


def sanitize_filename(name: str, default: str = 'merged_playlist.mp4') -> str:
    cleaned = re.sub(r'[\\/*?:"<>|]', '_', name.strip())
    cleaned = re.sub(r'_+', '_', cleaned).strip(' _')
    if not cleaned:
        cleaned = default
    if not cleaned.lower().endswith('.mp4'):
        cleaned += '.mp4'
    return cleaned


def get_ffmpeg_path() -> str | None:
    system_ffmpeg = shutil.which('ffmpeg')
    if system_ffmpeg:
        return system_ffmpeg

    try:
        import imageio_ffmpeg
        ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
        if ffmpeg_path and os.path.exists(ffmpeg_path):
            return ffmpeg_path
    except ImportError:
        pass

    return None


def get_playlist_title(url: str, ffmpeg_path: str | None) -> str:
    try:
        ydl_opts = {
            'extract_flat': True,
            'quiet': True,
            'skip_download': True,
            'no_warnings': True,
        }
        if ffmpeg_path and ffmpeg_path != 'ffmpeg':
            ydl_opts['ffmpeg_location'] = ffmpeg_path

        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(normalize_playlist_url(url), download=False)
            title = info.get('title', 'merged_playlist')
            return sanitize_filename(title)
    except Exception:
        return 'merged_playlist.mp4'


def download_playlist_internal(
    playlist_url: str,
    temp_dir: Path,
    ffmpeg_path: str | None,
    max_videos: int,
    log_cb,
    progress_cb,
) -> list[Path]:
    normalized_url, is_single_video = get_source_kind(playlist_url)
    log_cb(f'Using source URL: {normalized_url}')
    log_cb(f'Source mode: {"single video" if is_single_video else "playlist"}')

    downloaded_paths: set[Path] = set()

    def internal_progress_hook(d):
        filename = d.get('filename')
        if filename:
            downloaded_paths.add(Path(filename).resolve())
        progress_cb(d)

    ydl_opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]',
        'outtmpl': str(temp_dir / ('%(title)s.%(ext)s' if is_single_video else '%(playlist_index)04d_%(title)s.%(ext)s')),
        'logger': None,
        'progress_hooks': [internal_progress_hook],
        'ignoreerrors': True,
        'no_warnings': True,
    }

    if max_videos > 0 and not is_single_video:
        ydl_opts['playlistend'] = max_videos

    if is_single_video:
        ydl_opts['noplaylist'] = True

    if ffmpeg_path and ffmpeg_path != 'ffmpeg':
        ydl_opts['ffmpeg_location'] = ffmpeg_path

    with YoutubeDL(ydl_opts) as ydl:
        error_code = ydl.download([normalized_url])
        if error_code != 0:
            log_cb('Some items failed or were skipped.')

    downloaded_files: list[Path] = []
    for path in temp_dir.rglob('*'):
        if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS:
            downloaded_files.append(path)

    for path in downloaded_paths:
        if path.exists() and path.suffix.lower() in VIDEO_EXTENSIONS:
            downloaded_files.append(path)

    unique_files = sorted({p.resolve() for p in downloaded_files})
    log_cb(f'Downloaded {len(unique_files)} media files.')
    return unique_files


def concatenate_videos_ffmpeg(video_paths: list[Path], output_path: Path, ffmpeg_path: str, log_cb) -> bool:
    log_cb(f'Stitching {len(video_paths)} files with FFmpeg copy mode...')
    list_file_path = output_path.parent / 'ffmpeg_concat_list.txt'

    with list_file_path.open('w', encoding='utf-8') as handle:
        for path in video_paths:
            escaped_path = str(path.resolve()).replace("'", "'\\''")
            handle.write(f"file '{escaped_path}'\n")

    try:
        cmd = [
            ffmpeg_path,
            '-y',
            '-f', 'concat',
            '-safe', '0',
            '-i', str(list_file_path),
            '-c', 'copy',
            str(output_path),
        ]
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8',
            errors='ignore',
        )

        if result.returncode != 0:
            log_cb('FFmpeg copy mode failed.')
            log_cb(result.stderr[-4000:])
            return False

        log_cb(f'Merged video saved successfully.')
        return True
    finally:
        if list_file_path.exists():
            try:
                list_file_path.unlink()
            except Exception:
                pass


def concatenate_videos_moviepy(video_paths: list[Path], output_path: Path, log_cb) -> bool:
    try:
        from moviepy.editor import VideoFileClip, concatenate_videoclips
    except ImportError:
        log_cb('MoviePy is not installed.')
        return False

    log_cb(f'Stitching {len(video_paths)} files with MoviePy re-encode mode...')
    clips = []
    try:
        for path in video_paths:
            log_cb(f'Loading {path.name}')
            clips.append(VideoFileClip(str(path)))

        final_clip = concatenate_videoclips(clips, method='compose')
        final_clip.write_videofile(
            str(output_path),
            codec='libx264',
            audio_codec='aac',
            temp_audiofile='temp-audio.m4a',
            remove_temp=True,
            logger=None,
        )
        log_cb(f'Merged video saved successfully.')
        return True
    except Exception as exc:
        log_cb(f'MoviePy failed: {exc}')
        return False
    finally:
        for clip in clips:
            try:
                clip.close()
            except Exception:
                pass

# --- BACKGROUND STITCH TASK ---

def run_stitching_thread(task_id: str, context: TaskContext, url: str, filename: str, max_videos: int, merge_mode: str):
    temp_dir = Path(tempfile.mkdtemp(prefix=f"playlist_stitcher_web_{task_id}_"))
    context.add_log("Backend process spawned successfully.")
    
    ffmpeg_path = get_ffmpeg_path()
    if not ffmpeg_path:
        context.add_log("FFmpeg was not detected on system PATH or via imageio-ffmpeg.")
    else:
        context.add_log(f"Using FFmpeg binary at: {ffmpeg_path}")

    try:
        normalized_url = normalize_playlist_url(url)
        context.add_log(f"Target URL: {normalized_url}")
        
        # Resolve output filename
        output_name = filename.strip()
        if not output_name or output_name.lower().endswith("merged_playlist.mp4"):
            context.update_progress(0.01, "Fetching playlist metadata...")
            resolved_title = get_playlist_title(normalized_url, ffmpeg_path)
            output_name = resolved_title
            context.add_log(f"Resolved playlist title: {output_name}")
            
        output_name = sanitize_filename(output_name)
        
        # Prepare cache location for serving downloads
        cache_dir = Path(tempfile.gettempdir()) / "playlist_stitcher_web_cache" / task_id
        cache_dir.mkdir(parents=True, exist_ok=True)
        final_output_path = cache_dir / output_name
        
        context.update_progress(0.02, "Downloading playlist files...")
        
        # Progress callback for YoutubeDL
        def progress_cb(d):
            if d['status'] == 'downloading':
                total = d.get('total_bytes') or d.get('total_bytes_estimate')
                downloaded = d.get('downloaded_bytes', 0)
                pct = downloaded / total if total else 0.0
                
                info = d.get('info_dict', {})
                idx = info.get('playlist_index')
                n_entries = info.get('n_entries')
                basename = os.path.basename(d.get('filename', ''))
                
                if idx and n_entries:
                    overall_pct = (idx - 1) / n_entries + (pct / n_entries)
                    overall_pct = min(overall_pct * 0.85, 0.85) # Reserve 0.85-1.00 for stitching
                    context.update_progress(overall_pct, f"Downloading video {idx} of {n_entries}: {basename[:30]} ({pct*100:.1f}%)")
                else:
                    context.update_progress(pct * 0.85, f"Downloading: {basename[:40]} ({pct*100:.1f}%)")
                    
            elif d['status'] == 'finished':
                context.add_log(f"Finished downloading: {os.path.basename(d.get('filename', ''))}")

        # Download playlist
        downloaded_files = download_playlist_internal(
            normalized_url,
            temp_dir,
            ffmpeg_path,
            max_videos,
            context.add_log,
            progress_cb
        )

        if not downloaded_files:
            context.set_error("No video files could be downloaded. Check if the playlist link is valid and public.")
            return

        context.update_progress(0.85, "Stitching downloaded videos together...")
        
        success = False
        if merge_mode == 'MoviePy re-encode':
            success = concatenate_videos_moviepy(downloaded_files, final_output_path, context.add_log)
        elif merge_mode == 'FFmpeg copy':
            if not ffmpeg_path:
                context.add_log("FFmpeg was not found. Falling back to MoviePy re-encoding...")
                success = concatenate_videos_moviepy(downloaded_files, final_output_path, context.add_log)
            else:
                success = concatenate_videos_ffmpeg(downloaded_files, final_output_path, ffmpeg_path, context.add_log)
        else: # Auto mode
            if ffmpeg_path:
                success = concatenate_videos_ffmpeg(downloaded_files, final_output_path, ffmpeg_path, context.add_log)
            else:
                success = concatenate_videos_moviepy(downloaded_files, final_output_path, context.add_log)

        if success and final_output_path.exists():
            file_size_mb = final_output_path.stat().st_size / (1024 * 1024)
            context.update_progress(1.0, "Ready")
            context.add_log(f"Stitch completed successfully: {output_name} ({file_size_mb:.2f} MB)")
            
            task_files[task_id] = final_output_path
            context.set_success(f"/api/download/{task_id}", output_name, file_size_mb)
        else:
            context.set_error("Stitching process failed. See logs below.")

    except Exception as e:
        context.add_log(f"Exception during stitching: {str(e)}")
        context.set_error(f"Stitch thread crashed: {str(e)}")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

# --- API ENDPOINTS ---

@app.post("/api/stitch")
async def start_stitch(
    url: str = Form(...),
    filename: str = Form("merged_playlist.mp4"),
    max_videos: int = Form(0),
    merge_mode: str = Form("Auto")
):
    if not url.strip():
        raise HTTPException(status_code=400, detail="Playlist URL is required.")
        
    task_id = str(uuid.uuid4())
    loop = asyncio.get_running_loop()
    context = TaskContext(loop)
    tasks[task_id] = context
    
    # Run the worker thread
    thread = threading.Thread(
        target=run_stitching_thread,
        args=(task_id, context, url.strip(), filename, max_videos, merge_mode),
        daemon=True
    )
    thread.start()
    
    return {"task_id": task_id}


@app.get("/api/stream/{task_id}")
async def stream_task_progress(task_id: str):
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="Task not found.")
        
    async def sse_generator():
        task = tasks[task_id]
        
        # Send initial status
        # First send existing logs to populate UI on reconnect
        for log in task.logs:
            yield f"event: log\ndata: {log}\n\n"
        yield f"event: progress\ndata: {{\"percent\": {task.percent}, \"status\": \"{task.status}\"}}\n\n"
        
        if task.done:
            if task.success:
                yield f"event: success\ndata: {{\"download_url\": \"{task.download_url}\", \"filename\": \"{task.filename}\", \"size_mb\": {task.file_size}}}\n\n"
            else:
                yield f"event: error\ndata: \"{task.error or 'Stitching failed.'}\"\n\n"
            return
            
        # Yield dynamic updates
        while True:
            item = await task.queue.get()
            if item is None:
                # Sentinel signaling end of stream
                break
            
            import json
            event_type = item["event"]
            event_data = item["data"]
            yield f"event: {event_type}\ndata: {json.dumps(event_data)}\n\n"

    return StreamingResponse(sse_generator(), media_type="text/event-stream")


@app.get("/api/download/{task_id}")
async def download_file(task_id: str, background_tasks: BackgroundTasks):
    if task_id not in task_files:
        raise HTTPException(status_code=404, detail="Requested file not found or already deleted.")
        
    file_path = task_files[task_id]
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File does not exist on disk.")

    # Cleanup function helper to delete files after serving
    def cleanup_file():
        try:
            # Delete directory containing the file
            parent_dir = file_path.parent
            shutil.rmtree(parent_dir, ignore_errors=True)
            task_files.pop(task_id, None)
            tasks.pop(task_id, None)
        except Exception:
            pass

    background_tasks.add_task(cleanup_file)
    
    return FileResponse(
        path=file_path,
        filename=file_path.name,
        media_type="video/mp4"
    )

def get_local_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # doesn't even have to be reachable
        s.connect(('10.254.254.254', 1))
        IP = s.getsockname()[0]
    except Exception:
        IP = '127.0.0.1'
    finally:
        s.close()
    return IP

@app.on_event("startup")
def startup_event():
    local_ip = get_local_ip()
    port = 8000
    url = f"http://{local_ip}:{port}"
    
    print("\n" + "="*60)
    print("PLAYLIST STITCHER MOBILE SERVER ACTIVE!")
    print("="*60)
    print("To access the app on your mobile phone:")
    print("1. Connect your phone to the SAME Wi-Fi network.")
    print("2. Scan this QR Code or open the link below in Chrome/Safari:")
    print(f"\nURL: {url}\n")
    
    try:
        import sys
        if hasattr(sys.stdout, 'reconfigure'):
            try:
                sys.stdout.reconfigure(encoding='utf-8')
            except Exception:
                pass
        import qrcode
        qr = qrcode.QRCode(version=1, box_size=1, border=1)
        qr.add_data(url)
        qr.make(fit=True)
        print("QR CODE FOR QUICK SCAN:")
        qr.print_ascii(invert=True)
    except ImportError:
        print("Tip: Run 'pip install qrcode' to print a scanable QR code here.")
    except Exception as e:
        print(f"Could not render ASCII QR code on this terminal environment: {e}")
        
    print("="*60 + "\n")

# Clean up task cache folders that might remain from crashes/abandoned runs
def cleanup_stale_cache():
    try:
        cache_base = Path(tempfile.gettempdir()) / "playlist_stitcher_web_cache"
        if cache_base.exists():
            shutil.rmtree(cache_base, ignore_errors=True)
    except Exception:
        pass

cleanup_stale_cache()

# Mount static files (must be at the bottom so it doesn't shadow the API routes)
static_path = Path(__file__).parent / "static"
static_path.mkdir(exist_ok=True)

app.mount("/", StaticFiles(directory=str(static_path), html=True), name="static")

if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
