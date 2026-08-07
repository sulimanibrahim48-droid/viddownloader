import { StitchRequestParams, StitchResponse, ProgressEventData, SuccessEventData } from '../types';
import * as FileSystem from 'expo-file-system';
import * as Sharing from 'expo-sharing';

export class ApiService {
  private baseUrl: string;

  constructor(baseUrl: string = 'http://192.168.1.50:8000') {
    this.baseUrl = baseUrl.replace(/\/+$/, '');
  }

  setBaseUrl(url: string) {
    this.baseUrl = url.replace(/\/+$/, '');
  }

  getBaseUrl(): string {
    return this.baseUrl;
  }

  async testConnection(): Promise<boolean> {
    try {
      const response = await fetch(`${this.baseUrl}/docs`, { method: 'HEAD' });
      return response.status >= 200 && response.status < 400;
    } catch {
      return false;
    }
  }

  async startStitch(params: StitchRequestParams): Promise<StitchResponse> {
    const formData = new FormData();
    formData.append('url', params.url);
    if (params.filename) formData.append('filename', params.filename);
    if (params.maxVideos) formData.append('max_videos', params.maxVideos.toString());
    if (params.mergeMode) formData.append('merge_mode', params.mergeMode);
    if (params.formatType) formData.append('format_type', params.formatType);

    const response = await fetch(`${this.baseUrl}/api/stitch`, {
      method: 'POST',
      body: formData,
    });

    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(`Failed to start job (${response.status}): ${errorText}`);
    }

    return await response.json();
  }

  async cancelTask(taskId: string): Promise<void> {
    try {
      await fetch(`${this.baseUrl}/api/cancel/${taskId}`, {
        method: 'POST',
      });
    } catch (e) {
      console.warn('Error cancelling task:', e);
    }
  }

  subscribeToProgress(
    taskId: string,
    callbacks: {
      onLog?: (log: string) => void;
      onProgress?: (data: ProgressEventData) => void;
      onSuccess?: (data: SuccessEventData) => void;
      onError?: (error: string) => void;
      onCancelled?: (msg: string) => void;
    }
  ): () => void {
    let isCancelled = false;
    const controller = new AbortController();

    const streamUrl = `${this.baseUrl}/api/stream/${taskId}`;

    const startStreaming = async () => {
      try {
        const response = await fetch(streamUrl, {
          signal: controller.signal,
          headers: {
            'Accept': 'text/event-stream',
          },
        });

        if (!response.ok || !response.body) {
          throw new Error(`Stream connection failed: ${response.status}`);
        }

        // @ts-ignore
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (!isCancelled) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n');
          buffer = lines.pop() || '';

          let currentEvent = 'message';
          for (const line of lines) {
            const trimmed = line.trim();
            if (!trimmed) continue;

            if (trimmed.startsWith('event:')) {
              currentEvent = trimmed.replace('event:', '').trim();
            } else if (trimmed.startsWith('data:')) {
              const dataString = trimmed.replace('data:', '').trim();
              try {
                let parsedData: any = dataString;
                try {
                  parsedData = JSON.parse(dataString);
                } catch {
                  // Keep as string if not JSON
                }

                if (currentEvent === 'log' && callbacks.onLog) {
                  callbacks.onLog(typeof parsedData === 'string' ? parsedData : JSON.stringify(parsedData));
                } else if (currentEvent === 'progress' && callbacks.onProgress) {
                  callbacks.onProgress(parsedData as ProgressEventData);
                } else if (currentEvent === 'success' && callbacks.onSuccess) {
                  callbacks.onSuccess(parsedData as SuccessEventData);
                } else if (currentEvent === 'error' && callbacks.onError) {
                  callbacks.onError(typeof parsedData === 'string' ? parsedData : JSON.stringify(parsedData));
                } else if (currentEvent === 'cancelled' && callbacks.onCancelled) {
                  callbacks.onCancelled(typeof parsedData === 'string' ? parsedData : 'Cancelled');
                }
              } catch (parseErr) {
                console.warn('Error processing SSE data:', parseErr);
              }
            }
          }
        }
      } catch (err: any) {
        if (!isCancelled && err.name !== 'AbortError') {
          console.warn('SSE Stream error:', err);
          if (callbacks.onError) callbacks.onError(err.message || 'Stream error');
        }
      }
    };

    startStreaming();

    return () => {
      isCancelled = true;
      controller.abort();
    };
  }

  async downloadAndSaveFile(
    downloadUrl: string,
    filename: string,
    onProgress?: (fraction: number) => void
  ): Promise<string> {
    const fullUrl = downloadUrl.startsWith('http')
      ? downloadUrl
      : `${this.baseUrl}${downloadUrl.startsWith('/') ? '' : '/'}${downloadUrl}`;

    const localUri = `${FileSystem.documentDirectory}${filename}`;

    const downloadResumable = FileSystem.createDownloadResumable(
      fullUrl,
      localUri,
      {},
      (downloadProgress) => {
        const progress =
          downloadProgress.totalBytesWritten / downloadProgress.totalBytesExpectedToWrite;
        if (onProgress && !isNaN(progress)) {
          onProgress(progress);
        }
      }
    );

    const result = await downloadResumable.downloadAsync();
    if (!result?.uri) {
      throw new Error('Download failed to save to storage');
    }

    // Trigger native share/save sheet so user can save directly to Photos/Files
    if (await Sharing.isAvailableAsync()) {
      await Sharing.shareAsync(result.uri, {
        dialogTitle: `Save ${filename}`,
        mimeType: filename.endsWith('.mp3') ? 'audio/mpeg' : 'video/mp4',
        UTI: filename.endsWith('.mp3') ? 'public.mp3' : 'public.mpeg-4',
      });
    }

    return result.uri;
  }
}

export const apiService = new ApiService();
