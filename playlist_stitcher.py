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
import shutil
import argparse
import subprocess
import threading
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from yt_dlp import YoutubeDL

VIDEO_EXTENSIONS = {'.mp4', '.mkv', '.webm', '.mov', '.m4v', '.avi', '.flv'}

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

def normalize_playlist_url(url):
    """Convert YouTube watch URLs with a list id into canonical playlist URLs."""
    parsed = urlparse(url.strip())
    query = parse_qs(parsed.query)
    list_id = (query.get('list') or [None])[0]

    if not list_id:
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

def download_playlist(playlist_url, temp_dir, ffmpeg_path=None, log_cb=print, progress_cb=None):
    """
    Downloads all videos from the given playlist into the specified temp directory.
    Uses zero-padded playlist indices to preserve the correct chronological order.
    """
    playlist_url = normalize_playlist_url(playlist_url)
    log_cb(f"🚀 Initializing download for: {playlist_url}")

    downloaded_paths = set()
    
    # Set up the progress hook wrapper
    def internal_progress_hook(d):
        filename = d.get('filename')
        if filename:
            downloaded_paths.add(os.path.abspath(filename))

        if progress_cb:
            progress_cb(d)
            
    # Configure yt-dlp options
    ydl_opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]',
        'outtmpl': os.path.join(temp_dir, '%(playlist_index)04d_%(title)s.%(ext)s'),
        'logger': YDLLogger(log_cb),
        'progress_hooks': [internal_progress_hook],
        'ignoreerrors': True,  # Skip private/deleted videos instead of crashing
        'no_warnings': True,
    }
    
    # Pass FFmpeg location if it's not a standard global command
    if ffmpeg_path and ffmpeg_path != "ffmpeg":
        ydl_opts['ffmpeg_location'] = ffmpeg_path
        
    with YoutubeDL(ydl_opts) as ydl:
        error_code = ydl.download([playlist_url])
        if error_code != 0:
            log_cb("⚠️ Some videos in the playlist failed to download or were skipped.")

    # Gather and sort the downloaded media files.
    # yt-dlp may produce mp4, mkv, webm, or another supported container depending on the source.
    downloaded_files = []
    for root, _, files in os.walk(temp_dir):
        for file in files:
            ext = os.path.splitext(file)[1].lower()
            if ext in VIDEO_EXTENSIONS:
                downloaded_files.append(os.path.join(root, file))

    # Include files reported by yt-dlp even if they were not discovered by extension scan yet.
    for path in downloaded_paths:
        if os.path.splitext(path)[1].lower() in VIDEO_EXTENSIONS and os.path.exists(path):
            downloaded_files.append(path)

    # Sort numerically based on the zero-padded index filename prefix, then deduplicate.
    downloaded_files = sorted(set(downloaded_files))
    
    return downloaded_files

def concatenate_videos_ffmpeg(video_paths, output_filename, ffmpeg_path, log_cb=print):
    """
    Concatenates videos using the FFmpeg concat demuxer.
    This is extremely fast, lossless, and does not re-encode the video streams.
    """
    log_cb(f"🔄 Stitching {len(video_paths)} videos using FFmpeg (lossless copy)...")
    
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
            log_cb("❌ FFmpeg concatenation failed.")
            log_cb(f"Error Output:\n{result.stderr}")
            return False
            
        log_cb(f"🎉 Success! Merged video saved as: {output_filename}")
        return True
        
    finally:
        if os.path.exists(list_file_path):
            try:
                os.remove(list_file_path)
            except Exception as e:
                log_cb(f"⚠️ Could not remove temporary list file: {e}")

def concatenate_videos_moviepy(video_paths, output_filename, log_cb=print):
    """
    Fallback concatenation using MoviePy.
    Re-encodes clips to ensure resolution and codec mismatches are handled.
    """
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
            
            # URL Row
            self.url_label = ctk.CTkLabel(self.inputs_frame, text="Playlist URL:", font=ctk.CTkFont(weight="bold"))
            self.url_label.grid(row=0, column=0, padx=15, pady=(15, 5), sticky="w")
            
            self.url_entry = ctk.CTkEntry(
                self.inputs_frame, 
                placeholder_text="https://www.youtube.com/playlist?list=...",
                height=30
            )
            self.url_entry.grid(row=0, column=1, columnspan=2, padx=(0, 15), pady=(15, 5), sticky="ew")
            
            # Save Path Row
            self.save_label = ctk.CTkLabel(self.inputs_frame, text="Save Location:", font=ctk.CTkFont(weight="bold"))
            self.save_label.grid(row=1, column=0, padx=15, pady=(5, 15), sticky="w")
            
            self.save_entry = ctk.CTkEntry(
                self.inputs_frame, 
                placeholder_text="Choose destination file...",
                height=30
            )
            self.save_entry.grid(row=1, column=1, padx=(0, 10), pady=(5, 15), sticky="ew")
            
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
            self.browse_button.grid(row=1, column=2, padx=(0, 15), pady=(5, 15), sticky="e")
            
            self.inputs_frame.grid_columnconfigure(1, weight=1)

            # Options Frame
            self.options_frame = ctk.CTkFrame(self, fg_color="transparent")
            self.options_frame.pack(fill="x", padx=30, pady=5)
            
            self.moviepy_switch = ctk.CTkSwitch(
                self.options_frame, 
                text="Force MoviePy Re-encoding (use only if videos have different sizes or formats)",
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



        def browse_output_file(self):
            filename = filedialog.asksaveasfilename(
                defaultextension=".mp4",
                filetypes=[("MP4 Video", "*.mp4"), ("All Files", "*.*")],
                title="Save Merged Video"
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
            self.url_entry.configure(state="normal")
            self.save_entry.configure(state="normal")
            self.browse_button.configure(state="normal")
            self.moviepy_switch.configure(state="normal")
            self.start_button.configure(state="normal", text="Download & Merge Playlist")
            self.update_status(status)

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
            
            if not url:
                messagebox.showerror("Error", "Please enter a valid playlist URL.")
                return
                
            if not output:
                messagebox.showerror("Error", "Please specify a save destination file.")
                return
                
            # Disable controls to prevent duplicate run
            self.url_entry.configure(state="disabled")
            self.save_entry.configure(state="disabled")
            self.browse_button.configure(state="disabled")
            self.moviepy_switch.configure(state="disabled")
            self.start_button.configure(state="disabled", text="Stitching Playlist...")
            self.open_folder_button.configure(state="disabled")
            

            
            self.progress_bar.set(0.0)
            self.update_status("Starting background process...")
            
            # Run background thread
            thread = threading.Thread(
                target=self.run_background_logic,
                args=(url, output, self.moviepy_switch.get() == 1),
                daemon=True
            )
            thread.start()

        def run_background_logic(self, url, output, use_moviepy):
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
                self.log_message("Merging best video/audio formats requires FFmpeg. Installing 'imageio-ffmpeg' is highly recommended.")
                
            try:
                self.update_status("Fetching playlist information...")
                playlist_title = "merged_playlist"
                try:
                    # Quick extraction of playlist metadata
                    ydl_opts_info = {
                        'extract_flat': True,
                        'quiet': True,
                        'skip_download': True,
                        'no_warnings': True,
                    }
                    if ffmpeg_path and ffmpeg_path != "ffmpeg":
                        ydl_opts_info['ffmpeg_location'] = ffmpeg_path
                        
                    with YoutubeDL(ydl_opts_info) as ydl:
                        info = ydl.extract_info(url, download=False)
                        playlist_title = info.get('title', 'merged_playlist')
                except Exception as e:
                    self.log_message(f"⚠️ Could not fetch playlist title: {e}")
                
                # Sanitize filename (replace prohibited characters with underscores)
                clean_title = re.sub(r'[\\/*?:"<>|]', '_', playlist_title)
                clean_title = re.sub(r'_+', '_', clean_title).strip('_')
                
                # If output ends with default name, update it dynamically to matching title
                if output.lower().endswith("merged_playlist.mp4"):
                    dir_name = os.path.dirname(os.path.abspath(output))
                    output = os.path.join(dir_name, f"{clean_title}.mp4")
                    # Update GUI entry text
                    self.after(0, lambda out_val=output: self.save_entry.delete(0, "end"))
                    self.after(0, lambda out_val=output: self.save_entry.insert(0, out_val))
                
                self.log_message(f"📂 Output will be saved to: {output}")
                self.update_status("Downloading playlist...")
                
                # Setup custom progress callback for yt-dlp
                def progress_cb(d):
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
                            self.update_status(f"Downloading video {idx} of {n_entries}: {filename[:30]}... ({pct*100:.1f}%)")
                        else:
                            self.update_progress(pct * 0.9)
                            self.update_status(f"Downloading: {filename[:40]}... ({pct*100:.1f}%)")
                            
                    elif d['status'] == 'finished':
                        self.log_message(f"Finished downloading segment: {os.path.basename(d.get('filename', ''))}")
                
                # 1. Download
                downloaded_files = download_playlist(
                    url, 
                    temp_dir, 
                    ffmpeg_path, 
                    log_cb=self.log_message, 
                    progress_cb=progress_cb
                )
                
                if not downloaded_files:
                    self.log_message("❌ No files were successfully downloaded.")
                    self.after(0, lambda: messagebox.showerror("Error", "No videos could be downloaded. If you pasted a YouTube watch link, use the playlist link with /playlist?list=... or make sure the playlist is public."))
                    self.after(0, lambda: self.reset_ui("Ready"))
                    return
                    
                self.log_message(f"🎬 Successfully downloaded {len(downloaded_files)} segments.")
                self.update_status("Stitching videos together...")
                self.update_progress(0.9)
                
                # 2. Concat
                success = False
                if use_moviepy:
                    success = concatenate_videos_moviepy(downloaded_files, output, log_cb=self.log_message)
                else:
                    if ffmpeg_path:
                        success = concatenate_videos_ffmpeg(downloaded_files, output, ffmpeg_path, log_cb=self.log_message)
                    else:
                        self.log_message("⚠️ FFmpeg is missing. Attempting fallback to MoviePy...")
                        success = concatenate_videos_moviepy(downloaded_files, output, log_cb=self.log_message)
                        
                # 3. Handle result
                if success:
                    self.update_progress(1.0)
                    self.update_status("Done! 🎉")
                    self.log_message(f"🎉 Success! Merged video saved at:\n{output}")
                    self.after(0, lambda: self.open_folder_button.configure(state="normal"))
                    self.after(0, lambda: messagebox.showinfo("Success", f"Playlist successfully merged and saved to:\n{output}"))
                else:
                    self.update_status("Failed ❌")
                    self.after(0, lambda: messagebox.showerror("Error", "Stitching process failed. Check the logs for details."))
                    
            except Exception as e:
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
                        
                self.after(0, lambda: self.reset_ui("Done!" if success else "Failed"))

def main():
    parser = argparse.ArgumentParser(
        description="Download and stitch all videos from a playlist into a single video file."
    )
    parser.add_argument(
        "playlist_url", 
        nargs="?", 
        help="The URL of the playlist to download."
    )
    parser.add_argument(
        "output", 
        nargs="?", 
        default="merged_playlist.mp4", 
        help="Output filename for the merged video. Defaults to 'merged_playlist.mp4'."
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
                
        output_filename = args.output
        if not output_filename.lower().endswith('.mp4'):
            output_filename += '.mp4'
            
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
        if output_filename.lower().endswith("merged_playlist.mp4"):
            try:
                print("🔍 Fetching playlist metadata...")
                with YoutubeDL({'extract_flat': True, 'quiet': True, 'skip_download': True, 'no_warnings': True}) as ydl:
                    info = ydl.extract_info(playlist_url, download=False)
                    title = info.get('title', 'merged_playlist')
                    clean_title = re.sub(r'[\\/*?:"<>|]', '_', title)
                    clean_title = re.sub(r'_+', '_', clean_title).strip('_')
                    dir_name = os.path.dirname(os.path.abspath(output_filename))
                    output_filename = os.path.join(dir_name, f"{clean_title}.mp4")
            except Exception as e:
                print(f"⚠️ Could not resolve playlist title: {e}")
                
        print(f"📂 Output will be saved to: {output_filename}")
        try:
            downloaded_files = download_playlist(playlist_url, temp_dir, ffmpeg_path, log_cb=print)
            if not downloaded_files:
                print("❌ No videos downloaded. If this was a YouTube watch URL, try the playlist URL instead.")
                return
                
            success = False
            if args.use_moviepy:
                success = concatenate_videos_moviepy(downloaded_files, output_filename, log_cb=print)
            else:
                success = concatenate_videos_ffmpeg(downloaded_files, output_filename, ffmpeg_path, log_cb=print)
                
            if not success:
                print("❌ Failed to merge the video files.")
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
