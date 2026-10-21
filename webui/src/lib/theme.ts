import { ref } from 'vue';

export type ThemePreference = 'system' | 'light' | 'dark';
const storageKey = 'pixelization-theme';
const systemTheme = window.matchMedia('(prefers-color-scheme: dark)');
function readPreference(): ThemePreference {
  try {
    const value = localStorage.getItem(storageKey);
    if (value === 'light' || value === 'dark') return value;
  } catch { /* Theme switching also works when storage is unavailable. */ }
  return 'system';
}
export const themePreference = ref<ThemePreference>(readPreference());

function applyTheme() {
  const dark = themePreference.value === 'dark' || (themePreference.value === 'system' && systemTheme.matches);
  document.documentElement.dataset.theme = dark ? 'forest' : 'emerald';
  // Canvas previews also use this class to redraw their neutral grid colors.
  document.documentElement.classList.toggle('dark', dark);
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', dark ? '#15221e' : '#f5f8f6');
}
export function setThemePreference(value: ThemePreference) {
  themePreference.value = value;
  try { localStorage.setItem(storageKey, value); } catch { /* Keep the in-memory preference. */ }
  applyTheme();
}
systemTheme.addEventListener('change', applyTheme);
window.addEventListener('storage', event => {
  if (event.key === storageKey || event.key === null) {
    themePreference.value = readPreference();
    applyTheme();
  }
});
applyTheme();
