<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';

type ReviewStatus = 'pending' | 'human_edited' | 'qualified' | 'unqualified';
type ReviewEvent = { from: ReviewStatus | null; to: ReviewStatus; reason: string; timestamp: string | null };
type ReviewItem = { id: string; width: number; height: number; model_version: string; status: ReviewStatus; changed_pixels: number; reviewed_at?: string | null; review_reason?: string; review_history?: ReviewEvent[] };
type ReviewPage = { items: ReviewItem[]; total: number; offset: number; limit: number };
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
const imageUrl = (id: string, kind: string) => `/api/annotation/samples/${encodeURIComponent(id)}/image?kind=${kind}`;
const pageNumber = computed(() => Math.floor(offset.value / limit) + 1);
const pageCount = computed(() => Math.max(1, Math.ceil(total.value / limit)));
const statusLabel = (status: ReviewStatus | null) => status === 'qualified' ? '合格' : status === 'unqualified' ? '不合格' : status === 'human_edited' ? '已人工修改' : status === 'pending' ? '待审核' : '初次审核';
const formatTime = (value: string | null) => value ? new Date(value).toLocaleString('zh-CN') : '时间未记录';
let loadVersion = 0;

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
  } catch (cause) { error.value = cause instanceof Error ? cause.message : String(cause); }
  finally { busy.value = false; }
}

async function turnPage(delta: number) {
  offset.value = Math.max(0, Math.min((pageCount.value - 1) * limit, offset.value + delta * limit));
  selected.value = null;
  await load();
}

onMounted(() => { void load(); });
watch(selected, () => { rejectionReason.value = ''; });
</script>

<template>
  <div class="review-page">
    <header class="header"><div><span class="eyebrow">FINAL REVIEW</span><h1>最终审核</h1><p>逐张对照原图与纠错结果，确认是否可进入训练集。</p></div><a href="/annotate">返回标注工作台</a></header>
    <div v-if="error" class="message error" role="alert">{{ error }}</div>
    <div v-if="notice" class="message notice" role="status">{{ notice }}</div>
    <div class="layout">
      <aside class="queue"><div class="queue-head"><div><strong>{{ mode === 'history' ? '审核历史' : '待审核队列' }}</strong><small>{{ total }} 张{{ mode === 'queue' ? ' · 含已人工修改' : ' · 可更正结果' }}</small></div><select v-model="size" aria-label="筛选尺寸" @change="load(true)"><option value="">全部尺寸</option><option v-for="n in [24, 52, 78, 104]" :key="n" :value="String(n)">{{ n }}px</option></select></div>
        <div class="queue-tabs" role="tablist" aria-label="审核列表"><button role="tab" :aria-selected="mode === 'queue'" :class="{ active: mode === 'queue' }" @click="setMode('queue')">待审核</button><button role="tab" :aria-selected="mode === 'history'" :class="{ active: mode === 'history' }" @click="setMode('history')">审核历史</button></div>
        <div class="queue-list"><button v-for="(item, index) in items" :key="item.id" :class="{ active: item.id === selected?.id }" @click="selected = item"><span class="number">{{ String(offset + index + 1).padStart(5, '0') }}</span><img :src="imageUrl(item.id, 'corrected')" alt=""><span><strong>{{ item.id }}</strong><small>{{ item.width }}px · {{ statusLabel(item.status) }}</small></span></button><p v-if="!items.length" class="empty">{{ mode === 'history' ? '还没有审核历史。' : '当前没有待审核图片。' }}</p></div>
        <div class="pager"><button :disabled="offset === 0" @click="turnPage(-1)">上一页</button><span>{{ pageNumber }} / {{ pageCount }}</span><button :disabled="pageNumber >= pageCount" @click="turnPage(1)">下一页</button></div>
      </aside>
      <main v-if="selected" class="detail"><div class="detail-head"><div><span class="eyebrow">{{ mode === 'history' ? 'HISTORY' : 'REVIEW' }} / {{ selected.id }}</span><h2>{{ selected.id }} <small class="detail-status" :class="selected.status">{{ statusLabel(selected.status) }}</small></h2></div><span>{{ selected.width }} × {{ selected.height }} · 修改 {{ selected.changed_pixels }} 像素</span></div>
        <div class="comparison"><section><h3>原图</h3><div class="stage"><img :src="imageUrl(selected.id, 'sources')" alt="原图"></div></section><section><h3>纠错结果</h3><div class="stage"><img class="pixel" :src="imageUrl(selected.id, 'corrected')" alt="纠错后的像素图"></div></section></div>
        <div v-if="mode === 'history'" class="history-panel"><h3>审核记录</h3><ol><li v-for="(event, index) in [...(selected.review_history || [])].reverse()" :key="index"><span class="history-time">{{ formatTime(event.timestamp) }}</span><strong>{{ statusLabel(event.from) }} → {{ statusLabel(event.to) }}</strong><span v-if="event.reason" class="history-reason">原因：{{ event.reason }}</span></li></ol></div>
        <div class="actions"><a :href="`/annotate?q=${encodeURIComponent(selected.id)}`">去编辑这张</a><div class="review-controls"><button v-if="mode === 'history' && (selected.status === 'qualified' || selected.status === 'unqualified')" class="withdraw" :disabled="busy" @click="decide('pending')">撤回到待审核</button><input v-model="rejectionReason" type="text" maxlength="500" aria-label="不合格原因" placeholder="填写不合格原因" @keydown.enter="decide('unqualified')"><button class="reject" :disabled="busy || selected.status === 'unqualified'" @click="decide('unqualified')">{{ mode === 'history' ? '改为不合格' : '不合格' }}</button><button class="approve" :disabled="busy || selected.status === 'qualified'" @click="decide('qualified')">{{ mode === 'history' ? '改为合格' : '合格' }}</button></div></div>
      </main><main v-else class="detail empty-detail">{{ mode === 'history' ? '当前筛选没有审核历史。' : '当前筛选没有待审核图片。' }}</main>
    </div>
  </div>
</template>

<style scoped>
.review-page{min-height:100vh;background:#f5f8f6;color:#223631;font-family:Inter,system-ui,sans-serif}.header{height:106px;padding:18px 32px;background:#fff;border-bottom:1px solid #dfe8e3;display:flex;justify-content:space-between;align-items:center}.eyebrow{font-size:10px;font-weight:800;letter-spacing:.18em;color:#91a49d}.header h1{font-size:25px;margin:4px 0}.header p{font-size:12px;color:#788c85;margin:0}.header a,.actions a{color:#286558;text-decoration:none;font-size:12px;font-weight:700}.layout{display:grid;grid-template-columns:270px minmax(0,1fr);min-height:calc(100vh - 106px)}.queue{background:#fff;border-right:1px solid #dfe8e3;display:flex;flex-direction:column;min-height:0}.queue-head{padding:20px 14px;display:flex;justify-content:space-between;align-items:center;gap:8px}.queue-head strong,.queue-head small{display:block}.queue-head strong{font-size:14px}.queue-head small{font-size:11px;color:#8b9c95;margin-top:4px}.queue-head select{border:1px solid #dce8e1;background:#f8faf9;padding:6px;border-radius:6px;font-size:11px}.queue-list{overflow:auto;flex:1}.queue-list button{display:flex;align-items:center;gap:9px;width:100%;border:0;border-left:3px solid transparent;background:#fff;padding:9px 10px;text-align:left;color:inherit}.queue-list button:hover{background:#f2f7f4}.queue-list button.active{background:#eaf3ee;border-left-color:#e86e42}.queue-list img{width:42px;height:42px;object-fit:contain;image-rendering:pixelated}.queue-list strong,.queue-list small{display:block}.queue-list strong{font-size:12px}.queue-list small{font-size:10px;color:#85978f;margin-top:4px}.number{font-size:10px;color:#98a8a1;width:32px}.empty{padding:16px;font-size:12px;color:#879890}.pager{border-top:1px solid #e4ebe7;display:flex;align-items:center;justify-content:space-between;padding:10px;font-size:11px;color:#70867c}.pager button{border:1px solid #dbe8e0;background:#fff;padding:6px 8px;border-radius:6px}.pager button:disabled{opacity:.4}.detail{padding:30px;min-width:0}.detail-head{display:flex;justify-content:space-between;align-items:end;margin-bottom:20px}.detail-head h2{margin:5px 0 0;font-size:23px}.detail-head>span{font-size:11px;color:#70877d}.comparison{display:grid;grid-template-columns:1fr 1fr;gap:18px}.comparison section{background:#fff;border:1px solid #dfe8e3;border-radius:12px;overflow:hidden}.comparison h3{font-size:13px;margin:0;padding:15px;border-bottom:1px solid #e6ede9}.stage{height:min(60vh,650px);min-height:330px;display:grid;place-items:center;padding:18px;background-color:#f6f8f7;background-image:linear-gradient(45deg,#e9efec 25%,transparent 25%),linear-gradient(-45deg,#e9efec 25%,transparent 25%),linear-gradient(45deg,transparent 75%,#e9efec 75%),linear-gradient(-45deg,transparent 75%,#e9efec 75%);background-size:24px 24px}.stage img{max-width:100%;max-height:100%;object-fit:contain}.stage img.pixel{width:min(100%,560px);height:min(100%,560px);image-rendering:pixelated}.actions{display:flex;align-items:center;justify-content:space-between;margin-top:20px}.actions div{display:flex;gap:10px}.actions button{border:0;border-radius:8px;padding:11px 22px;color:white;font-weight:700}.actions button:disabled{opacity:.5}.reject{background:#bb5c4e}.approve{background:#246959}.empty-detail{display:grid;place-items:center;color:#81948a}.message{margin:12px 30px;padding:10px 14px;border-radius:8px;font-size:12px}.error{background:#fff0eb;color:#a43e30}.notice{background:#e9f4ed;color:#286c4b}@media(max-width:850px){.layout{grid-template-columns:1fr}.queue{max-height:270px}.queue-list{display:flex;overflow-x:auto}.queue-list button{min-width:175px;width:auto}.detail{padding:16px}.comparison{grid-template-columns:1fr}.stage{min-height:240px;height:42vh}.header{padding:16px}}
.review-controls input{min-width:150px;width:230px;max-width:32vw;border:1px solid #d8e4dd;background:#fff;border-radius:8px;padding:10px 12px;font-size:12px;outline:none}.review-controls input:focus{border-color:#c16b5a;box-shadow:0 0 0 2px #c16b5a22}@media(max-width:850px){.actions{align-items:stretch;flex-direction:column;gap:12px}.review-controls{flex-wrap:wrap}.review-controls input{max-width:none;flex:1}}
.queue-tabs{display:flex;gap:4px;padding:0 12px 10px;border-bottom:1px solid #e4ebe7}.queue-tabs button{flex:1;border:1px solid #dde8e1;border-radius:7px;background:#f7faf8;color:#5d7469;font-size:11px;font-weight:700;padding:8px 4px}.queue-tabs button.active{background:#e8f3ed;border-color:#87b7a1;color:#235f4c}.detail-status{font-size:11px;font-weight:700;padding:4px 8px;border-radius:5px;vertical-align:middle;background:#eef1ef;color:#6a8076}.detail-status.qualified{background:#e2f4e8;color:#25734e}.detail-status.unqualified{background:#fff0ea;color:#ad4f3d}.history-panel{margin-top:18px;background:#fff;border:1px solid #dfe8e3;border-radius:10px;padding:15px 18px}.history-panel h3{margin:0 0 10px;font-size:13px}.history-panel ol{list-style:none;margin:0;padding:0;display:grid;gap:7px;max-height:180px;overflow:auto}.history-panel li{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;font-size:12px;color:#445f52}.history-time{color:#889b90;font-variant-numeric:tabular-nums}.history-reason{color:#9c5341}.review-controls{min-width:0}.review-controls input{min-width:100px}.review-controls button{white-space:nowrap}@media(max-width:1000px){.actions{align-items:stretch;flex-direction:column;gap:12px}.review-controls{flex-wrap:wrap}.review-controls input{max-width:none;flex:1}}
.actions button.withdraw{background:#f1f4f2;color:#48675a;border:1px solid #d4e0d9}
</style>
