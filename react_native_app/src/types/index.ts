export type MergeMode = 'Auto' | 'Fast FFmpeg Copy (Lossless)' | 'Re-encode (MoviePy Fallback)';
export type OutputFormat = 'mp4' | 'mp3';

export type ProcessStatus = 'idle' | 'submitting' | 'processing' | 'downloading' | 'completed' | 'error' | 'cancelled';

export interface StitchRequestParams {
  url: string;
  filename?: string;
  maxVideos?: number;
  mergeMode?: MergeMode;
  formatType?: OutputFormat;
}

export interface StitchResponse {
  task_id: string;
}

export interface ProgressEventData {
  percent: number;
  status: string;
}

export interface SuccessEventData {
  download_url: string;
  filename: string;
  size_mb: number;
}
