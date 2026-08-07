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
const btnCancel = document.getElementById('btn-cancel');

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

function resetCancelButton() {
  if (btnCancel) {
    btnCancel.disabled = false;
    btnCancel.innerHTML = `
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
        <circle cx="12" cy="12" r="10"></circle>
        <line x1="15" y1="9" x2="9" y2="15"></line>
        <line x1="9" y1="9" x2="15" y2="15"></line>
      </svg>
      <span>Cancel Download</span>
    `;
  }
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
  resetCancelButton();

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

  eventSource.addEventListener('cancelled', (event) => {
    if (eventSource) {
      eventSource.close();
      eventSource = null;
    }
    currentTaskId = null;
    resetCancelButton();
    showStage(formStage);
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

// Cancel Button Handler
if (btnCancel) {
  btnCancel.addEventListener('click', async () => {
    if (!currentTaskId) {
      showStage(formStage);
      return;
    }

    btnCancel.disabled = true;
    btnCancel.innerHTML = `
      <svg class="loader-spinner" style="width: 14px; height: 14px; border-width: 2px;" viewBox="0 0 24 24"></svg>
      <span>Cancelling...</span>
    `;
    statusTitle.textContent = 'Cancelling download...';

    try {
      await fetch(`/api/cancel/${currentTaskId}`, { method: 'POST' });
    } catch (err) {
      console.error('Failed to send cancel request:', err);
      if (eventSource) {
        eventSource.close();
        eventSource = null;
      }
      currentTaskId = null;
      resetCancelButton();
      showStage(formStage);
    }
  });
}

// Format Radios
const formatRadios = document.querySelectorAll('input[name="format-choice"]');
formatRadios.forEach(radio => {
  radio.addEventListener('change', (e) => {
    const val = e.target.value;
    const currentName = outputNameInput.value.trim();
    if (val === 'mp3') {
      if (currentName.toLowerCase().endsWith('.mp4')) {
        outputNameInput.value = currentName.slice(0, -4) + '.mp3';
      }
    } else {
      if (currentName.toLowerCase().endsWith('.mp3')) {
        outputNameInput.value = currentName.slice(0, -4) + '.mp4';
      }
    }
  });
});

// Form Submission
stitchForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  
  const url = playlistUrlInput.value.trim();
  const filename = outputNameInput.value.trim();
  const maxVideos = maxVideosInput ? maxVideosInput.value : '0';
  const mergeMode = mergeModeSelect ? mergeModeSelect.value : 'Auto';
  const formatType = document.querySelector('input[name="format-choice"]:checked')?.value || 'mp4';

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
  formData.append('format_type', formatType);

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
    if (error.message === 'Failed to fetch' || error.name === 'TypeError') {
      errorMessageText.textContent = 'Cannot connect to the server. Please ensure the server is active on http://127.0.0.1:8000 and try again.';
    } else {
      errorMessageText.textContent = error.message;
    }
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

  const isAudio = downloadFilename.toLowerCase().endsWith('.mp3');
  const defaultLabel = isAudio ? 'Download Audio' : 'Download Video';

  // Show loading state
  btnDownload.disabled = true;
  btnDownloadLabel.textContent = 'Preparing download...';
  androidTip.textContent = '';

  try {
    // Fetch the file as a binary blob — this keeps us on the same page
    const response = await fetch(downloadApiUrl);
    if (!response.ok) throw new Error(`Server error: ${response.status}`);

    const blob = await response.blob();
    const mimeType = isAudio ? 'audio/mpeg' : 'video/mp4';
    const mediaBlob = new Blob([blob], { type: mimeType });
    const objectUrl = URL.createObjectURL(mediaBlob);

    // Create a temporary anchor and programmatically click it
    const a = document.createElement('a');
    a.href = objectUrl;
    a.download = downloadFilename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);

    // Clean up object URL after a delay
    setTimeout(() => URL.revokeObjectURL(objectUrl), 10000);

    btnDownloadLabel.textContent = defaultLabel;
    btnDownload.disabled = false;
    androidTip.textContent = 'Saved! Check your Downloads folder.';

  } catch (err) {
    console.error('Download failed:', err);
    btnDownloadLabel.textContent = defaultLabel;
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
  const isAudio = document.querySelector('input[name="format-choice"]:checked')?.value === 'mp3';
  outputNameInput.value = isAudio ? 'merged_playlist.mp3' : 'merged_playlist.mp4';
  if (maxVideosInput) maxVideosInput.value = '0';
  if (mergeModeSelect) mergeModeSelect.value = 'Auto';
  downloadApiUrl = null;
  downloadFilename = isAudio ? 'audio.mp3' : 'video.mp4';
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
