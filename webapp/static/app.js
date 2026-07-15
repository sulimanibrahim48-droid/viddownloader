// PWA Service Worker Registration
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js')
      .then(reg => console.log('Service Worker registered with scope:', reg.scope))
      .catch(err => console.error('Service Worker registration failed:', err));
  });
}

// Global Variables
let eventSource = null;
let currentTaskId = null;
let deferredPrompt = null;

// DOM Elements
const formStage = document.getElementById('form-stage');
const progressStage = document.getElementById('progress-stage');
const successStage = document.getElementById('success-stage');
const errorStage = document.getElementById('error-stage');

const stitchForm = document.getElementById('stitch-form');
const playlistUrlInput = document.getElementById('playlist-url');
const outputNameInput = document.getElementById('output-name');
const maxVideosInput = document.getElementById('max-videos');
const mergeModeSelect = document.getElementById('merge-mode');
const urlError = document.getElementById('url-error');

const progressBarFill = document.getElementById('progress-bar-fill');
const progressPercent = document.getElementById('progress-percent');
const statusTitle = document.getElementById('status-title');
const consoleLog = document.getElementById('console-log');
const btnToggleConsole = document.getElementById('btn-toggle-console');

const resultFilename = document.getElementById('result-filename');
const resultSize = document.getElementById('result-size');
const btnDownload = document.getElementById('btn-download');

const errorMessageText = document.getElementById('error-message-text');
const errorConsoleLog = document.getElementById('error-console-log');

const btnResetSuccess = document.getElementById('btn-reset-success');
const btnResetError = document.getElementById('btn-reset-error');

const pwaInstallBanner = document.getElementById('pwa-install-banner');
const btnPwaInstall = document.getElementById('btn-pwa-install');

// Setup UI State Management
function showStage(stage) {
  // Hide all stages
  [formStage, progressStage, successStage, errorStage].forEach(el => {
    el.classList.remove('stage-active');
  });
  // Show target stage
  stage.classList.add('stage-active');
}

// Console Toggle functionality
if (btnToggleConsole) {
  btnToggleConsole.addEventListener('click', () => {
    const isCollapsed = consoleLog.classList.toggle('collapsed');
    btnToggleConsole.textContent = isCollapsed ? 'Expand' : 'Collapse';
  });
}

// Format log strings for styling
function appendLog(message, type = 'info') {
  const line = document.createElement('span');
  
  // Format check
  let logClass = '';
  if (message.includes('❌') || message.toLowerCase().includes('failed') || type === 'error') {
    logClass = 'log-error';
  } else if (message.includes('🎉') || message.includes('Success!') || type === 'success') {
    logClass = 'log-success';
  } else if (message.includes('⚠️') || type === 'warn') {
    logClass = 'log-warn';
  }
  
  if (logClass) {
    line.className = logClass;
  }
  
  line.textContent = message + '\n';
  consoleLog.appendChild(line);
  consoleLog.scrollTop = consoleLog.scrollHeight;
}

// SSE Connection Manager
function connectToSSE(taskId) {
  if (eventSource) {
    eventSource.close();
  }

  consoleLog.textContent = ''; // Reset console
  progressBarFill.style.width = '0%';
  progressPercent.textContent = '0%';
  statusTitle.textContent = 'Connecting to server...';

  eventSource = new EventSource(`/api/stream/${taskId}`);

  eventSource.addEventListener('log', (event) => {
    const data = JSON.parse(event.data);
    appendLog(data);
  });

  eventSource.addEventListener('progress', (event) => {
    const data = JSON.parse(event.data);
    const pct = data.percent;
    const status = data.status;

    progressBarFill.style.width = `${pct * 100}%`;
    progressPercent.textContent = `${Math.round(pct * 100)}%`;
    statusTitle.textContent = status;
  });

  eventSource.addEventListener('success', (event) => {
    const data = JSON.parse(event.data);
    eventSource.close();

    // Populate Success Stage
    resultFilename.textContent = data.filename;
    resultSize.textContent = `${data.size_mb.toFixed(1)} MB`;

    // Store for the Fetch+Blob download handler
    downloadApiUrl = data.download_url;
    downloadFilename = data.filename;

    // Reset button state in case a previous download was made
    if (btnDownloadLabel) btnDownloadLabel.textContent = 'Download Video';
    btnDownload.disabled = false;
    if (androidTip) androidTip.textContent = '';

    showStage(successStage);
  });

  eventSource.addEventListener('error', (event) => {
    const data = JSON.parse(event.data);
    eventSource.close();

    errorMessageText.textContent = data || 'Stitching process failed.';
    errorConsoleLog.textContent = consoleLog.textContent;
    showStage(errorStage);
  });

  eventSource.onerror = (err) => {
    console.error('SSE Error:', err);
    // Usually, EventSource reconnects automatically.
    // If the server goes down, we report after some time.
  };
}

// Form Submission
stitchForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  
  const url = playlistUrlInput.value.trim();
  const filename = outputNameInput.value.trim();
  const maxVideos = maxVideosInput ? maxVideosInput.value : '0';
  const mergeMode = mergeModeSelect ? mergeModeSelect.value : 'Auto';

  // Simple URL Validation
  if (!url) {
    formStage.querySelector('.form-group').classList.add('has-error');
    playlistUrlInput.focus();
    return;
  }
  formStage.querySelector('.form-group').classList.remove('has-error');

  const formData = new FormData();
  formData.append('url', url);
  formData.append('filename', filename);
  formData.append('max_videos', maxVideos);
  formData.append('merge_mode', mergeMode);

  // Transition to Progress Card
  showStage(progressStage);

  try {
    const response = await fetch('/api/stitch', {
      method: 'POST',
      body: formData
    });

    if (!response.ok) {
      const errorData = await response.json();
      throw new Error(errorData.detail || 'Failed to start stitching task.');
    }

    const data = await response.json();
    currentTaskId = data.task_id;
    connectToSSE(currentTaskId);

  } catch (error) {
    errorMessageText.textContent = error.message;
    errorConsoleLog.textContent = error.stack || 'Could not launch stitching job.';
    showStage(errorStage);
  }
});

// -------------------------------------------------------
// Download Handler — Android-compatible Fetch + Blob method
// -------------------------------------------------------
const btnDownloadLabel = document.getElementById('btn-download-label');
const androidTip = document.getElementById('android-tip');
let downloadApiUrl = null; // Set when success SSE event arrives
let downloadFilename = 'video.mp4';

btnDownload.addEventListener('click', async () => {
  if (!downloadApiUrl) return;

  // Show loading state
  btnDownload.disabled = true;
  btnDownloadLabel.textContent = 'Preparing download...';
  androidTip.textContent = '';

  try {
    // Fetch the file as a binary blob — this keeps us on the same page
    const response = await fetch(downloadApiUrl);
    if (!response.ok) throw new Error(`Server error: ${response.status}`);

    const blob = await response.blob();
    // Force video/mp4 MIME so Android recognises it
    const videoBlob = new Blob([blob], { type: 'video/mp4' });
    const objectUrl = URL.createObjectURL(videoBlob);

    // Create a temporary anchor and programmatically click it
    const a = document.createElement('a');
    a.href = objectUrl;
    a.download = downloadFilename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);

    // Clean up object URL after a delay
    setTimeout(() => URL.revokeObjectURL(objectUrl), 10000);

    btnDownloadLabel.textContent = 'Download Video';
    btnDownload.disabled = false;
    androidTip.textContent = 'Saved! Check your Downloads folder.';

  } catch (err) {
    console.error('Download failed:', err);
    btnDownloadLabel.textContent = 'Download Video';
    btnDownload.disabled = false;
    androidTip.textContent = 'Download failed. Try again.';
  }
});


// Reset Handlers
function resetToForm() {
  if (eventSource) {
    eventSource.close();
    eventSource = null;
  }
  playlistUrlInput.value = '';
  outputNameInput.value = 'merged_playlist.mp4';
  if (maxVideosInput) maxVideosInput.value = '0';
  if (mergeModeSelect) mergeModeSelect.value = 'Auto';
  downloadApiUrl = null;
  downloadFilename = 'video.mp4';
  if (androidTip) androidTip.textContent = '';
  currentTaskId = null;

  showStage(formStage);
}

btnResetSuccess.addEventListener('click', resetToForm);
btnResetError.addEventListener('click', resetToForm);

// PWA Install Event Handler
window.addEventListener('beforeinstallprompt', (e) => {
  // Prevent Chrome 67 and earlier from automatically showing the prompt
  e.preventDefault();
  // Stash the event so it can be triggered later.
  deferredPrompt = e;
  // Update UI to show the install banner
  pwaInstallBanner.classList.remove('hidden');
});

btnPwaInstall.addEventListener('click', async () => {
  if (!deferredPrompt) return;
  
  // Show the install prompt
  deferredPrompt.prompt();
  
  // Wait for the user to respond to the prompt
  const { outcome } = await deferredPrompt.userChoice;
  console.log(`User response to install prompt: ${outcome}`);
  
  // We no longer need the prompt
  deferredPrompt = null;
  // Hide the banner
  pwaInstallBanner.classList.add('hidden');
});

window.addEventListener('appinstalled', (evt) => {
  console.log('Playlist Stitcher app was installed successfully.');
  pwaInstallBanner.classList.add('hidden');
});
