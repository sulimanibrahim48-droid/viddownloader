import sys
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

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
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from yt_dlp import YoutubeDL

# Define constants
VIDEO_EXTENSIONS = {'.mp4', '.mkv', '.webm', '.mov', '.m4v', '.avi', '.flv'}
AUDIO_EXTENSIONS = {'.mp3', '.m4a', '.aac', '.opus', '.flac', '.wav', '.ogg'}
MEDIA_EXTENSIONS = VIDEO_EXTENSIONS | AUDIO_EXTENSIONS

# Initialize FastAPI app
app = FastAPI(title="Playlist Stitcher API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
        self.cancelled = False
        self.cancel_event = threading.Event()
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

    def cancel(self):
        self.cancelled = True
        self.cancel_event.set()
        self.add_log("🛑 Cancellation requested by user...")
        self.update_progress(self.percent, "Cancelling download...")

    def set_cancelled(self, message: str = "Download cancelled by user."):
        self.cancelled = True
        self.done = True
        self._put_event("cancelled", message)
        self.loop.call_soon_threadsafe(self.queue.put_nowait, None)

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
    """Convert YouTube watch URLs with a list id into canonical playlist URLs.

    YouTube Mix / Radio playlists (list IDs starting with 'RD') are auto-generated
    and are NOT accessible via the /playlist path. Keep the original watch URL for
    these so yt-dlp can properly enumerate the radio stream.
    """
    parsed = urlparse(url.strip())
    query = parse_qs(parsed.query)
    list_id = (query.get('list') or [None])[0]

    if not list_id:
        return url.strip()

    # YouTube Mix / Radio playlists: list IDs start with 'RD'.
    # These only work as watch URLs; converting to /playlist breaks them.
    if list_id.startswith('RD'):
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


def sanitize_filename(name: str, default: str = 'merged_playlist.mp4', format_type: str = 'mp4') -> str:
    cleaned = re.sub(r'[\\/*?:"<>|]', '_', name.strip())
    cleaned = re.sub(r'_+', '_', cleaned).strip(' _')
    target_ext = f".{format_type.lower()}"
    if not cleaned:
        cleaned = default if default.lower().endswith(target_ext) else f"merged_playlist{target_ext}"
    if cleaned.lower().endswith(('.mp4', '.mp3')):
        cleaned = cleaned.rsplit('.', 1)[0]
    cleaned += target_ext
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


def get_js_runtimes() -> dict:
    node_path = shutil.which('node') or shutil.which('node.exe')
    if node_path:
        return {'node': {'path': node_path}}
    deno_path = shutil.which('deno') or shutil.which('deno.exe')
    if deno_path:
        return {'deno': {'path': deno_path}}
    return {}


def get_yt_dlp_base_opts(ffmpeg_path: str | None = None) -> dict:
    opts: dict = {
        'remote_components': ['ejs:github'],
        'extractor_args': {
            'youtube': {
                'player_client': ['mweb', 'ios', 'android', 'web']
            }
        },
    }
    js_runtimes = get_js_runtimes()
    if js_runtimes:
        opts['js_runtimes'] = js_runtimes
    if ffmpeg_path and ffmpeg_path != 'ffmpeg':
        opts['ffmpeg_location'] = ffmpeg_path
    return opts


def get_playlist_title(url: str, ffmpeg_path: str | None, format_type: str = 'mp4') -> str:
    try:
        ydl_opts = get_yt_dlp_base_opts(ffmpeg_path)
        ydl_opts.update({
            'extract_flat': True,
            'quiet': True,
            'skip_download': True,
            'no_warnings': True,
        })

        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(normalize_playlist_url(url), download=False)
            title = info.get('title', f'merged_playlist.{format_type}')
            return sanitize_filename(title, format_type=format_type)
    except Exception:
        return f'merged_playlist.{format_type}'


def download_playlist_internal(
    playlist_url: str,
    temp_dir: Path,
    ffmpeg_path: str | None,
    max_videos: int,
    format_type: str,
    log_cb,
    progress_cb,
) -> list[Path]:
    normalized_url, is_single_video = get_source_kind(playlist_url)
    is_audio = format_type.lower() == 'mp3'
    log_cb(f'Using source URL: {normalized_url}')
    log_cb(f'Source mode: {"single item" if is_single_video else "playlist"} ({ "MP3 Audio" if is_audio else "MP4 Video" })')

    downloaded_paths: set[Path] = set()

    def internal_progress_hook(d):
        filename = d.get('filename')
        if filename:
            downloaded_paths.add(Path(filename).resolve())
        progress_cb(d)

    ydl_opts = get_yt_dlp_base_opts(ffmpeg_path)
    if is_audio:
        ydl_opts.update({
            'format': 'bestaudio/best',
            'outtmpl': str(temp_dir / ('%(title)s.%(ext)s' if is_single_video else '%(playlist_index|0001)04d_%(title)s.%(ext)s')),
            'logger': None,
            'progress_hooks': [internal_progress_hook],
            'ignoreerrors': True,
            'no_warnings': True,
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
        })
    else:
        ydl_opts.update({
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best[ext=mp4]/best',
            'outtmpl': str(temp_dir / ('%(title)s.%(ext)s' if is_single_video else '%(playlist_index|0001)04d_%(title)s.%(ext)s')),
            'logger': None,
            'progress_hooks': [internal_progress_hook],
            'ignoreerrors': True,
            'no_warnings': True,
        })

    if max_videos > 0 and not is_single_video:
        ydl_opts['playlistend'] = max_videos

    if is_single_video:
        ydl_opts['noplaylist'] = True

    with YoutubeDL(ydl_opts) as ydl:
        error_code = ydl.download([normalized_url])
        if error_code != 0:
            log_cb('Some items failed or were skipped.')

    valid_exts = AUDIO_EXTENSIONS if is_audio else VIDEO_EXTENSIONS
    downloaded_files: list[Path] = []
    for path in temp_dir.rglob('*'):
        if path.is_file() and (path.suffix.lower() in valid_exts or path.suffix.lower() in MEDIA_EXTENSIONS):
            downloaded_files.append(path)

    for path in downloaded_paths:
        if path.exists() and (path.suffix.lower() in valid_exts or path.suffix.lower() in MEDIA_EXTENSIONS):
            downloaded_files.append(path)

    unique_files = sorted({p.resolve() for p in downloaded_files})
    log_cb(f'Downloaded {len(unique_files)} media files.')
    return unique_files


def concatenate_videos_ffmpeg(video_paths: list[Path], output_path: Path, ffmpeg_path: str, format_type: str, log_cb) -> bool:
    is_audio = format_type.lower() == 'mp3' or output_path.suffix.lower() == '.mp3'
    if len(video_paths) == 1:
        log_cb('Single file detected — saving directly to output...')
        try:
            shutil.copy2(video_paths[0], output_path)
            log_cb(f'Merged file saved to {output_path}')
            return True
        except Exception as e:
            log_cb(f'Direct copy failed ({e}), attempting FFmpeg remux...')

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
            if is_audio:
                log_cb('Lossless copy failed, trying MP3 re-encoding...')
                cmd_reencode = [
                    ffmpeg_path,
                    '-y',
                    '-f', 'concat',
                    '-safe', '0',
                    '-i', str(list_file_path),
                    '-c:a', 'libmp3lame',
                    '-b:a', '192k',
                    str(output_path),
                ]
                res2 = subprocess.run(
                    cmd_reencode,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding='utf-8',
                    errors='ignore',
                )
                if res2.returncode == 0:
                    log_cb('Merged audio saved successfully.')
                    return True

            log_cb('FFmpeg copy mode failed.')
            log_cb(result.stderr[-4000:])
            return False

        log_cb(f'Merged file saved successfully.')
        return True
    finally:
        if list_file_path.exists():
            try:
                list_file_path.unlink()
            except Exception:
                pass


def concatenate_videos_moviepy(video_paths: list[Path], output_path: Path, format_type: str, log_cb) -> bool:
    is_audio = format_type.lower() == 'mp3' or output_path.suffix.lower() == '.mp3'
    if is_audio:
        try:
            from moviepy.editor import AudioFileClip, concatenate_audioclips
        except ImportError:
            log_cb('MoviePy is not installed.')
            return False

        log_cb(f'Stitching {len(video_paths)} audio files with MoviePy...')
        clips = []
        try:
            for path in video_paths:
                log_cb(f'Loading {path.name}')
                clips.append(AudioFileClip(str(path)))

            final_clip = concatenate_audioclips(clips)
            final_clip.write_audiofile(
                str(output_path),
                bitrate='192k',
                logger=None,
            )
            log_cb('Merged audio saved successfully.')
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
    else:
        try:
            from moviepy.editor import VideoFileClip, concatenate_videoclips
        except ImportError:
            log_cb('MoviePy is not installed.')
            return False

        log_cb(f'Stitching {len(video_paths)} video files with MoviePy re-encode mode...')
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
            log_cb('Merged video saved successfully.')
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

def run_stitching_thread(task_id: str, context: TaskContext, url: str, filename: str, max_videos: int, merge_mode: str, format_type: str = 'mp4'):
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
        
        target_ext = f".{format_type.lower()}"
        default_file_names = ("merged_playlist.mp4", "merged_playlist.mp3", f"merged_playlist{target_ext}")
        
        # Resolve output filename
        output_name = filename.strip()
        if not output_name or output_name.lower().endswith(default_file_names):
            context.update_progress(0.01, "Fetching playlist metadata...")
            resolved_title = get_playlist_title(normalized_url, ffmpeg_path, format_type=format_type)
            output_name = resolved_title
            context.add_log(f"Resolved playlist title: {output_name}")
            
        output_name = sanitize_filename(output_name, format_type=format_type)
        
        # Prepare cache location for serving downloads
        cache_dir = Path(tempfile.gettempdir()) / "playlist_stitcher_web_cache" / task_id
        cache_dir.mkdir(parents=True, exist_ok=True)
        final_output_path = cache_dir / output_name
        
        context.update_progress(0.02, f"Downloading playlist files ({'MP3 Audio' if format_type == 'mp3' else 'MP4 Video'})...")
        
        # Progress callback for YoutubeDL
        def progress_cb(d):
            if context.cancel_event.is_set():
                raise Exception("Download cancelled by user.")

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
                    context.update_progress(overall_pct, f"Downloading item {idx} of {n_entries}: {basename[:30]} ({pct*100:.1f}%)")
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
            format_type,
            context.add_log,
            progress_cb
        )

        if context.cancel_event.is_set():
            context.add_log("🛑 Download cancelled by user.")
            context.set_cancelled("Download was cancelled by user.")
            return

        if not downloaded_files:
            context.set_error("No media files could be downloaded. Check if the playlist link is valid and public.")
            return

        context.update_progress(0.85, "Stitching downloaded files together...")
        
        success = False
        if merge_mode == 'MoviePy re-encode':
            success = concatenate_videos_moviepy(downloaded_files, final_output_path, format_type=format_type, log_cb=context.add_log)
        elif merge_mode == 'FFmpeg copy':
            if not ffmpeg_path:
                context.add_log("FFmpeg was not found. Falling back to MoviePy re-encoding...")
                success = concatenate_videos_moviepy(downloaded_files, final_output_path, format_type=format_type, log_cb=context.add_log)
            else:
                success = concatenate_videos_ffmpeg(downloaded_files, final_output_path, ffmpeg_path, format_type=format_type, log_cb=context.add_log)
        else: # Auto mode
            if ffmpeg_path:
                success = concatenate_videos_ffmpeg(downloaded_files, final_output_path, ffmpeg_path, format_type=format_type, log_cb=context.add_log)
            else:
                success = concatenate_videos_moviepy(downloaded_files, final_output_path, format_type=format_type, log_cb=context.add_log)

        if context.cancel_event.is_set():
            context.add_log("🛑 Process cancelled by user.")
            context.set_cancelled("Download was cancelled by user.")
            return

        if success and final_output_path.exists():
            file_size_mb = final_output_path.stat().st_size / (1024 * 1024)
            context.update_progress(1.0, "Ready")
            context.add_log(f"Stitch completed successfully: {output_name} ({file_size_mb:.2f} MB)")
            
            task_files[task_id] = final_output_path
            context.set_success(f"/api/download/{task_id}", output_name, file_size_mb)
        else:
            context.set_error("Stitching process failed. See logs below.")

    except Exception as e:
        if context.cancel_event.is_set():
            context.add_log("🛑 Process cancelled by user.")
            context.set_cancelled("Download was cancelled by user.")
        else:
            context.add_log(f"Exception during stitching: {str(e)}")
            context.set_error(f"Stitch thread crashed: {str(e)}")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

# --- API ENDPOINTS ---

@app.post("/api/stitch")
async def start_stitch(
    url: str = Form(...),
    filename: str = Form(""),
    max_videos: int = Form(0),
    merge_mode: str = Form("Auto"),
    format_type: str = Form("mp4")
):
    if not url.strip():
        raise HTTPException(status_code=400, detail="Playlist URL is required.")
        
    task_id = str(uuid.uuid4())
    loop = asyncio.get_running_loop()
    context = TaskContext(loop)
    tasks[task_id] = context
    
    fmt = format_type.lower() if format_type.lower() in ("mp4", "mp3") else "mp4"
    
    # Run the worker thread
    thread = threading.Thread(
        target=run_stitching_thread,
        args=(task_id, context, url.strip(), filename, max_videos, merge_mode, fmt),
        daemon=True
    )
    thread.start()
    
    return {"task_id": task_id}


@app.post("/api/cancel/{task_id}")
async def cancel_task(task_id: str):
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="Task not found.")
    task = tasks[task_id]
    task.cancel()
    return {"status": "cancelled"}


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
            if task.cancelled:
                yield f"event: cancelled\ndata: \"Download cancelled by user.\"\n\n"
            elif task.success:
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
    
    media_type = "audio/mpeg" if file_path.suffix.lower() == ".mp3" else "video/mp4"
    return FileResponse(
        path=file_path,
        filename=file_path.name,
        media_type=media_type
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
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=False)
