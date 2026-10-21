<script setup lang="ts">
import { setThemePreference, themePreference, type ThemePreference } from '../lib/theme';
</script>

<template>
  <label class="theme-picker">
    <svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><path d="M12 3a9 9 0 1 0 9 9 7 7 0 0 1-9-9Z" /></svg>
    <select class="du-select du-select-sm" aria-label="界面主题" :value="themePreference" @change="setThemePreference(($event.target as HTMLSelectElement).value as ThemePreference)">
      <option value="system">跟随系统</option>
      <option value="light">亮色模式</option>
      <option value="dark">深色模式</option>
    </select>
  </label>
</template>

<style scoped>
.theme-picker{display:inline-flex;align-items:center;gap:7px;color:var(--color-base-content);flex-shrink:0}
.theme-picker select{width:auto;min-width:108px;min-height:36px;font-size:12px;background-color:var(--color-base-100)}
@media(max-width:850px){.theme-picker select{min-height:44px;font-size:16px}}
</style>
