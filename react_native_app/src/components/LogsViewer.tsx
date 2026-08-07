import React, { useRef, useState } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, ScrollView } from 'react-native';
import { colors } from '../theme/colors';

interface LogsViewerProps {
  logs: string[];
}

export const LogsViewer: React.FC<LogsViewerProps> = ({ logs }) => {
  const [expanded, setExpanded] = useState(false);
  const scrollViewRef = useRef<ScrollView>(null);

  if (logs.length === 0) return null;

  return (
    <View style={styles.container}>
      <TouchableOpacity
        style={styles.toggleHeader}
        onPress={() => setExpanded(!expanded)}
        activeOpacity={0.7}
      >
        <View style={styles.titleRow}>
          <Text style={styles.terminalIcon}>💻</Text>
          <Text style={styles.title}>Console Output ({logs.length} events)</Text>
        </View>
        <Text style={styles.arrow}>{expanded ? '▲' : '▼'}</Text>
      </TouchableOpacity>

      {expanded && (
        <View style={styles.logBox}>
          <ScrollView
            ref={scrollViewRef}
            style={styles.scroll}
            onContentSizeChange={() => scrollViewRef.current?.scrollToEnd({ animated: true })}
            nestedScrollEnabled
          >
            {logs.map((log, index) => (
              <Text key={index} style={styles.logLine}>
                <Text style={styles.logPrefix}>› </Text>
                {log}
              </Text>
            ))}
          </ScrollView>
        </View>
      )}
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    backgroundColor: colors.surface,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: colors.surfaceBorder,
    overflow: 'hidden',
    marginTop: 16,
  },
  toggleHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingVertical: 14,
    backgroundColor: colors.surface,
  },
  titleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  terminalIcon: {
    fontSize: 16,
  },
  title: {
    fontSize: 14,
    fontWeight: '600',
    color: colors.textSecondary,
  },
  arrow: {
    fontSize: 12,
    color: colors.textMuted,
  },
  logBox: {
    backgroundColor: colors.logBg,
    borderTopWidth: 1,
    borderTopColor: colors.surfaceBorder,
    height: 180,
    padding: 12,
  },
  scroll: {
    flex: 1,
  },
  logLine: {
    fontFamily: 'monospace',
    fontSize: 12,
    color: colors.logText,
    lineHeight: 18,
    marginBottom: 4,
  },
  logPrefix: {
    color: colors.primary,
    fontWeight: '700',
  },
});
