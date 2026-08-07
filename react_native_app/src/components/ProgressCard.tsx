import React from 'react';
import { View, Text, StyleSheet, TouchableOpacity, ActivityIndicator } from 'react-native';
import { colors } from '../theme/colors';

interface ProgressCardProps {
  percent: number;
  status: string;
  onCancel: () => void;
}

export const ProgressCard: React.FC<ProgressCardProps> = ({ percent, status, onCancel }) => {
  const clampedPercent = Math.min(100, Math.max(0, percent));

  return (
    <View style={styles.card}>
      <View style={styles.headerRow}>
        <View style={styles.statusGroup}>
          <ActivityIndicator size="small" color={colors.primary} />
          <Text style={styles.title}>Processing Playlist...</Text>
        </View>
        <Text style={styles.percentageText}>{clampedPercent.toFixed(1)}%</Text>
      </View>

      {/* Progress Bar Container */}
      <View style={styles.progressBarBg}>
        <View style={[styles.progressBarFill, { width: `${clampedPercent}%` }]} />
      </View>

      <Text style={styles.statusText} numberOfLines={2}>
        {status || 'Downloading videos and preparing to stitch...'}
      </Text>

      <TouchableOpacity style={styles.cancelButton} onPress={onCancel} activeOpacity={0.7}>
        <Text style={styles.cancelButtonText}>🛑 Cancel Process</Text>
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
  headerRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 14,
  },
  statusGroup: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
  },
  title: {
    fontSize: 16,
    fontWeight: '700',
    color: colors.text,
  },
  percentageText: {
    fontSize: 18,
    fontWeight: '800',
    color: colors.accent,
  },
  progressBarBg: {
    height: 10,
    backgroundColor: colors.inputBg,
    borderRadius: 5,
    overflow: 'hidden',
    borderWidth: 1,
    borderColor: colors.inputBorder,
    marginBottom: 12,
  },
  progressBarFill: {
    height: '100%',
    backgroundColor: colors.primary,
    borderRadius: 5,
  },
  statusText: {
    fontSize: 13,
    color: colors.textSecondary,
    lineHeight: 18,
    marginBottom: 16,
  },
  cancelButton: {
    paddingVertical: 10,
    borderRadius: 10,
    backgroundColor: colors.card,
    borderWidth: 1,
    borderColor: colors.danger + '60',
    alignItems: 'center',
    justifyContent: 'center',
  },
  cancelButtonText: {
    color: colors.danger,
    fontSize: 13,
    fontWeight: '600',
  },
});
