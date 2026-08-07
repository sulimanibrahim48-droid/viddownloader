import React, { useState, useEffect, useRef } from 'react';
import {
  SafeAreaView,
  ScrollView,
  StyleSheet,
  View,
  Text,
  Alert,
  StatusBar,
  KeyboardAvoidingView,
  Platform,
} from 'react-native';
import { StatusBar as ExpoStatusBar } from 'expo-status-bar';

import { colors } from './src/theme/colors';
import { Header } from './src/components/Header';
import { InputCard } from './src/components/InputCard';
import { ProgressCard } from './src/components/ProgressCard';
import { LogsViewer } from './src/components/LogsViewer';
import { ResultCard } from './src/components/ResultCard';
import { ServerSettingsModal } from './src/components/ServerSettingsModal';
import { apiService } from './src/services/api';
import { ProcessStatus, StitchRequestParams, SuccessEventData } from './src/types';

export default function App() {
  const [status, setStatus] = useState<ProcessStatus>('idle');
  const [taskId, setTaskId] = useState<string | null>(null);
  const [progress, setProgress] = useState<number>(0);
  const [progressStatus, setProgressStatus] = useState<string>('');
  const [logs, setLogs] = useState<string[]>([]);
  const [result, setResult] = useState<SuccessEventData | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const [serverUrl, setServerUrl] = useState<string>('http://192.168.1.50:8000');
  const [serverConnected, setServerConnected] = useState<boolean>(false);
  const [settingsOpen, setSettingsOpen] = useState<boolean>(false);

  const [isSaving, setIsSaving] = useState<boolean>(false);
  const [saveProgress, setSaveProgress] = useState<number>(0);

  const unsubscribeRef = useRef<(() => void) | null>(null);

  // Check initial server connectivity
  useEffect(() => {
    apiService.setBaseUrl(serverUrl);
    apiService.testConnection().then((ok) => setServerConnected(ok));
  }, [serverUrl]);

  // Clean up SSE listener on unmount
  useEffect(() => {
    return () => {
      if (unsubscribeRef.current) {
        unsubscribeRef.current();
      }
    };
  }, []);

  const handleStartStitch = async (params: StitchRequestParams) => {
    setStatus('submitting');
    setProgress(0);
    setProgressStatus('Connecting to server...');
    setLogs([]);
    setResult(null);
    setErrorMessage(null);

    try {
      const response = await apiService.startStitch(params);
      const newTaskId = response.task_id;
      setTaskId(newTaskId);
      setStatus('processing');
      setProgressStatus('Initializing download thread...');

      // Subscribe to Server-Sent Events
      const unsubscribe = apiService.subscribeToProgress(newTaskId, {
        onLog: (log) => {
          setLogs((prev) => [...prev, log]);
        },
        onProgress: (data) => {
          setProgress(data.percent);
          setProgressStatus(data.status);
        },
        onSuccess: (data) => {
          setResult(data);
          setProgress(100);
          setProgressStatus('Complete!');
          setStatus('completed');
        },
        onError: (err) => {
          setErrorMessage(err);
          setStatus('error');
          Alert.alert('Processing Error', err);
        },
        onCancelled: () => {
          setStatus('cancelled');
          setProgressStatus('Cancelled by user.');
        },
      });

      unsubscribeRef.current = unsubscribe;
    } catch (err: any) {
      setStatus('error');
      const msg = err.message || 'Failed to submit playlist to server.';
      setErrorMessage(msg);
      Alert.alert(
        'Connection Failed',
        `${msg}\n\nPlease check your Server IP in Settings (⚙️) and make sure your phone and computer are on the same Wi-Fi network.`
      );
    }
  };

  const handleCancel = async () => {
    if (taskId) {
      await apiService.cancelTask(taskId);
    }
    if (unsubscribeRef.current) {
      unsubscribeRef.current();
    }
    setStatus('cancelled');
    setProgressStatus('Operation cancelled.');
  };

  const handleSaveToDevice = async () => {
    if (!result) return;
    setIsSaving(true);
    setSaveProgress(0);

    try {
      await apiService.downloadAndSaveFile(
        result.download_url,
        result.filename,
        (p) => setSaveProgress(p)
      );
    } catch (err: any) {
      Alert.alert('Save Failed', err.message || 'Could not save video to your device.');
    } finally {
      setIsSaving(false);
    }
  };

  const handleReset = () => {
    if (unsubscribeRef.current) {
      unsubscribeRef.current();
    }
    setStatus('idle');
    setTaskId(null);
    setProgress(0);
    setProgressStatus('');
    setLogs([]);
    setResult(null);
    setErrorMessage(null);
  };

  const handleSaveServerUrl = (newUrl: string) => {
    setServerUrl(newUrl);
    apiService.setBaseUrl(newUrl);
    apiService.testConnection().then((ok) => setServerConnected(ok));
  };

  return (
    <SafeAreaView style={styles.safeArea}>
      <ExpoStatusBar style="light" />
      <Header
        onOpenSettings={() => setSettingsOpen(true)}
        serverConnected={serverConnected}
      />

      <KeyboardAvoidingView
        style={styles.keyboardAvoid}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      >
        <ScrollView
          style={styles.scroll}
          contentContainerStyle={styles.scrollContent}
          keyboardShouldPersistTaps="handled"
        >
          {errorMessage && status === 'error' && (
            <View style={styles.errorBanner}>
              <Text style={styles.errorTitle}>⚠️ Error</Text>
              <Text style={styles.errorBody}>{errorMessage}</Text>
            </View>
          )}

          {status === 'idle' || status === 'submitting' ? (
            <InputCard
              onSubmit={handleStartStitch}
              isLoading={status === 'submitting'}
            />
          ) : null}

          {status === 'processing' ? (
            <ProgressCard
              percent={progress}
              status={progressStatus}
              onCancel={handleCancel}
            />
          ) : null}

          {status === 'completed' && result ? (
            <ResultCard
              result={result}
              isSaving={isSaving}
              saveProgress={saveProgress}
              onSaveToDevice={handleSaveToDevice}
              onReset={handleReset}
            />
          ) : null}

          {status === 'cancelled' ? (
            <View style={styles.cancelledCard}>
              <Text style={styles.cancelledTitle}>🛑 Download Cancelled</Text>
              <Text style={styles.cancelledText}>
                The stitching process was stopped.
              </Text>
              <InputCard onSubmit={handleStartStitch} isLoading={false} />
            </View>
          ) : null}

          {/* Real-time console logs stream */}
          <LogsViewer logs={logs} />
        </ScrollView>
      </KeyboardAvoidingView>

      <ServerSettingsModal
        visible={settingsOpen}
        currentUrl={serverUrl}
        onSave={handleSaveServerUrl}
        onClose={() => setSettingsOpen(false)}
        onTestConnection={(url) => {
          const tempService = new (apiService.constructor as any)(url);
          return tempService.testConnection();
        }}
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: colors.background,
    paddingTop: Platform.OS === 'android' ? StatusBar.currentHeight : 0,
  },
  keyboardAvoid: {
    flex: 1,
  },
  scroll: {
    flex: 1,
  },
  scrollContent: {
    padding: 16,
    paddingBottom: 40,
  },
  errorBanner: {
    backgroundColor: colors.danger + '20',
    borderWidth: 1,
    borderColor: colors.danger,
    borderRadius: 14,
    padding: 14,
    marginBottom: 16,
  },
  errorTitle: {
    color: colors.danger,
    fontWeight: '700',
    fontSize: 14,
    marginBottom: 4,
  },
  errorBody: {
    color: colors.textSecondary,
    fontSize: 13,
    lineHeight: 18,
  },
  cancelledCard: {
    gap: 16,
  },
  cancelledTitle: {
    color: colors.warning,
    fontSize: 16,
    fontWeight: '700',
    textAlign: 'center',
  },
  cancelledText: {
    color: colors.textSecondary,
    fontSize: 13,
    textAlign: 'center',
    marginBottom: 8,
  },
});
