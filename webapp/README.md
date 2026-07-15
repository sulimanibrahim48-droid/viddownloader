# Playlist Stitcher Web App

A separate web version of the playlist downloader and merger. It includes:
1. **Responsive PWA (Recommended for Mobile)**: Powered by FastAPI & SSE progress streams. Fully optimized for Android/iOS browser layouts and installation.
2. **Streamlit App**: The original Streamlit dashboard.

---

## 📱 Option A: Run Responsive PWA Server (FastAPI)

This mode starts a lightweight server that serves a beautiful, touch-friendly UI. You can install it on your mobile device's home screen.

### 1. Run the server locally
Make sure your computer and mobile phone are connected to the **same Wi-Fi network**.

```bash
cd webapp
pip install -r requirements.txt
python app.py
```
This runs the server on `http://0.0.0.0:8000`.

### 2. Connect from your mobile device
1. Find your computer's local IP address (e.g., `192.168.1.50`).
   - On Windows: Run `ipconfig` in CMD and look for `IPv4 Address`.
   - On Mac/Linux: Run `ifconfig` or `ip a` and check your interface IP.
2. Open your mobile phone's web browser (Safari on iOS, Chrome on Android).
3. Navigate to `http://<YOUR-LAPTOP-IP>:8000` (e.g., `http://192.168.1.50:8000`).

### 3. Install to Home Screen (PWA)
- **iOS (Safari)**: Tap the **Share** button at the bottom of Safari, scroll down, and select **Add to Home Screen**.
- **Android (Chrome)**: Tap the **three dots** in the top right corner and select **Add to Home screen** (or tap the "Install" banner at the bottom).

The application will now appear on your home screen as a standalone application, hiding browser bars and running in fullscreen!

---

## 💻 Option B: Run Streamlit App

To run the classic Streamlit web dashboard:

```bash
cd webapp
pip install -r requirements.txt
streamlit run streamlit_app.py
```

---

## What it does

- Accepts a YouTube playlist URL.
- Downloads the playlist using `yt-dlp` in a background thread.
- Merges the videos using lossless FFmpeg copy or MoviePy.
- Streams live progress and console logs to your phone's browser using Server-Sent Events (SSE).
- Serves the final file directly to your browser for download.
