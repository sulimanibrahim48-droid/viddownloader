import React, { useState } from 'react';
import {
  View,
  Text,
  TextInput,
  TouchableOpacity,
  StyleSheet,
  ActivityIndicator,
  Alert,
} from 'react-native';
import * as Clipboard from 'expo-clipboard';
import { colors } from '../theme/colors';
import { MergeMode, OutputFormat, StitchRequestParams } from '../types';

interface InputCardProps {
  onSubmit: (params: StitchRequestParams) => void;
  isLoading: boolean;
}

export const InputCard: React.FC<InputCardProps> = ({ onSubmit, isLoading }) => {
  const [url, setUrl] = useState('');
  const [filename, setFilename] = useState('');
  const [format, setFormat] = useState<OutputFormat>('mp4');
  const [maxVideos, setMaxVideos] = useState<string>('');
  const [mergeMode, setMergeMode] = useState<MergeMode>('Auto');
  const [showAdvanced, setShowAdvanced] = useState(false);

  const handlePaste = async () => {
    try {
      const text = await Clipboard.getStringAsync();
      if (text) {
        setUrl(text.trim());
      }
    } catch {
      Alert.alert('Notice', 'Could not read from clipboard.');
    }
  };

  const handleStart = () => {
    if (!url.trim()) {
      Alert.alert('Missing URL', 'Please paste a YouTube playlist link.');
      return;
    }

    const maxV = parseInt(maxVideos, 10);
    onSubmit({
      url: url.trim(),
      filename: filename.trim() || undefined,
      maxVideos: isNaN(maxV) || maxV <= 0 ? undefined : maxV,
      mergeMode,
      formatType: format,
    });
  };

  return (
    <View style={styles.card}>
      <Text style={styles.label}>
        Playlist Link <Text style={styles.required}>*</Text>
      </Text>

      <View style={styles.inputRow}>
        <TextInput
          style={styles.textInput}
          placeholder="https://www.youtube.com/playlist?list=..."
          placeholderTextColor={colors.textMuted}
          value={url}
          onChangeText={setUrl}
          autoCapitalize="none"
          autoCorrect={false}
          editable={!isLoading}
        />
        <TouchableOpacity
          style={styles.pasteButton}
          onPress={handlePaste}
          disabled={isLoading}
          activeOpacity={0.7}
        >
          <Text style={styles.pasteButtonText}>📋 Paste</Text>
        </TouchableOpacity>
      </View>

      <Text style={styles.label}>Custom Video Title (Optional)</Text>
      <TextInput
        style={styles.textInput}
        placeholder="e.g. My_Favorite_Course"
        placeholderTextColor={colors.textMuted}
        value={filename}
        onChangeText={setFilename}
        autoCapitalize="none"
        editable={!isLoading}
      />

      <View style={styles.formatSection}>
        <Text style={styles.label}>Format Type</Text>
        <View style={styles.pillGroup}>
          <TouchableOpacity
            style={[styles.pill, format === 'mp4' && styles.pillActive]}
            onPress={() => setFormat('mp4')}
            disabled={isLoading}
          >
            <Text style={[styles.pillText, format === 'mp4' && styles.pillTextActive]}>
              🎬 MP4 (Video)
            </Text>
          </TouchableOpacity>

          <TouchableOpacity
            style={[styles.pill, format === 'mp3' && styles.pillActive]}
            onPress={() => setFormat('mp3')}
            disabled={isLoading}
          >
            <Text style={[styles.pillText, format === 'mp3' && styles.pillTextActive]}>
              🎵 MP3 (Audio Only)
            </Text>
          </TouchableOpacity>
        </View>
      </View>

      <TouchableOpacity
        style={styles.advancedToggle}
        onPress={() => setShowAdvanced(!showAdvanced)}
        activeOpacity={0.7}
      >
        <Text style={styles.advancedToggleText}>
          {showAdvanced ? '▲ Hide Advanced Options' : '▼ Show Advanced Options'}
        </Text>
      </TouchableOpacity>

      {showAdvanced && (
        <View style={styles.advancedContainer}>
          <Text style={styles.label}>Limit Number of Videos (0 = All)</Text>
          <TextInput
            style={styles.textInput}
            placeholder="0"
            placeholderTextColor={colors.textMuted}
            value={maxVideos}
            onChangeText={setMaxVideos}
            keyboardType="numeric"
            editable={!isLoading}
          />

          <Text style={styles.label}>Merge Engine Mode</Text>
          <View style={styles.modeList}>
            {(['Auto', 'Fast FFmpeg Copy (Lossless)', 'Re-encode (MoviePy Fallback)'] as MergeMode[]).map(
              (mode) => (
                <TouchableOpacity
                  key={mode}
                  style={[styles.modeItem, mergeMode === mode && styles.modeItemActive]}
                  onPress={() => setMergeMode(mode)}
                  disabled={isLoading}
                >
                  <View style={[styles.radioDot, mergeMode === mode && styles.radioDotActive]} />
                  <Text style={[styles.modeText, mergeMode === mode && styles.modeTextActive]}>
                    {mode}
                  </Text>
                </TouchableOpacity>
              )
            )}
          </View>
        </View>
      )}

      <TouchableOpacity
        style={[styles.submitButton, isLoading && styles.submitButtonDisabled]}
        onPress={handleStart}
        disabled={isLoading}
        activeOpacity={0.8}
      >
        {isLoading ? (
          <ActivityIndicator color="#FFFFFF" size="small" />
        ) : (
          <Text style={styles.submitButtonText}>🚀 Download & Stitch Playlist</Text>
        )}
      </TouchableOpacity>
    </View>
  );
};

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.surface,
    borderRadius: 16,
    padding: 20,
    borderWidth: 1,
    borderColor: colors.surfaceBorder,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.2,
    shadowRadius: 8,
    elevation: 4,
  },
  label: {
    fontSize: 14,
    fontWeight: '600',
    color: colors.textSecondary,
    marginBottom: 8,
    marginTop: 12,
  },
  required: {
    color: colors.danger,
  },
  inputRow: {
    flexDirection: 'row',
    gap: 8,
  },
  textInput: {
    flex: 1,
    backgroundColor: colors.inputBg,
    borderRadius: 12,
    paddingHorizontal: 14,
    paddingVertical: 12,
    color: colors.text,
    fontSize: 14,
    borderWidth: 1,
    borderColor: colors.inputBorder,
  },
  pasteButton: {
    backgroundColor: colors.card,
    borderRadius: 12,
    paddingHorizontal: 14,
    justifyContent: 'center',
    alignItems: 'center',
    borderWidth: 1,
    borderColor: colors.surfaceBorder,
  },
  pasteButtonText: {
    color: colors.accent,
    fontWeight: '600',
    fontSize: 13,
  },
  formatSection: {
    marginTop: 4,
  },
  pillGroup: {
    flexDirection: 'row',
    gap: 10,
  },
  pill: {
    flex: 1,
    paddingVertical: 12,
    borderRadius: 12,
    backgroundColor: colors.card,
    alignItems: 'center',
    borderWidth: 1,
    borderColor: colors.surfaceBorder,
  },
  pillActive: {
    backgroundColor: colors.primary + '25',
    borderColor: colors.primary,
  },
  pillText: {
    color: colors.textSecondary,
    fontWeight: '600',
    fontSize: 13,
  },
  pillTextActive: {
    color: '#818CF8',
    fontWeight: '700',
  },
  advancedToggle: {
    marginTop: 16,
    paddingVertical: 8,
    alignItems: 'center',
  },
  advancedToggleText: {
    color: colors.accent,
    fontSize: 13,
    fontWeight: '600',
  },
  advancedContainer: {
    marginTop: 8,
    paddingTop: 12,
    borderTopWidth: 1,
    borderTopColor: colors.surfaceBorder,
  },
  modeList: {
    gap: 8,
    marginTop: 4,
  },
  modeItem: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    padding: 10,
    borderRadius: 10,
    backgroundColor: colors.card,
    borderWidth: 1,
    borderColor: colors.surfaceBorder,
  },
  modeItemActive: {
    borderColor: colors.primary,
    backgroundColor: colors.primary + '15',
  },
  radioDot: {
    width: 16,
    height: 16,
    borderRadius: 8,
    borderWidth: 2,
    borderColor: colors.textMuted,
  },
  radioDotActive: {
    borderColor: colors.primary,
    backgroundColor: colors.primary,
  },
  modeText: {
    fontSize: 13,
    color: colors.textSecondary,
  },
  modeTextActive: {
    color: colors.text,
    fontWeight: '600',
  },
  submitButton: {
    marginTop: 20,
    backgroundColor: colors.primary,
    borderRadius: 14,
    paddingVertical: 15,
    alignItems: 'center',
    justifyContent: 'center',
    shadowColor: colors.primary,
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.35,
    shadowRadius: 8,
    elevation: 5,
  },
  submitButtonDisabled: {
    opacity: 0.6,
  },
  submitButtonText: {
    color: '#FFFFFF',
    fontSize: 16,
    fontWeight: '700',
    letterSpacing: 0.3,
  },
});
