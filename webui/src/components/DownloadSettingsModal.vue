<script setup lang="ts">
import type { GridDownloadOptions } from "../types/downloadTypes";
import DownloadSettingsModalView from "./DownloadSettingsModalView.vue";

defineProps<{
  isOpen: boolean;
  onClose: () => void;
  options: GridDownloadOptions;
  onOptionsChange: (options: GridDownloadOptions) => void;
  onDownload: (opts?: GridDownloadOptions) => void;
}>();
</script>

<template>
  <DownloadSettingsModalView
    :is-open="isOpen"
    :on-close="onClose"
    :options="options"
    :on-options-change="onOptionsChange"
    :on-download="onDownload"
  />
</template>
