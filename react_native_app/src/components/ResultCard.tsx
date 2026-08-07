import React from 'react';
import { View, Text, StyleSheet, TouchableOpacity, ActivityIndicator } from 'react-native';
import { colors } from '../theme/colors';
import { SuccessEventData } from '../types';

interface ResultCardProps {
  result: SuccessEventData;
  isSaving: boolean;
  saveProgress: number;
  onSaveToDevice: () => void;
  onReset: () => void;
}

export const ResultCard: React.FC<ResultCardProps> = ({
  result,
  isSaving,
  saveProgress,
  onSaveToDevice,
  onReset,
}) => {
  return (
    <View style={styles.card}>
      <View style={styles.badgeRow}>
        <View style={styles.badge}>
          <Text style={styles.badgeEmoji}>🎉</Text>
          <Text style={styles.badgeText}>Ready to Download</Text>
        </View>
      </View>

      <Text style={styles.fileName} numberOfLines={2}>
        {result.filename}
      </Text>

      <View style={styles.infoRow}>
        <Text style={styles.infoLabel}>Estimated Size:</Text>
        <Text style={styles.infoValue}>{result.size_mb.toFixed(2)} MB</Text>
      </View>

      {isSaving && (
        <View style={styles.savingSection}>
          <ActivityIndicator size="small" color={colors.accent} />
          <Text style={styles.savingText}>
            Saving to phone... {(saveProgress * 100).toFixed(0)}%
          </Text>
        </View>
      )}

      <TouchableOpacity
        style={[styles.saveButton, isSaving && styles.buttonDisabled]}
        onPress={onSaveToDevice}
        disabled={isSaving}
        activeOpacity={0.8}
      >
        <Text style={styles.saveButtonText}>
          {isSaving ? '⏳ Saving...' : '📥 Save to Phone & Share'}
        </Text>
      </TouchableOpacity>

      <TouchableOpacity
        style={styles.resetButton}
        onPress={onReset}
        disabled={isSaving}
        activeOpacity={0.7}
      >
        <Text style={styles.resetButtonText}>➕ Stitch Another Playlist</Text>
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
    borderColor: colors.success + '40',
    shadowColor: colors.success,
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.15,
    shadowRadius: 10,
    elevation: 4,
  },
  badgeRow: {
    flexDirection: 'row',
    marginBottom: 12,
  },
  badge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 8,
    backgroundColor: colors.success + '20',
    borderWidth: 1,
    borderColor: colors.success + '40',
  },
  badgeEmoji: {
    fontSize: 14,
  },
  badgeText: {
    color: colors.success,
    fontSize: 13,
    fontWeight: '700',
  },
  fileName: {
    fontSize: 17,
    fontWeight: '700',
    color: colors.text,
    marginBottom: 10,
  },
  infoRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    marginBottom: 16,
  },
  infoLabel: {
    color: colors.textSecondary,
    fontSize: 14,
  },
  infoValue: {
    color: colors.accent,
    fontWeight: '700',
    fontSize: 14,
  },
  savingSection: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    marginBottom: 12,
  },
  savingText: {
    color: colors.accent,
    fontSize: 13,
    fontWeight: '600',
  },
  saveButton: {
    backgroundColor: colors.success,
    borderRadius: 12,
    paddingVertical: 14,
    alignItems: 'center',
    justifyContent: 'center',
    shadowColor: colors.success,
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.3,
    shadowRadius: 8,
    elevation: 4,
  },
  saveButtonText: {
    color: '#FFFFFF',
    fontSize: 15,
    fontWeight: '700',
  },
  buttonDisabled: {
    opacity: 0.6,
  },
  resetButton: {
    marginTop: 10,
    borderRadius: 12,
    paddingVertical: 12,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.card,
    borderWidth: 1,
    borderColor: colors.surfaceBorder,
  },
  resetButtonText: {
    color: colors.textSecondary,
    fontSize: 14,
    fontWeight: '600',
  },
});
