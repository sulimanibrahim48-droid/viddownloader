#!/usr/bin/env python3
"""
Playlist Stitcher GUI & CLI
===========================
A clean, production-ready desktop application and CLI tool that downloads 
playlists using `yt-dlp` and merges them into a single, seamless video file.

Features:
---------
- Modern desktop GUI built with `customtkinter`.
- Threaded execution prevents UI freezing during downloads/merges.
- Real-time overall progress bar and console logs in the GUI.
- Direct FFmpeg concatenation (lossless, instant) with MoviePy fallback.
- Auto-detects system FFmpeg or falls back to `imageio-ffmpeg` binary.
- Graceful error handling and automated cleanup.

Requirements:
-------------
    pip install -r requirements.txt
"""

import os
import sys

if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

import shutil
import argparse
import subprocess
import threading
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from yt_dlp import YoutubeDL

VIDEO_EXTENSIONS = {'.mp4', '.mkv', '.webm', '.mov', '.m4v', '.avi', '.flv'}
AUDIO_EXTENSIONS = {'.mp3', '.m4a', '.aac', '.opus', '.flac', '.wav', '.ogg'}
MEDIA_EXTENSIONS = VIDEO_EXTENSIONS | AUDIO_EXTENSIONS

# Configure stdout/stderr to use UTF-8 to avoid UnicodeEncodeErrors on Windows terminals
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

# Try to import GUI dependencies
try:
    import customtkinter as ctk
    from tkinter import filedialog, messagebox
    GUI_AVAILABLE = True
except ImportError:
    GUI_AVAILABLE = False

class YDLLogger:
    """Redirects yt-dlp logs to our custom logging callback."""
    def __init__(self, log_cb):
        self.log_cb = log_cb
        
    def debug(self, msg):
        # Filter out progress bar logs to avoid textbox clutter
        if msg.startswith('[download]') and '%' in msg:
            pass
        else:
            self.log_cb(msg)
            
    def info(self, msg):
        self.log_cb(msg)
        
    def warning(self, msg):
        self.log_cb(f"⚠️ {msg}")
        
    def error(self, msg):
        self.log_cb(f"❌ {msg}")

def get_ffmpeg_path():
    """
    Locates the FFmpeg executable.
    Checks the system PATH first, then tries to fall back to the executable 
    provided by the `imageio-ffmpeg` package if installed.
    """
    # 1. Check system PATH
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        return system_ffmpeg
    
    # 2. Try to load from imageio_ffmpeg
    try:
        import imageio_ffmpeg
        ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
        if ffmpeg_path and os.path.exists(ffmpeg_path):
            return ffmpeg_path
    except ImportError:
        pass
        
    return None

def get_js_runtimes():
    """Finds node or deno executable to allow yt-dlp to solve YouTube JS challenges."""
    node_path = shutil.which("node") or shutil.which("node.exe")
    if node_path:
        return {'node': {'path': node_path}}
    deno_path = shutil.which("deno") or shutil.which("deno.exe")
    if deno_path:
        return {'deno': {'path': deno_path}}
    return {}

def get_yt_dlp_base_opts(ffmpeg_path=None):
    """Returns base options for yt-dlp ensuring compatibility with YouTube changes."""
    opts = {
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
    if ffmpeg_path and ffmpeg_path != "ffmpeg":
        opts['ffmpeg_location'] = ffmpeg_path
    return opts

def normalize_playlist_url(url):
    """Convert YouTube watch URLs with a list id into canonical playlist URLs.
    
    YouTube Mix / Radio playlists (list IDs starting with 'RD', 'RDMM', 'RDEM', etc.)
    are auto-generated and are NOT accessible via the /playlist path. For these, we
    keep the original watch URL so yt-dlp can properly enumerate the radio stream.
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
        return urlunparse((
            parsed.scheme or 'https',
            'www.youtube.com',
            '/playlist',
            '',
            urlencode({'list': list_id}),
            '',
        ))

    return url.strip()

def download_playlist(playlist_url, temp_dir, format_type="mp4", ffmpeg_path=None, log_cb=print, progress_cb=None):
    """
    Downloads all items from the given playlist into the specified temp directory.
    Supports 'mp4' (video) and 'mp3' (audio).
    Uses zero-padded playlist indices to preserve the correct chronological order.
    """
    playlist_url = normalize_playlist_url(playlist_url)
    is_audio = format_type.lower() == "mp3"
    log_cb(f"🚀 Initializing download ({'MP3 Audio' if is_audio else 'MP4 Video'}) for: {playlist_url}")

    downloaded_paths = set()
    
    # Set up the progress hook wrapper
    def internal_progress_hook(d):
        filename = d.get('filename')
        if filename:
            downloaded_paths.add(os.path.abspath(filename))

        if progress_cb:
            progress_cb(d)
            
    # Configure yt-dlp options
    ydl_opts = get_yt_dlp_base_opts(ffmpeg_path)
    
    if is_audio:
        ydl_opts.update({
            'format': 'bestaudio/best',
            'outtmpl': os.path.join(temp_dir, '%(playlist_index|0001)04d_%(title)s.%(ext)s'),
            'logger': YDLLogger(log_cb),
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
            'outtmpl': os.path.join(temp_dir, '%(playlist_index|0001)04d_%(title)s.%(ext)s'),
            'logger': YDLLogger(log_cb),
            'progress_hooks': [internal_progress_hook],
            'ignoreerrors': True,  # Skip private/deleted videos instead of crashing
            'no_warnings': True,
        })
    
    with YoutubeDL(ydl_opts) as ydl:
        error_code = ydl.download([playlist_url])
        if error_code != 0:
            log_cb("⚠️ Some items in the playlist failed to download or were skipped.")

    # Gather and sort the downloaded media files.
    valid_exts = AUDIO_EXTENSIONS if is_audio else VIDEO_EXTENSIONS
    downloaded_files = []
    for root, _, files in os.walk(temp_dir):
        for file in files:
            ext = os.path.splitext(file)[1].lower()
            if ext in valid_exts or ext in MEDIA_EXTENSIONS:
                downloaded_files.append(os.path.join(root, file))

    # Include files reported by yt-dlp even if they were not discovered by extension scan yet.
    for path in downloaded_paths:
        if (os.path.splitext(path)[1].lower() in valid_exts or os.path.splitext(path)[1].lower() in MEDIA_EXTENSIONS) and os.path.exists(path):
            downloaded_files.append(path)

    # Sort numerically based on the zero-padded index filename prefix, then deduplicate.
    downloaded_files = sorted(set(downloaded_files))
    
    return downloaded_files

def concatenate_videos_ffmpeg(video_paths, output_filename, ffmpeg_path, format_type="mp4", log_cb=print):
    """
    Concatenates videos/audios using the FFmpeg concat demuxer.
    This is extremely fast, lossless, and does not re-encode streams unless necessary.
    """
    is_audio = format_type.lower() == "mp3" or output_filename.lower().endswith(".mp3")
    media_name = "audio files" if is_audio else "videos"

    if len(video_paths) == 1:
        log_cb(f"🔄 Single item detected — saving directly to output...")
        try:
            shutil.copy2(video_paths[0], output_filename)
            log_cb(f"🎉 Success! File saved as: {output_filename}")
            return True
        except Exception as e:
            log_cb(f"⚠️ Direct copy failed ({e}), attempting FFmpeg remux...")

    log_cb(f"🔄 Stitching {len(video_paths)} {media_name} using FFmpeg (lossless copy)...")
    
    list_file_path = os.path.join(os.path.dirname(output_filename) or '.', "ffmpeg_concat_list.txt")
    
    # Write paths to the list file. FFmpeg requires escaping single quotes and backslashes.
    with open(list_file_path, "w", encoding="utf-8") as f:
        for path in video_paths:
            abs_path = os.path.abspath(path)
            escaped_path = abs_path.replace("'", "'\\''")
            f.write(f"file '{escaped_path}'\n")
            
    try:
        cmd = [
            ffmpeg_path,
            "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", list_file_path,
            "-c", "copy",
            output_filename
        ]
        
        log_cb(f"Running FFmpeg: {' '.join(cmd)}")
        
        result = subprocess.run(
            cmd, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE, 
            text=True,
            encoding='utf-8',
            errors='ignore'
        )
        
        if result.returncode != 0:
            if is_audio:
                log_cb("⚠️ Lossless audio copy failed, attempting MP3 re-encoding...")
                cmd_reencode = [
                    ffmpeg_path,
                    "-y",
                    "-f", "concat",
                    "-safe", "0",
                    "-i", list_file_path,
                    "-c:a", "libmp3lame",
                    "-b:a", "192k",
                    output_filename
                ]
                result2 = subprocess.run(
                    cmd_reencode,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding='utf-8',
                    errors='ignore'
                )
                if result2.returncode == 0:
                    log_cb(f"🎉 Success! Merged audio saved as: {output_filename}")
                    return True

            log_cb("❌ FFmpeg concatenation failed.")
            log_cb(f"Error Output:\n{result.stderr}")
            return False
            
        log_cb(f"🎉 Success! Merged file saved as: {output_filename}")
        return True
        
    finally:
        if os.path.exists(list_file_path):
            try:
                os.remove(list_file_path)
            except Exception as e:
                log_cb(f"⚠️ Could not remove temporary list file: {e}")

def concatenate_videos_moviepy(video_paths, output_filename, format_type="mp4", log_cb=print):
    """
    Fallback concatenation using MoviePy.
    Re-encodes clips to ensure resolution, sample rate, and codec mismatches are handled.
    """
    is_audio = format_type.lower() == "mp3" or output_filename.lower().endswith(".mp3")
    
    if is_audio:
        try:
            from moviepy.editor import AudioFileClip, concatenate_audioclips
        except ImportError:
            log_cb("❌ MoviePy is not installed. Run 'pip install moviepy' to use this fallback.")
            return False
            
        log_cb(f"🔄 Stitching {len(video_paths)} audio files using MoviePy...")
        clips = []
        try:
            for path in video_paths:
                log_cb(f"Loading audio clip: {os.path.basename(path)}")
                clips.append(AudioFileClip(path))
                
            log_cb("🔄 Concatenating audio clips...")
            final_clip = concatenate_audioclips(clips)
            
            log_cb(f"💾 Rendering final output to: {output_filename}")
            final_clip.write_audiofile(
                output_filename,
                bitrate="192k",
                logger=None
            )
            log_cb(f"🎉 Success! Merged audio saved as: {output_filename}")
            return True
        except Exception as e:
            log_cb(f"❌ MoviePy audio concatenation failed: {e}")
            return False
        finally:
            log_cb("🧹 Releasing audio clip files...")
            for clip in clips:
                try:
                    clip.close()
                except Exception:
                    pass
    else:
        try:
            from moviepy.editor import VideoFileClip, concatenate_videoclips
        except ImportError:
            log_cb("❌ MoviePy is not installed. Run 'pip install moviepy' to use this fallback.")
            return False
            
        log_cb(f"🔄 Stitching {len(video_paths)} videos using MoviePy (Re-encoding)...")
        clips = []
        try:
            for path in video_paths:
                log_cb(f"Loading clip: {os.path.basename(path)}")
                clips.append(VideoFileClip(path))
                
            log_cb("🔄 Concatenating clips...")
            final_clip = concatenate_videoclips(clips, method="compose")
            
            log_cb(f"💾 Rendering final output to: {output_filename}")
            final_clip.write_videofile(
                output_filename, 
                codec="libx264", 
                audio_codec="aac",
                temp_audiofile="temp-audio.m4a",
                remove_temp=True,
                logger=None  # Suppress internal moviepy log stdout spam
            )
            log_cb(f"🎉 Success! Merged video saved as: {output_filename}")
            return True
        except Exception as e:
            log_cb(f"❌ MoviePy concatenation failed: {e}")
            return False
        finally:
            log_cb("🧹 Releasing clip files...")
            for clip in clips:
                try:
                    clip.close()
                except Exception:
                    pass

if GUI_AVAILABLE:
    class PlaylistStitcherGUI(ctk.CTk):
        def __init__(self):
            super().__init__()
            
            # Application Setup
            self.title("🎬 Playlist Stitcher & Merger")
            self.geometry("750x420")
            self.minsize(650, 380)
            ctk.set_appearance_mode("Dark")
            ctk.set_default_color_theme("blue")
            
            # Cancellation flag — set by the Cancel button, read in the background thread
            self._cancel_event = threading.Event()
            
            self.center_window()
            self.create_widgets()
            
        def center_window(self):
            self.update_idletasks()
            width = self.winfo_width()
            height = self.winfo_height()
            x = (self.winfo_screenwidth() // 2) - (width // 2)
            y = (self.winfo_screenheight() // 2) - (height // 2)
            self.geometry(f"+{x}+{y}")
            
        def create_widgets(self):
            # Title Banner
            self.title_frame = ctk.CTkFrame(self, fg_color="transparent")
            self.title_frame.pack(fill="x", padx=30, pady=(20, 10))
            
            self.title_label = ctk.CTkLabel(
                self.title_frame, 
                text="🎬 PLAYLIST STITCHER", 
                font=ctk.CTkFont(family="Segoe UI", size=24, weight="bold")
            )
            self.title_label.pack(anchor="w")
            
            self.subtitle_label = ctk.CTkLabel(
                self.title_frame, 
                text="Download and merge playlist videos into a single, seamless file", 
                font=ctk.CTkFont(family="Segoe UI", size=12),
                text_color="gray"
            )
            self.subtitle_label.pack(anchor="w")

            self.separator = ctk.CTkFrame(self, height=2, fg_color="gray30")
            self.separator.pack(fill="x", padx=30, pady=5)

            # Inputs Frame
            self.inputs_frame = ctk.CTkFrame(self)
            self.inputs_frame.pack(fill="x", padx=30, pady=10)
            
            # Format Selector Row
            self.format_label = ctk.CTkLabel(self.inputs_frame, text="Format:", font=ctk.CTkFont(weight="bold"))
            self.format_label.grid(row=0, column=0, padx=15, pady=(15, 5), sticky="w")
            
            self.format_seg = ctk.CTkSegmentedButton(
                self.inputs_frame,
                values=["MP4 (Video)", "MP3 (Audio)"],
                command=self.on_format_change
            )
            self.format_seg.set("MP4 (Video)")
            self.format_seg.grid(row=0, column=1, columnspan=2, padx=(0, 15), pady=(15, 5), sticky="w")

            # URL Row
            self.url_label = ctk.CTkLabel(self.inputs_frame, text="Playlist URL:", font=ctk.CTkFont(weight="bold"))
            self.url_label.grid(row=1, column=0, padx=15, pady=(5, 5), sticky="w")
            
            self.url_entry = ctk.CTkEntry(
                self.inputs_frame, 
                placeholder_text="https://www.youtube.com/playlist?list=...",
                height=30
            )
            self.url_entry.grid(row=1, column=1, columnspan=2, padx=(0, 15), pady=(5, 5), sticky="ew")
            
            # Save Path Row
            self.save_label = ctk.CTkLabel(self.inputs_frame, text="Save Location:", font=ctk.CTkFont(weight="bold"))
            self.save_label.grid(row=2, column=0, padx=15, pady=(5, 15), sticky="w")
            
            self.save_entry = ctk.CTkEntry(
                self.inputs_frame, 
                placeholder_text="Choose destination file...",
                height=30
            )
            self.save_entry.grid(row=2, column=1, padx=(0, 10), pady=(5, 15), sticky="ew")
            
            # Pre-fill default path (prefer standard Downloads directory on the laptop)
            user_downloads = os.path.join(os.path.expanduser("~"), "Downloads")
            if os.path.exists(user_downloads):
                default_output = os.path.join(user_downloads, "merged_playlist.mp4")
            else:
                default_output = os.path.join(os.getcwd(), "merged_playlist.mp4")
            self.save_entry.insert(0, default_output)
            
            self.browse_button = ctk.CTkButton(
                self.inputs_frame, 
                text="Browse...", 
                width=80, 
                height=30,
                command=self.browse_output_file
            )
            self.browse_button.grid(row=2, column=2, padx=(0, 15), pady=(5, 15), sticky="e")
            
            self.inputs_frame.grid_columnconfigure(1, weight=1)

            # Options Frame
            self.options_frame = ctk.CTkFrame(self, fg_color="transparent")
            self.options_frame.pack(fill="x", padx=30, pady=5)
            
            self.moviepy_switch = ctk.CTkSwitch(
                self.options_frame, 
                text="Force MoviePy Re-encoding (use only if files have different formats or codecs)",
                font=ctk.CTkFont(size=11)
            )
            self.moviepy_switch.pack(anchor="w", padx=15)

            # Action Frame
            self.action_frame = ctk.CTkFrame(self, fg_color="transparent")
            self.action_frame.pack(fill="x", padx=30, pady=(10, 30))
            
            self.start_button = ctk.CTkButton(
                self.action_frame, 
                text="Download & Merge Playlist", 
                font=ctk.CTkFont(size=14, weight="bold"),
                height=40,
                command=self.start_process
            )
            self.start_button.pack(fill="x", pady=5)
            
            # Cancel Button — hidden by default, shown only while running
            self.cancel_button = ctk.CTkButton(
                self.action_frame,
                text="⛔ Cancel Download",
                font=ctk.CTkFont(size=13, weight="bold"),
                height=36,
                fg_color="#c0392b",
                hover_color="#e74c3c",
                command=self.cancel_process
            )
            # Don't pack yet; shown dynamically when a run starts
            
            # Secondary Action: Open Folder
            self.open_folder_button = ctk.CTkButton(
                self.action_frame, 
                text="Open Output Folder", 
                font=ctk.CTkFont(size=12),
                height=30,
                fg_color="gray30",
                hover_color="gray40",
                state="disabled",
                command=self.open_output_folder
            )
            self.open_folder_button.pack(fill="x", pady=5)
            
            self.progress_bar = ctk.CTkProgressBar(self.action_frame)
            self.progress_bar.pack(fill="x", pady=5)
            self.progress_bar.set(0.0)
            
            self.status_label = ctk.CTkLabel(
                self.action_frame, 
                text="Status: Ready", 
                font=ctk.CTkFont(size=12, slant="italic")
            )
            self.status_label.pack(anchor="w", pady=2)

        def on_format_change(self, value):
            curr = self.save_entry.get().strip()
            if not curr:
                return
            if value.startswith("MP3"):
                if curr.lower().endswith(".mp4"):
                    self.save_entry.delete(0, "end")
                    self.save_entry.insert(0, curr[:-4] + ".mp3")
            else:
                if curr.lower().endswith(".mp3"):
                    self.save_entry.delete(0, "end")
                    self.save_entry.insert(0, curr[:-4] + ".mp4")

        def browse_output_file(self):
            is_mp3 = self.format_seg.get().startswith("MP3")
            ext = ".mp3" if is_mp3 else ".mp4"
            types = [("MP3 Audio", "*.mp3"), ("All Files", "*.*")] if is_mp3 else [("MP4 Video", "*.mp4"), ("All Files", "*.*")]
            title = "Save Merged Audio" if is_mp3 else "Save Merged Video"

            filename = filedialog.asksaveasfilename(
                defaultextension=ext,
                filetypes=types,
                title=title
            )
            if filename:
                self.save_entry.delete(0, "end")
                self.save_entry.insert(0, filename)

        def log_message(self, msg):
            """Logs to stdout (hidden in packaged .exe)."""
            print(msg)

        def update_progress(self, val):
            """Sets progress bar value (0.0 to 1.0) safely from background thread."""
            self.after(0, lambda: self.progress_bar.set(val))

        def update_status(self, text):
            """Updates status label text safely from background thread."""
            self.after(0, lambda: self.status_label.configure(text=f"Status: {text}"))

        def reset_ui(self, status="Ready"):
            """Resets UI components back to default interactive state."""
            self.format_seg.configure(state="normal")
            self.url_entry.configure(state="normal")
            self.save_entry.configure(state="normal")
            self.browse_button.configure(state="normal")
            self.moviepy_switch.configure(state="normal")
            self.start_button.configure(state="normal", text="Download & Merge Playlist")
            # Hide the cancel button again
            self.cancel_button.pack_forget()
            self.update_status(status)

        def cancel_process(self):
            """Signal the background thread to stop as soon as possible."""
            self._cancel_event.set()
            self.cancel_button.configure(state="disabled", text="Cancelling…")
            self.update_status("Cancelling — please wait...")

        def open_output_folder(self):
            """Opens the directory containing the output file in native Explorer."""
            output_path = self.save_entry.get().strip()
            if output_path:
                folder = os.path.dirname(os.path.abspath(output_path))
                if os.path.exists(folder):
                    if sys.platform == 'win32':
                        os.startfile(folder)
                    elif sys.platform == 'darwin':
                        subprocess.run(['open', folder])
                    else:
                        subprocess.run(['xdg-open', folder])

        def start_process(self):
            url = self.url_entry.get().strip()
            output = self.save_entry.get().strip()
            url = normalize_playlist_url(url)
            format_type = "mp3" if self.format_seg.get().startswith("MP3") else "mp4"
            
            if not url:
                messagebox.showerror("Error", "Please enter a valid playlist URL.")
                return
                
            if not output:
                messagebox.showerror("Error", "Please specify a save destination file.")
                return
                
            # Disable controls to prevent duplicate run
            self.format_seg.configure(state="disabled")
            self.url_entry.configure(state="disabled")
            self.save_entry.configure(state="disabled")
            self.browse_button.configure(state="disabled")
            self.moviepy_switch.configure(state="disabled")
            self.start_button.configure(state="disabled", text="Downloading...")
            self.open_folder_button.configure(state="disabled")
            
            # Reset cancellation flag and show Cancel button
            self._cancel_event.clear()
            self.cancel_button.configure(state="normal", text="⛔ Cancel Download")
            self.cancel_button.pack(fill="x", pady=5, before=self.open_folder_button)
            
            self.progress_bar.set(0.0)
            self.update_status("Starting background process...")
            
            # Run background thread
            thread = threading.Thread(
                target=self.run_background_logic,
                args=(url, output, self.moviepy_switch.get() == 1, format_type),
                daemon=True
            )
            thread.start()

        def run_background_logic(self, url, output, use_moviepy, format_type="mp4"):
            import time
            import re
            
            # Generate a unique temp directory in the local system Temp folder to bypass OneDrive lock/sync
            import tempfile
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            temp_dir = os.path.join(tempfile.gettempdir(), f"playlist_stitcher_{timestamp}")
            if not os.path.exists(temp_dir):
                os.makedirs(temp_dir)
                
            ffmpeg_path = get_ffmpeg_path()
            if not ffmpeg_path:
                self.log_message("⚠️ FFmpeg was not detected on your system PATH or via imageio-ffmpeg.")
                self.log_message("Merging audio/video formats requires FFmpeg. Installing 'imageio-ffmpeg' is highly recommended.")
                
            try:
                self.update_status("Fetching playlist information...")
                target_ext = f".{format_type.lower()}"
                playlist_title = f"merged_playlist{target_ext}"
                try:
                    # Quick extraction of playlist metadata
                    ydl_opts_info = get_yt_dlp_base_opts(ffmpeg_path)
                    ydl_opts_info.update({
                        'extract_flat': True,
                        'quiet': True,
                        'skip_download': True,
                        'no_warnings': True,
                    })
                        
                    with YoutubeDL(ydl_opts_info) as ydl:
                        info = ydl.extract_info(url, download=False)
                        playlist_title = info.get('title', f"merged_playlist{target_ext}")
                except Exception as e:
                    self.log_message(f"⚠️ Could not fetch playlist title: {e}")
                
                # Sanitize filename (replace prohibited characters with underscores)
                clean_title = re.sub(r'[\\/*?:"<>|]', '_', playlist_title)
                clean_title = re.sub(r'_+', '_', clean_title).strip('_')
                if clean_title.lower().endswith(('.mp4', '.mp3')):
                    clean_title = clean_title.rsplit('.', 1)[0]
                
                # If output ends with default name, update it dynamically to matching title
                if output.lower().endswith(("merged_playlist.mp4", "merged_playlist.mp3")):
                    dir_name = os.path.dirname(os.path.abspath(output))
                    output = os.path.join(dir_name, f"{clean_title}{target_ext}")
                    # Update GUI entry text
                    self.after(0, lambda out_val=output: self.save_entry.delete(0, "end"))
                    self.after(0, lambda out_val=output: self.save_entry.insert(0, out_val))
                
                self.log_message(f"📂 Output will be saved to: {output}")
                self.update_status(f"Downloading playlist ({'MP3 Audio' if format_type == 'mp3' else 'MP4 Video'})...")
                
                # Setup custom progress callback for yt-dlp
                def progress_cb(d):
                    # Check for cancellation on every progress tick — raising here
                    # causes yt-dlp to abort the current download immediately.
                    if self._cancel_event.is_set():
                        raise Exception("Download cancelled by user.")
                    
                    if d['status'] == 'downloading':
                        total = d.get('total_bytes') or d.get('total_bytes_estimate')
                        downloaded = d.get('downloaded_bytes', 0)
                        
                        pct = downloaded / total if total else 0.0
                        
                        info = d.get('info_dict', {})
                        idx = info.get('playlist_index')
                        n_entries = info.get('n_entries')
                        
                        filename = os.path.basename(d.get('filename', ''))
                        
                        if idx and n_entries:
                            # True overall calculation across the entire playlist
                            overall_pct = (idx - 1) / n_entries + (pct / n_entries)
                            # Clamp between 0.0 and 0.9 (reserve 0.9 - 1.0 for stitching phase)
                            overall_pct = min(overall_pct * 0.9, 0.9)
                            
                            self.update_progress(overall_pct)
                            self.update_status(f"Downloading item {idx} of {n_entries}: {filename[:30]}... ({pct*100:.1f}%)")
                        else:
                            self.update_progress(pct * 0.9)
                            self.update_status(f"Downloading: {filename[:40]}... ({pct*100:.1f}%)")
                            
                    elif d['status'] == 'finished':
                        self.log_message(f"Finished downloading segment: {os.path.basename(d.get('filename', ''))}")
                
                # 1. Download
                downloaded_files = download_playlist(
                    url, 
                    temp_dir, 
                    format_type=format_type,
                    ffmpeg_path=ffmpeg_path, 
                    log_cb=self.log_message, 
                    progress_cb=progress_cb
                )
                
                # Check if cancelled after download returns
                if self._cancel_event.is_set():
                    self.log_message("🛑 Download cancelled by user.")
                    self.update_progress(0.0)
                    self.after(0, lambda: messagebox.showinfo("Cancelled", "Download was cancelled. No file was saved."))
                    self.after(0, lambda: self.reset_ui("Cancelled"))
                    return
                
                if not downloaded_files:
                    self.log_message("❌ No files were successfully downloaded.")
                    self.after(0, lambda: messagebox.showerror("Error", "No media files could be downloaded. If you pasted a YouTube watch link, use the playlist link with /playlist?list=... or make sure the playlist is public."))
                    self.after(0, lambda: self.reset_ui("Ready"))
                    return
                    
                self.log_message(f"🎬 Successfully downloaded {len(downloaded_files)} segments.")
                self.update_status("Stitching files together...")
                self.update_progress(0.9)
                
                # 2. Concat
                success = False
                if use_moviepy:
                    success = concatenate_videos_moviepy(downloaded_files, output, format_type=format_type, log_cb=self.log_message)
                else:
                    if ffmpeg_path:
                        success = concatenate_videos_ffmpeg(downloaded_files, output, ffmpeg_path, format_type=format_type, log_cb=self.log_message)
                    else:
                        self.log_message("⚠️ FFmpeg is missing. Attempting fallback to MoviePy...")
                        success = concatenate_videos_moviepy(downloaded_files, output, format_type=format_type, log_cb=self.log_message)
                        
                # 3. Handle result
                if success:
                    self.update_progress(1.0)
                    self.update_status("Done! 🎉")
                    self.log_message(f"🎉 Success! Merged file saved at:\n{output}")
                    self.after(0, lambda: self.open_folder_button.configure(state="normal"))
                    self.after(0, lambda: messagebox.showinfo("Success", f"Playlist successfully merged and saved to:\n{output}"))
                else:
                    self.update_status("Failed ❌")
                    self.after(0, lambda: messagebox.showerror("Error", "Stitching process failed. Check the logs for details."))
                    
            except Exception as e:
                if self._cancel_event.is_set():
                    # Swallow the exception that yt-dlp surfaces from the cancelled progress hook
                    self.log_message("🛑 Download cancelled by user.")
                    self.update_progress(0.0)
                    self.after(0, lambda: messagebox.showinfo("Cancelled", "Download was cancelled. No file was saved."))
                else:
                    self.log_message(f"❌ Unexpected Error: {e}")
                    self.update_status("Error ❌")
                    self.after(0, lambda: messagebox.showerror("Unexpected Error", f"An error occurred:\n{e}"))
            finally:
                # 4. Clean up temporary files
                self.log_message("🧹 Cleaning up temporary download files...")
                if os.path.exists(temp_dir):
                    try:
                        shutil.rmtree(temp_dir)
                        self.log_message("✨ Temporary directory cleaned up.")
                    except Exception as e:
                        self.log_message(f"⚠️ Could not completely delete temporary directory '{temp_dir}': {e}")
                        
                if self._cancel_event.is_set():
                    final_status = "Cancelled"
                elif success:
                    final_status = "Done!"
                else:
                    final_status = "Failed"
                self.after(0, lambda s=final_status: self.reset_ui(s))

def main():
    parser = argparse.ArgumentParser(
        description="Download and stitch all videos/audios from a playlist into a single file."
    )
    parser.add_argument(
        "playlist_url", 
        nargs="?", 
        help="The URL of the playlist to download."
    )
    parser.add_argument(
        "output", 
        nargs="?", 
        default=None, 
        help="Output filename for the merged file. Defaults to 'merged_playlist.mp4' or 'merged_playlist.mp3'."
    )
    parser.add_argument(
        "--format", "-f",
        choices=["mp4", "mp3"],
        default="mp4",
        help="Output format: 'mp4' (video) or 'mp3' (audio). Defaults to 'mp4'."
    )
    parser.add_argument(
        "--use-moviepy", 
        action="store_true", 
        help="Force using MoviePy for concatenation instead of FFmpeg copy."
    )
    parser.add_argument(
        "--cli",
        action="store_true",
        help="Force running in command-line mode even if GUI packages are installed."
    )
    
    args = parser.parse_args()
    
    # Deciding whether to run GUI or CLI
    # We run CLI if explicit argument is passed, if there's a playlist URL in args, or if GUI is unavailable.
    run_cli = args.cli or (args.playlist_url is not None) or not GUI_AVAILABLE
    
    if run_cli:
        # CLI Mode
        playlist_url = args.playlist_url
        if not playlist_url:
            playlist_url = input("🔗 Enter the playlist URL: ").strip()
            if not playlist_url:
                print("❌ Error: No playlist URL provided. Exiting.")
                sys.exit(1)

        playlist_url = normalize_playlist_url(playlist_url)
        format_type = args.format.lower()
        target_ext = f".{format_type}"
                
        output_filename = args.output
        if not output_filename:
            output_filename = f"merged_playlist{target_ext}"
        elif not output_filename.lower().endswith(target_ext):
            output_filename += target_ext
            
        ffmpeg_path = get_ffmpeg_path()
        if not ffmpeg_path:
            print("\n⚠️ FFmpeg was not detected on system PATH or via imageio-ffmpeg.")
            print("Please run: pip install imageio-ffmpeg")
            sys.exit(1)

        # Generate a unique temp directory in the local system Temp folder to bypass OneDrive lock/sync
        import time
        import re
        import tempfile
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        temp_dir = os.path.join(tempfile.gettempdir(), f"playlist_stitcher_{timestamp}")
        if not os.path.exists(temp_dir):
            os.makedirs(temp_dir)
            
        # Try to resolve playlist title if output is the default filename
        if output_filename.lower().endswith(("merged_playlist.mp4", "merged_playlist.mp3")):
            try:
                print("🔍 Fetching playlist metadata...")
                ydl_opts_info = get_yt_dlp_base_opts(ffmpeg_path)
                ydl_opts_info.update({'extract_flat': True, 'quiet': True, 'skip_download': True, 'no_warnings': True})
                with YoutubeDL(ydl_opts_info) as ydl:
                    info = ydl.extract_info(playlist_url, download=False)
                    title = info.get('title', f"merged_playlist{target_ext}")
                    clean_title = re.sub(r'[\\/*?:"<>|]', '_', title)
                    clean_title = re.sub(r'_+', '_', clean_title).strip('_')
                    if clean_title.lower().endswith(('.mp4', '.mp3')):
                        clean_title = clean_title.rsplit('.', 1)[0]
                    dir_name = os.path.dirname(os.path.abspath(output_filename))
                    output_filename = os.path.join(dir_name, f"{clean_title}{target_ext}")
            except Exception as e:
                print(f"⚠️ Could not resolve playlist title: {e}")
                
        print(f"📂 Output will be saved to: {output_filename} ({'MP3 Audio' if format_type == 'mp3' else 'MP4 Video'})")
        try:
            downloaded_files = download_playlist(playlist_url, temp_dir, format_type=format_type, ffmpeg_path=ffmpeg_path, log_cb=print)
            if not downloaded_files:
                print("❌ No media files downloaded. If this was a YouTube watch URL, try the playlist URL instead.")
                return
                
            success = False
            if args.use_moviepy:
                success = concatenate_videos_moviepy(downloaded_files, output_filename, format_type=format_type, log_cb=print)
            else:
                success = concatenate_videos_ffmpeg(downloaded_files, output_filename, ffmpeg_path, format_type=format_type, log_cb=print)
                
            if not success:
                print("❌ Failed to merge the media files.")
        finally:
            print("🧹 Cleaning up temporary files...")
            if os.path.exists(temp_dir):
                try:
                    shutil.rmtree(temp_dir)
                    print("✨ Cleanup complete!")
                except Exception as e:
                    print(f"⚠️ Could not delete temp folder automatically: {e}")
    else:
        # Start the GUI
        app = PlaylistStitcherGUI()
        app.mainloop()

if __name__ == "__main__":
    main()
