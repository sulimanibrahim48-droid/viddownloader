import React from 'react';
import { View, Text, StyleSheet, TouchableOpacity } from 'react-native';
import { colors } from '../theme/colors';

interface HeaderProps {
  onOpenSettings: () => void;
  serverConnected: boolean;
}

export const Header: React.FC<HeaderProps> = ({ onOpenSettings, serverConnected }) => {
  return (
    <View style={styles.container}>
      <View style={styles.titleContainer}>
        <View style={styles.logoBadge}>
          <Text style={styles.logoEmoji}>🎬</Text>
        </View>
        <View>
          <Text style={styles.title}>Playlist Stitcher</Text>
          <Text style={styles.subtitle}>Mobile Downloader & Merger</Text>
        </View>
      </View>

      <TouchableOpacity 
        style={[styles.settingsButton, !serverConnected && styles.settingsButtonWarning]} 
        onPress={onOpenSettings}
        activeOpacity={0.7}
      >
        <Text style={styles.settingsIcon}>⚙️</Text>
        <View style={[styles.statusDot, serverConnected ? styles.dotConnected : styles.dotDisconnected]} />
      </TouchableOpacity>
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 20,
    paddingTop: 16,
    paddingBottom: 16,
    backgroundColor: colors.surface,
    borderBottomWidth: 1,
    borderBottomColor: colors.surfaceBorder,
  },
  titleContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
  },
  logoBadge: {
    width: 44,
    height: 44,
    borderRadius: 12,
    backgroundColor: colors.primary + '25',
    borderWidth: 1,
    borderColor: colors.primary + '40',
    alignItems: 'center',
    justifyContent: 'center',
  },
  logoEmoji: {
    fontSize: 22,
  },
  title: {
    fontSize: 19,
    fontWeight: '700',
    color: colors.text,
    letterSpacing: 0.3,
  },
  subtitle: {
    fontSize: 12,
    color: colors.textSecondary,
    marginTop: 1,
  },
  settingsButton: {
    width: 42,
    height: 42,
    borderRadius: 12,
    backgroundColor: colors.card,
    borderWidth: 1,
    borderColor: colors.surfaceBorder,
    alignItems: 'center',
    justifyContent: 'center',
    position: 'relative',
  },
  settingsButtonWarning: {
    borderColor: colors.warning,
  },
  settingsIcon: {
    fontSize: 18,
  },
  statusDot: {
    width: 9,
    height: 9,
    borderRadius: 5,
    position: 'absolute',
    top: 6,
    right: 6,
    borderWidth: 1.5,
    borderColor: colors.surface,
  },
  dotConnected: {
    backgroundColor: colors.success,
  },
  dotDisconnected: {
    backgroundColor: colors.danger,
  },
});
