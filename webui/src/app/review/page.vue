<script setup lang="ts">
import ThemeSwitcher from "../../components/ThemeSwitcher.vue";
import { computed, onMounted, ref, watch } from 'vue';

type ReviewStatus = 'pending' | 'human_edited' | 'qualified' | 'unqualified';
type ReviewEvent = { from: ReviewStatus | null; to: ReviewStatus; reason: string; timestamp: string | null };
type ReviewItem = { id: string; width: number; height: number; model_version: string; status: ReviewStatus; changed_pixels: number; reviewed_at?: string | null; review_reason?: string; review_history?: ReviewEvent[] };
type ReviewPage = { items: ReviewItem[]; total: number; offset: number; limit: number };
type ReasonSuggestion = { reason: string; count: number; last_used: string };
const items = ref<ReviewItem[]>([]);
const selected = ref<ReviewItem | null>(null);
const total = ref(0);
const offset = ref(0);
const limit = 40;
const size = ref('');
const mode = ref<'queue' | 'history'>('queue');
const busy = ref(false);
const error = ref('');
const notice = ref('');
const rejectionReason = ref('');
const reasonSuggestions = ref<{ popular: ReasonSuggestion[]; recent: ReasonSuggestion[] }>({ popular: [], recent: [] });
const reasonError = ref('');
const editorBackground = ref<'light' | 'dark'>('light');
const imageUrl = (id: string, kind: string) => `/api/annotation/samples/${encodeURIComponent(id)}/image?kind=${kind}`;
const pageNumber = computed(() => Math.floor(offset.value / limit) + 1);
const pageCount = computed(() => Math.max(1, Math.ceil(total.value / limit)));
const statusLabel = (status: ReviewStatus | null) => status === 'qualified' ? '合格' : status === 'unqualified' ? '不合格' : status === 'human_edited' ? '已人工修改' : status === 'pending' ? '待审核' : '初次审核';
const formatTime = (value: string | null) => value ? new Date(value).toLocaleString('zh-CN') : '时间未记录';
let loadVersion = 0;

async function loadReasons() {
  try {
    const response = await fetch('/api/annotation/review/reasons');
    const data = await response.json() as { popular?: ReasonSuggestion[]; recent?: ReasonSuggestion[]; error?: string };
    if (!response.ok) throw new Error(data.error || '读取常用原因失败');
    reasonSuggestions.value = { popular: data.popular || [], recent: data.recent || [] };
    reasonError.value = '';
  } catch (cause) { reasonError.value = cause instanceof Error ? cause.message : String(cause); }
}

async function load(reset = false) {
  if (reset) offset.value = 0;
  error.value = '';
  const version = ++loadVersion;
  try {
    const query = new URLSearchParams({ offset: String(offset.value), limit: String(limit), size: size.value });
    const endpoint = mode.value === 'history' ? '/api/annotation/review/history' : '/api/annotation/review';
    const response = await fetch(`${endpoint}?${query}`);
    const data = await response.json() as ReviewPage & { error?: string };
    if (!response.ok) throw new Error(data.error || '读取审核队列失败');
    if (version !== loadVersion) return;
    items.value = data.items;
    total.value = data.total;
    selected.value = items.value.find(item => item.id === selected.value?.id) || items.value[0] || null;
  } catch (cause) { if (version === loadVersion) error.value = cause instanceof Error ? cause.message : String(cause); }
}

function setMode(next: 'queue' | 'history') {
  if (mode.value === next) return;
  mode.value = next;
  selected.value = null;
  notice.value = '';
  void load(true);
}

async function decide(status: 'qualified' | 'unqualified' | 'pending') {
  if (!selected.value || busy.value) return;
  if (status === 'unqualified' && !rejectionReason.value.trim()) { error.value = '请先填写不合格原因'; return; }
  busy.value = true;
  error.value = '';
  const id = selected.value.id;
  try {
    const response = await fetch(`/api/annotation/samples/${encodeURIComponent(id)}/review`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status, expected_status: selected.value.status,
        reason: status === 'unqualified' ? rejectionReason.value.trim() : undefined }),
    });
    const data = await response.json() as { error?: string };
    if (!response.ok) throw new Error(data.error || '提交审核失败');
    notice.value = `${id} ${status === 'pending' ? '已撤回到待审核' : `已标记为${statusLabel(status)}`}`;
    await load(true);
    if (status === 'unqualified') await loadReasons();
  } catch (cause) { error.value = cause instanceof Error ? cause.message : String(cause); }
  finally { busy.value = false; }
}

async function turnPage(delta: number) {
  offset.value = Math.max(0, Math.min((pageCount.value - 1) * limit, offset.value + delta * limit));
  selected.value = null;
  await load();
}

onMounted(() => {
  if (localStorage.getItem('annotationEditorBackground') === 'dark') editorBackground.value = 'dark';
  void load();
  void loadReasons();
});
watch(editorBackground, value => localStorage.setItem('annotationEditorBackground', value));
watch(selected, () => { rejectionReason.value = ''; });
</script>

<template>
  <div class="review-page">
    <header class="header"><div class="header-actions"><ThemeSwitcher /><a href="/annotate">返回标注工作台</a></div></header>
    <div v-if="error" class="message error" role="alert">{{ error }}</div>
    <div v-if="notice" class="message notice" role="status">{{ notice }}</div>
    <div class="layout">
      <aside class="queue"><div class="queue-head"><div><strong>{{ mode === 'history' ? '审核历史' : '待审核队列' }}</strong><small>{{ total }} 张{{ mode === 'queue' ? ' · 含已人工修改' : ' · 可更正结果' }}</small></div><select v-model="size" aria-label="筛选尺寸" @change="load(true)"><option value="">全部尺寸</option><option v-for="n in [24, 52, 78, 104]" :key="n" :value="String(n)">{{ n }}px</option></select></div>
        <div class="queue-tabs" role="tablist" aria-label="审核列表"><button role="tab" :aria-selected="mode === 'queue'" :class="{ active: mode === 'queue' }" @click="setMode('queue')">待审核</button><button role="tab" :aria-selected="mode === 'history'" :class="{ active: mode === 'history' }" @click="setMode('history')">审核历史</button></div>
        <div class="queue-list"><button v-for="(item, index) in items" :key="item.id" :class="{ active: item.id === selected?.id }" @click="selected = item"><span class="number">{{ String(offset + index + 1).padStart(5, '0') }}</span><img :src="imageUrl(item.id, 'corrected')" alt=""><span><strong>{{ item.id }}</strong><small>{{ item.width }}px · {{ statusLabel(item.status) }}</small></span></button><p v-if="!items.length" class="empty">{{ mode === 'history' ? '还没有审核历史。' : '当前没有待审核图片。' }}</p></div>
        <div class="pager"><button :disabled="offset === 0" @click="turnPage(-1)">上一页</button><span>{{ pageNumber }} / {{ pageCount }}</span><button :disabled="pageNumber >= pageCount" @click="turnPage(1)">下一页</button></div>
      </aside>
      <main v-if="selected" class="detail"><div class="detail-head"><div><h2>{{ selected.id }} <small class="detail-status" :class="selected.status">{{ statusLabel(selected.status) }}</small></h2></div><div class="detail-meta"><span>{{ selected.width }} × {{ selected.height }} · 修改 {{ selected.changed_pixels }} 像素</span><a :href="`/annotate?q=${encodeURIComponent(selected.id)}`">去编辑这张</a></div></div>
        <div class="comparison"><section><h3>原图</h3><div class="stage" :class="{ 'dark-background': editorBackground === 'dark' }"><img :src="imageUrl(selected.id, 'sources')" alt="原图"></div></section><section><div class="comparison-title"><h3>纠错结果</h3><div class="background-switch" role="group" aria-label="审核背景"><span>背景</span><button type="button" :class="{ active: editorBackground === 'light' }" :aria-pressed="editorBackground === 'light'" @click="editorBackground = 'light'">浅色</button><button type="button" :class="{ active: editorBackground === 'dark' }" :aria-pressed="editorBackground === 'dark'" @click="editorBackground = 'dark'">深色</button></div></div><div class="stage" :class="{ 'dark-background': editorBackground === 'dark' }"><img class="pixel" :src="imageUrl(selected.id, 'corrected')" alt="纠错后的像素图"></div></section></div>
        <div v-if="mode === 'history'" class="history-panel"><h3>审核记录</h3><ol><li v-for="(event, index) in [...(selected.review_history || [])].reverse()" :key="index"><span class="history-time">{{ formatTime(event.timestamp) }}</span><strong>{{ statusLabel(event.from) }} → {{ statusLabel(event.to) }}</strong><span v-if="event.reason" class="history-reason">原因：{{ event.reason }}</span></li></ol></div>
        <section class="reason-suggestions" aria-label="不合格原因快捷选择"><div class="reason-section"><h3>常用原因 <small>填写次数最多的 5 种</small></h3><div class="reason-options"><button v-for="item in reasonSuggestions.popular" :key="item.reason" type="button" class="reason-chip" :title="item.reason" :aria-label="`填入不合格原因：${item.reason}`" @click="rejectionReason = item.reason">{{ item.reason }} <span>×{{ item.count }}</span></button><span v-if="!reasonSuggestions.popular.length" class="reason-empty">暂无记录</span></div></div><div class="reason-section"><h3>最近使用 <small>另外 5 种</small></h3><div class="reason-options"><button v-for="item in reasonSuggestions.recent" :key="item.reason" type="button" class="reason-chip" :title="item.reason" :aria-label="`填入不合格原因：${item.reason}`" @click="rejectionReason = item.reason">{{ item.reason }}</button><span v-if="!reasonSuggestions.recent.length" class="reason-empty">暂无更多原因</span></div></div><p v-if="reasonError" class="reason-error">{{ reasonError }}</p></section>
        <div class="actions"><div class="review-controls"><button v-if="mode === 'history' && (selected.status === 'qualified' || selected.status === 'unqualified')" class="withdraw" :disabled="busy" @click="decide('pending')">撤回到待审核</button><input v-model="rejectionReason" type="text" maxlength="500" aria-label="不合格原因" placeholder="填写不合格原因" @keydown.enter="decide('unqualified')"><button class="reject" :disabled="busy || selected.status === 'unqualified'" @click="decide('unqualified')">{{ mode === 'history' ? '改为不合格' : '不合格' }}</button><button class="approve" :disabled="busy || selected.status === 'qualified'" @click="decide('qualified')">{{ mode === 'history' ? '改为合格' : '合格' }}</button></div></div>
      </main><main v-else class="detail empty-detail">{{ mode === 'history' ? '当前筛选没有审核历史。' : '当前筛选没有待审核图片。' }}</main>
    </div>
  </div>
</template>

<style scoped>
.review-page{min-height:100vh;background:var(--color-base-200);color:var(--color-base-content);font-family:Inter,system-ui,sans-serif}.header{height:106px;padding:18px 32px;background:var(--color-base-100);border-bottom:1px solid var(--color-base-300);display:flex;justify-content:space-between;align-items:center}.eyebrow{font-size:10px;font-weight:800;letter-spacing:.18em;color:var(--ui-subtle)}.header h1{font-size:25px;margin:4px 0}.header p{font-size:12px;color:var(--ui-muted);margin:0}.header a,.actions a{color:var(--color-primary);text-decoration:none;font-size:12px;font-weight:700}.layout{display:grid;grid-template-columns:270px minmax(0,1fr);min-height:calc(100vh - 106px)}.queue{background:var(--color-base-100);border-right:1px solid var(--color-base-300);display:flex;flex-direction:column;min-height:0}.queue-head{padding:20px 14px;display:flex;justify-content:space-between;align-items:center;gap:8px}.queue-head strong,.queue-head small{display:block}.queue-head strong{font-size:14px}.queue-head small{font-size:11px;color:var(--ui-subtle);margin-top:4px}.queue-head select{border:1px solid var(--color-base-300);background:var(--color-base-200);padding:6px;border-radius:6px;font-size:11px}.queue-list{overflow:auto;flex:1}.queue-list button{display:flex;align-items:center;gap:9px;width:100%;border:0;border-left:3px solid transparent;background:var(--color-base-100);padding:9px 10px;text-align:left;color:inherit}.queue-list button:hover{background:var(--color-base-200)}.queue-list button.active{background:var(--ui-selected);border-left-color:var(--color-accent)}.queue-list img{width:42px;height:42px;object-fit:contain;image-rendering:pixelated}.queue-list strong,.queue-list small{display:block}.queue-list strong{font-size:12px}.queue-list small{font-size:10px;color:var(--ui-subtle);margin-top:4px}.number{font-size:10px;color:var(--ui-subtle);width:32px}.empty{padding:16px;font-size:12px;color:var(--ui-subtle)}.pager{border-top:1px solid var(--color-base-300);display:flex;align-items:center;justify-content:space-between;padding:10px;font-size:11px;color:var(--ui-muted)}.pager button{border:1px solid var(--color-base-300);background:var(--color-base-100);padding:6px 8px;border-radius:6px}.pager button:disabled{opacity:.4}.detail{padding:30px;min-width:0}.detail-head{display:flex;justify-content:space-between;align-items:end;margin-bottom:20px}.detail-head h2{margin:5px 0 0;font-size:23px}.detail-head>span{font-size:11px;color:var(--ui-muted)}.comparison{display:grid;grid-template-columns:1fr 1fr;gap:18px}.comparison section{background:var(--color-base-100);border:1px solid var(--color-base-300);border-radius:12px;overflow:hidden}.comparison h3{font-size:13px;margin:0;padding:15px;border-bottom:1px solid var(--color-base-300)}.stage{height:min(60vh,650px);min-height:330px;display:grid;place-items:center;padding:18px;background-color:var(--color-base-200);background-image:linear-gradient(45deg,var(--ui-checker) 25%,transparent 25%),linear-gradient(-45deg,var(--ui-checker) 25%,transparent 25%),linear-gradient(45deg,transparent 75%,var(--ui-checker) 75%),linear-gradient(-45deg,transparent 75%,var(--ui-checker) 75%);background-size:24px 24px}.stage img{max-width:100%;max-height:100%;object-fit:contain}.stage img.pixel{width:min(100%,560px);height:min(100%,560px);image-rendering:pixelated}.actions{display:flex;align-items:center;justify-content:space-between;margin-top:20px}.actions div{display:flex;gap:10px}.actions button{border:0;border-radius:8px;padding:11px 22px;color:var(--color-primary-content);font-weight:700}.actions button:disabled{opacity:.5}.reject{background:var(--color-error)}.approve{background:var(--color-primary)}.empty-detail{display:grid;place-items:center;color:var(--ui-subtle)}.message{margin:12px 30px;padding:10px 14px;border-radius:8px;font-size:12px}.error{background:var(--ui-error-soft);color:var(--color-error)}.notice{background:var(--ui-success-soft);color:var(--color-success)}@media(max-width:850px){.layout{grid-template-columns:1fr}.queue{max-height:270px}.queue-list{display:flex;overflow-x:auto}.queue-list button{min-width:175px;width:auto}.detail{padding:16px}.comparison{grid-template-columns:1fr}.stage{min-height:240px;height:42vh}.header{padding:16px}}
.review-controls input{min-width:150px;width:230px;max-width:32vw;border:1px solid var(--color-base-300);background:var(--color-base-100);border-radius:8px;padding:10px 12px;font-size:12px;outline:none}.review-controls input:focus{border-color:var(--color-error);box-shadow:0 0 0 2px color-mix(in oklab,var(--color-error) 15%,transparent)}@media(max-width:850px){.actions{align-items:stretch;flex-direction:column;gap:12px}.review-controls{flex-wrap:wrap}.review-controls input{max-width:none;flex:1}}
.reason-suggestions{margin-top:18px;padding:14px 16px;background:var(--color-base-100);border:1px solid var(--color-base-300);border-radius:10px;display:grid;gap:12px}.reason-section h3{display:flex;align-items:baseline;gap:9px;margin:0 0 8px;font-size:12px}.reason-section h3 small{font-size:10px;font-weight:400;color:var(--ui-subtle)}.reason-options{display:flex;flex-wrap:wrap;gap:7px}.reason-chip{max-width:100%;padding:7px 10px;border:1px solid var(--color-base-300);border-radius:7px;background:var(--color-base-200);color:var(--color-base-content);font-size:12px;text-align:left;overflow-wrap:anywhere;cursor:pointer}.reason-chip:hover{border-color:var(--color-error);background:var(--ui-error-soft)}.reason-chip:focus-visible{outline:2px solid var(--color-error);outline-offset:2px}.reason-chip span{margin-left:5px;color:var(--ui-subtle);white-space:nowrap}.reason-empty,.reason-error{font-size:11px;color:var(--ui-subtle)}.reason-error{margin:0;color:var(--color-error)}
.queue-tabs{display:flex;gap:4px;padding:0 12px 10px;border-bottom:1px solid var(--color-base-300)}.queue-tabs button{flex:1;border:1px solid var(--color-base-300);border-radius:7px;background:var(--color-base-200);color:var(--ui-muted);font-size:11px;font-weight:700;padding:8px 4px}.queue-tabs button.active{background:var(--ui-selected);border-color:var(--color-base-300);color:var(--color-primary)}.detail-status{font-size:11px;font-weight:700;padding:4px 8px;border-radius:5px;vertical-align:middle;background:var(--color-base-200);color:var(--ui-muted)}.detail-status.qualified{background:var(--ui-success-soft);color:var(--color-success)}.detail-status.unqualified{background:var(--ui-error-soft);color:var(--color-error)}.history-panel{margin-top:18px;background:var(--color-base-100);border:1px solid var(--color-base-300);border-radius:10px;padding:15px 18px}.history-panel h3{margin:0 0 10px;font-size:13px}.history-panel ol{list-style:none;margin:0;padding:0;display:grid;gap:7px;max-height:180px;overflow:auto}.history-panel li{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;font-size:12px;color:var(--ui-muted)}.history-time{color:var(--ui-subtle);font-variant-numeric:tabular-nums}.history-reason{color:var(--color-error)}.review-controls{min-width:0}.review-controls input{min-width:100px}.review-controls button{white-space:nowrap}@media(max-width:1000px){.actions{align-items:stretch;flex-direction:column;gap:12px}.review-controls{flex-wrap:wrap}.review-controls input{max-width:none;flex:1}}
.actions button.withdraw{background:var(--color-base-200);color:var(--ui-muted);border:1px solid var(--color-base-300)}
.header-actions{display:flex;align-items:center;gap:20px}
.background-switch{display:inline-flex;align-items:center;gap:4px;white-space:nowrap;font-size:12px;color:var(--ui-muted)}
.background-switch>span{margin-right:3px}
.background-switch button{border:1px solid var(--color-base-300);border-radius:6px;background:var(--color-base-200);color:var(--ui-muted);padding:6px 9px;font-size:11px;cursor:pointer}
.background-switch button.active{border-color:var(--color-primary);background:var(--ui-selected);color:var(--color-primary);font-weight:700}
.background-switch button:focus-visible{outline:2px solid var(--color-accent);outline-offset:2px}
/* Image backgrounds are a user preference, independent of the UI theme. */
.stage:not(.dark-background){background-color:#f6f8f7;background-image:linear-gradient(45deg,#e3e9e8 25%,transparent 25%),linear-gradient(-45deg,#e3e9e8 25%,transparent 25%),linear-gradient(45deg,transparent 75%,#e3e9e8 75%),linear-gradient(-45deg,transparent 75%,#e3e9e8 75%)}
.comparison-title{display:flex;align-items:center;justify-content:space-between;gap:8px;padding-right:12px;border-bottom:1px solid var(--color-base-300)}
.comparison-title h3{border-bottom:0;flex-shrink:0}
.comparison-title .background-switch{margin-left:auto}
.stage.dark-background{background-color:#343c40;background-image:linear-gradient(45deg,#485257 25%,transparent 25%),linear-gradient(-45deg,#485257 25%,transparent 25%),linear-gradient(45deg,transparent 75%,#485257 75%),linear-gradient(-45deg,transparent 75%,#485257 75%)}
@media(min-width:851px){.layout{height:calc(100vh - 106px);min-height:0;overflow:hidden}.queue-list{min-height:0;overflow-y:auto}.detail{min-height:0;overflow-y:auto}}
@media(max-width:650px){.header{height:auto;min-height:106px;gap:12px;flex-wrap:wrap}.header-actions{gap:12px;flex-wrap:wrap}}
/* Keep long sample identifiers and review reasons inside their columns. */
.detail-head>div,.queue-list button>span:last-child{min-width:0}
.detail-head h2,.detail-head .eyebrow,.queue-list strong,.history-reason{overflow-wrap:anywhere}
@media(max-width:850px){
  .review-page{min-height:100dvh}
  .header{height:auto;min-height:106px;align-items:flex-start;gap:14px;flex-wrap:wrap}
  .header-actions{width:100%;justify-content:space-between;gap:12px;flex-wrap:wrap}
  .header p{line-height:1.6}
  .header a,.actions a{display:inline-flex;align-items:center;min-height:44px}
  .background-switch button,.queue-head select,.queue-tabs button,.pager button{min-height:44px}
  .queue{max-height:none;min-width:0;border-right:0;border-bottom:1px solid var(--color-base-300)}
  .queue-head{padding:12px 16px}
  .queue-head select{font-size:16px}
  .queue-tabs{padding:0 16px 8px}
  .queue-list{flex:none;padding:0 6px;overscroll-behavior-x:contain}
  .queue-list button{flex:0 0 200px;min-width:0;border-left:0;border-bottom:3px solid transparent}
  .queue-list button.active{border-bottom-color:var(--color-accent)}
  .queue-list strong{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
  .number{flex-shrink:0}
  .queue-list img{flex-shrink:0}
  .pager{padding:6px 16px}
  .detail-head{align-items:flex-start;flex-direction:column;gap:10px;margin-bottom:16px}
  .detail-head h2{font-size:20px;line-height:1.6}
  .detail-status{display:inline-block;line-height:1.4}
  .comparison{gap:12px}
  .comparison h3{padding:10px 12px}
  .stage{height:auto;min-height:0;aspect-ratio:1;padding:12px;overflow:hidden}
  .stage img{width:100%;height:100%;min-width:0;min-height:0}
  .stage img.pixel{width:100%;height:100%}
  .actions{margin-top:16px;padding-bottom:env(safe-area-inset-bottom,0px)}
  .actions .review-controls{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
  .review-controls input{grid-column:1/-1;width:100%;min-width:0;max-width:none;font-size:16px;min-height:44px}
  .actions button{min-height:44px;padding:11px 12px}
  .review-controls .withdraw{grid-column:1/-1}
  .message{margin:12px 16px;overflow-wrap:anywhere}
  .history-panel{padding:12px}
  .history-panel li{gap:4px 10px}
}
@media(max-width:360px){
  .header,.detail{padding:12px}
  .header-actions{gap:4px}
}


/* Theme tokens keep controls and feedback readable in both palettes. */
.approve{background:var(--color-primary);color:var(--color-primary-content)}
.reject{background:var(--color-error);color:var(--color-error-content)}
.error{background:var(--ui-error-soft);color:var(--color-error)}
.notice{background:var(--ui-success-soft);color:var(--color-success)}
.detail-status.qualified{background:var(--ui-success-soft);color:var(--color-success)}
.detail-status.unqualified{background:var(--ui-error-soft);color:var(--color-error)}

/* Keep the full review decision in one viewport at every breakpoint. */
.review-page{height:100dvh;min-height:0;overflow:hidden;display:flex;flex-direction:column}
.header{height:48px;min-height:0;flex:none;padding:4px 16px;justify-content:flex-end}
.header-actions{gap:12px}
.header a,.detail-meta a{color:var(--color-primary);text-decoration:none;font-size:12px;font-weight:700}
.layout{flex:1;height:auto;min-height:0;overflow:hidden}
.message{position:fixed;z-index:20;top:48px;right:12px;max-width:min(440px,calc(100vw - 24px));margin:0;box-shadow:0 8px 24px #0002}
.queue-list{min-height:0;overscroll-behavior:contain}
.detail{display:flex;flex-direction:column;gap:8px;min-height:0;overflow:hidden;padding:12px 16px}
.detail-head{flex:none;align-items:center;gap:12px;margin:0}
.detail-head h2{margin:0;font-size:18px;line-height:1.3}
.detail-meta{display:flex;align-items:center;gap:14px;min-width:0}
.detail-meta span{font-size:11px;color:var(--ui-muted);white-space:nowrap}
.detail-meta a{white-space:nowrap}
.comparison{flex:1;min-height:0;gap:10px}
.comparison section{display:flex;flex-direction:column;min-height:0}
.comparison h3{flex:none;padding:7px 10px;font-size:12px}
.comparison-title{flex:none}
.stage{flex:1;min-height:0;height:auto;overflow:hidden;padding:8px}
.stage img,.stage img.pixel{width:100%;height:100%;max-width:100%;max-height:100%;object-fit:contain}
.history-panel{flex:0 1 90px;min-height:38px;overflow:auto;margin:0;padding:7px 10px}
.history-panel h3{margin:0 0 4px}
.history-panel ol{max-height:none}
.reason-suggestions{flex:none;display:grid;gap:5px;margin:0;padding:7px 9px}
.reason-section{display:grid;grid-template-columns:70px minmax(0,1fr);align-items:center;min-width:0;gap:6px}
.reason-section h3{margin:0;font-size:11px;white-space:nowrap}
.reason-section h3 small{display:none}
.reason-options{min-width:0;flex-wrap:nowrap;overflow-x:auto;gap:5px;scrollbar-width:thin;overscroll-behavior-x:contain}
.reason-chip{flex:none;max-width:210px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;padding:5px 8px;font-size:11px}
.actions{flex:none;justify-content:flex-end;margin:0;padding:0}
.actions .review-controls{display:flex;width:100%;align-items:center;flex-wrap:nowrap;gap:8px}
.review-controls input{flex:1;width:auto;max-width:none;min-width:0}
.actions button{min-height:38px;padding:8px 14px}
@media(max-width:850px){
  .layout{display:flex;flex-direction:column}
  .queue{flex:none;height:128px;max-height:none;min-width:0;overflow:hidden;border-right:0;border-bottom:1px solid var(--color-base-300)}
  .queue-head{height:32px;min-height:0;padding:2px 8px}
  .queue-head strong{font-size:12px}
  .queue-head small{display:none}
  .queue-head select{min-height:28px;padding:2px 6px;font-size:12px}
  .queue-tabs{height:30px;min-height:0;padding:0 8px 2px}
  .queue-tabs button{min-height:27px;padding:2px;font-size:11px}
  .queue-list{flex:1;height:42px;min-height:0;padding:0 4px;overflow-x:auto;overflow-y:hidden}
  .queue-list button{flex:0 0 116px;min-width:0;max-width:116px;height:42px;padding:3px 5px;gap:5px;border-left:0;border-bottom:3px solid transparent}
  .queue-list img{width:28px;height:28px}
  .queue-list strong{font-size:11px}
  .queue-list small,.number{display:none}
  .pager{height:24px;min-height:0;padding:0 8px}
  .pager button{min-height:21px;padding:1px 6px}
  .detail{flex:1;min-height:0;padding:6px 8px max(6px,env(safe-area-inset-bottom));gap:5px}
  .detail-head{flex:none;flex-direction:row;align-items:center;justify-content:space-between;gap:6px;margin:0;min-height:24px}
  .detail-head h2{font-size:14px;line-height:1.2}
  .detail-status{padding:2px 4px;font-size:10px}
  .detail-meta span{display:none}
  .detail-meta a{display:inline;font-size:11px;min-height:0}
  .comparison{flex:1;min-height:0;grid-template-columns:repeat(2,minmax(0,1fr));gap:5px}
  .comparison h3{padding:4px 5px;font-size:10px}
  .comparison-title{gap:2px;padding-right:2px}
  .comparison-title .background-switch{gap:2px}
  .background-switch>span{display:none}
  .background-switch button{min-height:22px;padding:2px 3px;font-size:9px}
  .stage{height:auto;min-height:0;aspect-ratio:auto;padding:3px}
  .stage img,.stage img.pixel{width:100%;height:100%;min-width:0;min-height:0}
  .history-panel{flex:0 1 65px;min-height:32px;padding:4px 6px}
  .history-panel h3{font-size:11px}
  .history-panel li{font-size:10px}
  .reason-suggestions{gap:3px;padding:4px 5px}
  .reason-section{grid-template-columns:48px minmax(0,1fr);gap:3px}
  .reason-section h3{font-size:10px}
  .reason-options{gap:4px}
  .reason-chip{max-width:160px;padding:4px 6px;font-size:10px}
  .actions{margin:0;padding:0}
  .actions .review-controls{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));width:100%;gap:5px}
  .review-controls input{grid-column:1/-1;width:100%;min-width:0;max-width:none;min-height:34px;height:34px;padding:4px 8px;font-size:16px}
  .actions button{min-height:34px;height:34px;padding:4px 8px;font-size:12px}
  .review-controls .withdraw{grid-column:1/-1}
  .message{top:48px}
}
@media(max-width:850px) and (max-height:550px){
  .header{height:40px}
  .message{top:40px}
  .queue-head{height:28px}
  .queue-tabs{height:27px}
  .queue-list,.queue-list button{height:36px}
  .queue{height:115px}
  .detail{gap:3px;padding-top:3px;padding-bottom:3px}
  .reason-chip{padding-top:2px;padding-bottom:2px}
  .actions button,.review-controls input{min-height:30px;height:30px}
}
</style>
