from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import streamlit as st
from yt_dlp import YoutubeDL

VIDEO_EXTENSIONS = {'.mp4', '.mkv', '.webm', '.mov', '.m4v', '.avi', '.flv'}


st.set_page_config(page_title='Playlist Stitcher Web App', page_icon='🎬', layout='centered')


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
    """Return the normalized URL and whether the source should be treated as a single video."""
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


def render_logs(logs: list[str], placeholder) -> None:
    if not logs:
        placeholder.code('Waiting for input...', language='text')
        return
    placeholder.code('\n'.join(logs[-200:]), language='text')


def append_log(logs: list[str], placeholder, message: str) -> None:
    logs.append(message)
    render_logs(logs, placeholder)


def download_playlist(
    playlist_url: str,
    temp_dir: Path,
    ffmpeg_path: str | None,
    max_videos: int,
    logs: list[str],
    log_placeholder,
    progress_placeholder,
    status_placeholder,
) -> list[Path]:
    normalized_url, is_single_video = get_source_kind(playlist_url)
    append_log(logs, log_placeholder, f'Using source URL: {normalized_url}')
    append_log(logs, log_placeholder, f'Source mode: {"single video" if is_single_video else "playlist"}')

    downloaded_paths: set[Path] = set()

    def internal_progress_hook(d):
        filename = d.get('filename')
        if filename:
            downloaded_paths.add(Path(filename).resolve())

        if d.get('status') == 'downloading':
            total = d.get('total_bytes') or d.get('total_bytes_estimate')
            downloaded = d.get('downloaded_bytes', 0)
            pct = (downloaded / total) if total else 0.0

            info = d.get('info_dict', {})
            idx = info.get('playlist_index')
            n_entries = info.get('n_entries')
            basename = os.path.basename(d.get('filename', ''))

            if idx and n_entries:
                overall_pct = (idx - 1) / n_entries + (pct / n_entries)
                overall_pct = min(max(overall_pct, 0.0), 0.85)
                progress_placeholder.progress(float(overall_pct))
                status_placeholder.info(
                    f'Downloading video {idx} of {n_entries}: {basename[:40]} ({pct * 100:.1f}%)'
                )
            else:
                progress_placeholder.progress(float(min(max(pct, 0.0), 0.85)))
                status_placeholder.info(f'Downloading: {basename[:60]} ({pct * 100:.1f}%)')

        elif d.get('status') == 'finished':
            append_log(logs, log_placeholder, f'Finished downloading: {os.path.basename(d.get("filename", ""))}')

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
            append_log(logs, log_placeholder, 'Some items failed or were skipped.')

    downloaded_files: list[Path] = []
    for path in temp_dir.rglob('*'):
        if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS:
            downloaded_files.append(path)

    for path in downloaded_paths:
        if path.exists() and path.suffix.lower() in VIDEO_EXTENSIONS:
            downloaded_files.append(path)

    unique_files = sorted({p.resolve() for p in downloaded_files})
    append_log(logs, log_placeholder, f'Downloaded {len(unique_files)} media files.')
    return unique_files


def concatenate_videos_ffmpeg(video_paths: list[Path], output_path: Path, ffmpeg_path: str, logs: list[str], log_placeholder) -> bool:
    append_log(logs, log_placeholder, f'Stitching {len(video_paths)} files with FFmpeg copy mode...')
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
            append_log(logs, log_placeholder, 'FFmpeg copy mode failed.')
            append_log(logs, log_placeholder, result.stderr[-4000:])
            return False

        append_log(logs, log_placeholder, f'Merged video saved to {output_path}')
        return True
    finally:
        if list_file_path.exists():
            try:
                list_file_path.unlink()
            except Exception:
                pass


def concatenate_videos_moviepy(video_paths: list[Path], output_path: Path, logs: list[str], log_placeholder) -> bool:
    try:
        from moviepy.editor import VideoFileClip, concatenate_videoclips
    except ImportError:
        append_log(logs, log_placeholder, 'MoviePy is not installed.')
        return False

    append_log(logs, log_placeholder, f'Stitching {len(video_paths)} files with MoviePy re-encode mode...')
    clips = []
    try:
        for path in video_paths:
            append_log(logs, log_placeholder, f'Loading {path.name}')
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
        append_log(logs, log_placeholder, f'Merged video saved to {output_path}')
        return True
    except Exception as exc:
        append_log(logs, log_placeholder, f'MoviePy failed: {exc}')
        return False
    finally:
        for clip in clips:
            try:
                clip.close()
            except Exception:
                pass


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


def main() -> None:
    st.title('Playlist Stitcher Web App')
    st.caption('Web version of the playlist downloader and merger')

    st.info('This web app runs on a server or your local machine. The final video is prepared on the server and then downloaded by your browser.')

    with st.form('playlist_form'):
        playlist_url = st.text_input(
            'Playlist URL',
            placeholder='https://www.youtube.com/watch?v=...&list=...',
        )
        output_name = st.text_input('Output filename', value='merged_playlist.mp4')
        max_videos = st.number_input('Max videos to process (0 = all)', min_value=0, value=1, step=1)
        merge_mode = st.selectbox('Merge mode', ['Auto', 'FFmpeg copy', 'MoviePy re-encode'])
        submitted = st.form_submit_button('Download and merge')

    if not submitted:
        st.write('Enter a YouTube playlist URL and submit the form to start.')
        return

    if not playlist_url.strip():
        st.error('Please enter a playlist URL.')
        return

    temp_dir = Path(tempfile.mkdtemp(prefix='playlist_stitcher_web_'))
    logs: list[str] = []
    progress_placeholder = st.empty()
    status_placeholder = st.empty()
    log_placeholder = st.empty()
    progress_placeholder.progress(0.0)
    status_placeholder.info('Starting...')
    render_logs(logs, log_placeholder)

    ffmpeg_path = get_ffmpeg_path()
    if not ffmpeg_path:
        append_log(logs, log_placeholder, 'FFmpeg was not found on PATH. imageio-ffmpeg will be used if available.')
    else:
        append_log(logs, log_placeholder, f'Using FFmpeg: {ffmpeg_path}')

    normalized_url = normalize_playlist_url(playlist_url)
    append_log(logs, log_placeholder, f'Normalized URL: {normalized_url}')

    if output_name.strip().lower().endswith('merged_playlist.mp4'):
        output_name = get_playlist_title(normalized_url, ffmpeg_path)

    output_path = temp_dir / sanitize_filename(output_name)
    status_placeholder.info('Fetching and downloading playlist...')

    try:
        downloaded_files = download_playlist(
            normalized_url,
            temp_dir,
            ffmpeg_path,
            int(max_videos),
            logs,
            log_placeholder,
            progress_placeholder,
            status_placeholder,
        )

        if not downloaded_files:
            st.error('No videos could be downloaded. Make sure the playlist is public and the link is valid.')
            return

        progress_placeholder.progress(0.9)
        status_placeholder.info('Stitching videos together...')

        merge_ok = False
        if merge_mode == 'MoviePy re-encode':
            merge_ok = concatenate_videos_moviepy(downloaded_files, output_path, logs, log_placeholder)
        elif merge_mode == 'FFmpeg copy':
            if not ffmpeg_path:
                st.warning('FFmpeg was not found, falling back to MoviePy if installed.')
                merge_ok = concatenate_videos_moviepy(downloaded_files, output_path, logs, log_placeholder)
            else:
                merge_ok = concatenate_videos_ffmpeg(downloaded_files, output_path, ffmpeg_path, logs, log_placeholder)
        else:
            if ffmpeg_path:
                merge_ok = concatenate_videos_ffmpeg(downloaded_files, output_path, ffmpeg_path, logs, log_placeholder)
            else:
                merge_ok = concatenate_videos_moviepy(downloaded_files, output_path, logs, log_placeholder)

        if not merge_ok or not output_path.exists():
            st.error('Stitching failed. Check the log output below.')
            return

        progress_placeholder.progress(1.0)
        status_placeholder.success('Done')

        file_bytes = output_path.read_bytes()
        st.success(f'Created {output_path.name} successfully.')
        st.download_button(
            'Download merged video',
            data=file_bytes,
            file_name=output_path.name,
            mime='video/mp4',
        )
        st.write(f'File size: {output_path.stat().st_size / (1024 * 1024):.1f} MB')
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == '__main__':
    main()
