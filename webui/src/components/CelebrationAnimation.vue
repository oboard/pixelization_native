<script setup lang="ts">
import { ref, watch, onBeforeUnmount } from 'vue'

const props = defineProps<{ isVisible: boolean; onComplete?: () => void }>()
// 原 onComplete 回调或 @completed 事件择一接入。
const emit = defineEmits<{ completed: [] }>()
interface Particle {
  id: number; emoji: string; x: number; y: number; vx: number; vy: number
  rotation: number; rotationSpeed: number; scale: number; opacity: number; color?: string
}
const particles = ref<Particle[]>([])
const confetti = ref<Particle[]>([])
let initialFrame: number | undefined
let animationId: number | undefined
let timer: ReturnType<typeof setTimeout> | undefined
function createCelebrationParticles() {
  const celebrationEmojis = ['🎉', '🎊', '✨', '🌟', '💫', '🎈', '🎁', '🏆']
  const confettiColors = ['#ff6b6b', '#4ecdc4', '#45b7d1', '#96ceb4', '#feca57', '#ff9ff3', '#54a0ff']
  const newParticles: Particle[] = []
  for (let i = 0; i < 20; i++) {
    const fromLeft = Math.random() < 0.5
    newParticles.push({ id: Date.now() + i, emoji: celebrationEmojis[Math.floor(Math.random() * celebrationEmojis.length)],
      x: fromLeft ? -50 : window.innerWidth + 50, y: Math.random() * window.innerHeight * 0.6 + window.innerHeight * 0.2,
      vx: (fromLeft ? 1 : -1) * (Math.random() * 3 + 2), vy: (Math.random() - 0.5) * 4,
      rotation: Math.random() * 360, rotationSpeed: (Math.random() - 0.5) * 10, scale: Math.random() * 0.5 + 0.8, opacity: 1 })
  }
  const newConfetti: Particle[] = []
  for (let i = 0; i < 40; i++) {
    const fromLeft = Math.random() < 0.5
    newConfetti.push({ id: Date.now() + i + 1000, emoji: '',
      x: fromLeft ? -20 : window.innerWidth + 20, y: Math.random() * window.innerHeight * 0.4 + window.innerHeight * 0.1,
      vx: (fromLeft ? 1 : -1) * (Math.random() * 4 + 3), vy: Math.random() * 2 - 1,
      rotation: Math.random() * 360, rotationSpeed: (Math.random() - 0.5) * 15, scale: Math.random() * 0.3 + 0.2,
      opacity: 1, color: confettiColors[Math.floor(Math.random() * confettiColors.length)] })
  }
  return { newParticles, newConfetti }
}
function stop() {
  if (initialFrame !== undefined) cancelAnimationFrame(initialFrame)
  if (animationId !== undefined) cancelAnimationFrame(animationId)
  if (timer !== undefined) clearTimeout(timer)
  initialFrame = undefined; animationId = undefined; timer = undefined
  particles.value = []; confetti.value = []
}
function animate() {
  particles.value = particles.value.map(p => ({ ...p, x: p.x + p.vx, y: p.y + p.vy,
    rotation: p.rotation + p.rotationSpeed, opacity: Math.max(0, p.opacity - 0.02), vy: p.vy + 0.1 }))
    .filter(p => p.x > -100 && p.x < window.innerWidth + 100 && p.y < window.innerHeight + 100 && p.opacity > 0)
  confetti.value = confetti.value.map(p => ({ ...p, x: p.x + p.vx, y: p.y + p.vy,
    rotation: p.rotation + p.rotationSpeed, opacity: Math.max(0, p.opacity - 0.015), vy: p.vy + 0.08 }))
    .filter(p => p.x > -50 && p.x < window.innerWidth + 50 && p.y < window.innerHeight + 50 && p.opacity > 0)
  animationId = requestAnimationFrame(animate)
}
watch(() => props.isVisible, visible => {
  stop()
  if (!visible) return
  initialFrame = requestAnimationFrame(() => {
    const created = createCelebrationParticles()
    particles.value = created.newParticles
    confetti.value = created.newConfetti
  })
  animate()
  timer = setTimeout(() => { stop(); props.onComplete?.(); emit('completed') }, 1500)
}, { immediate: true })
onBeforeUnmount(stop)
</script>

<template>
  <div v-if="isVisible" class="fixed inset-0 pointer-events-none z-50">
    <div v-for="particle in particles" :key="particle.id" class="absolute text-2xl select-none"
      :style="{ left: `${particle.x}px`, top: `${particle.y}px`, transform: `rotate(${particle.rotation}deg) scale(${particle.scale})`, opacity: particle.opacity, fontSize: '24px' }">{{ particle.emoji }}</div>
    <div v-for="particle in confetti" :key="particle.id" class="absolute"
      :style="{ left: `${particle.x}px`, top: `${particle.y}px`, width: '6px', height: '12px', backgroundColor: particle.color, transform: `rotate(${particle.rotation}deg) scale(${particle.scale})`, opacity: particle.opacity, borderRadius: '1px' }" />
    <div class="absolute top-1/2 left-1/2 transform -translate-x-1/2 -translate-y-1/2 text-center animate-bounce"
      :style="{ animationDuration: '0.6s', animationTimingFunction: 'ease-out', animationFillMode: 'both' }">
      <div class="text-4xl font-bold text-warning drop-shadow-lg animate-pulse">🎉完成🎉</div>
      <div class="text-lg text-white drop-shadow-md mt-2">这个颜色拼完了！</div>
    </div>
  </div>
</template>
