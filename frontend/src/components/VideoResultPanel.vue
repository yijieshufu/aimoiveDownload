<script setup>
import { ref, watch } from 'vue';
import { Play } from 'lucide-vue-next';
import { apiAbsolute } from '../api/index.js';

const props = defineProps({
  videoInfo: { type: Object, default: null },
  isExtracting: { type: Boolean, default: false },
  isPro: { type: Boolean, default: false },
  isDownloading: { type: Boolean, default: false },
});

const emit = defineEmits(['download-format', 'need-pro']);

const selectedFormatId = ref(null);

watch(
  () => props.videoInfo,
  () => {
    selectedFormatId.value = null;
  }
);

function formatDuration(seconds) {
  const totalSeconds = Math.max(0, Math.floor(Number(seconds) || 0));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const remainingSeconds = totalSeconds % 60;
  if (hours > 0) return `${hours}:${String(minutes).padStart(2, '0')}:${String(remainingSeconds).padStart(2, '0')}`;
  return `${minutes}:${String(remainingSeconds).padStart(2, '0')}`;
}

function formatViews(views) {
  const v = Number(views || 0);
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
  if (v >= 1_000) return `${(v / 1_000).toFixed(1)}K`;
  return String(v || 0);
}

function formatFileSize(bytes) {
  const b = Number(bytes || 0);
  if (b >= 1024 ** 3) return `${(b / 1024 ** 3).toFixed(2)} GB`;
  if (b >= 1024 ** 2) return `${(b / 1024 ** 2).toFixed(2)} MB`;
  if (b >= 1024) return `${(b / 1024).toFixed(2)} KB`;
  return `${b} B`;
}

function isUltraHdFormat(f) {
  const w = Number(f?.width || 0);
  const h = Number(f?.height || 0);
  return Math.max(w, h) >= 3840 || Math.min(w, h) >= 2160;
}

function selectFormat(f) {
  if (!f?.format_id) return;
  selectedFormatId.value = f.format_id;
}

function isSelected(f) {
  return selectedFormatId.value === f.format_id;
}

function formatSizeLabel(f) {
  const kind = f.display_size_kind;
  const rawFs = Number(f.filesize || 0);
  const disp = Number(f.display_size_bytes || 0);
  const bytes = disp > 0 ? disp : rawFs;
  if (!bytes) {
    return '大小由平台动态下发，解析阶段常无法给出精确值';
  }
  const text = formatFileSize(bytes);
  const treatExact = kind === 'exact' || (!kind && rawFs > 0);
  if (treatExact) return text;
  if (kind === 'approx' || kind === 'estimate') return `约 ${text}`;
  return text;
}

function onStartDownload() {
  const list = props.videoInfo?.formats || [];
  const f = list.find((x) => x.format_id === selectedFormatId.value);
  if (!f) return;
  if (isUltraHdFormat(f) && !props.isPro) {
    emit('need-pro');
    return;
  }
  emit('download-format', f);
}
</script>

<template>
  <section class="lg:col-span-4 space-y-4 print-hidden">
    <div class="glass-card p-4">
      <div class="flex items-center justify-between mb-2">
        <div class="text-[11px] font-semibold tracking-[0.14em] uppercase text-slate-400">视频预览</div>
        <div v-if="videoInfo" class="pill-soft px-2 py-0.5 text-[10px] text-slate-600">
          {{ formatDuration(videoInfo?.duration) }} · {{ formatViews(videoInfo?.view_count) }} 次播放
        </div>
      </div>
      <div
        class="group relative aspect-video rounded-2xl border border-slate-200 bg-slate-100 flex items-center justify-center overflow-hidden"
      >
        <div v-if="isExtracting && !videoInfo" class="absolute inset-0 shimmer rounded-2xl"></div>
        <img
          v-if="videoInfo?.thumbnail"
          class="w-full h-full object-cover transition duration-500 ease-out group-hover:scale-[1.02]"
          :src="apiAbsolute(videoInfo.thumbnail)"
        />
        <div v-else class="text-xs text-slate-500 px-4 text-center">解析后显示预览封面</div>

        <div v-if="videoInfo?.thumbnail" class="absolute inset-0 flex items-center justify-center pointer-events-none">
          <div
            class="h-12 w-12 rounded-full bg-white/90 border border-slate-200 shadow-lg flex items-center justify-center"
          >
            <Play class="w-5 h-5 text-[#2563eb] fill-[#2563eb] translate-x-0.5" />
          </div>
        </div>
      </div>
      <div class="mt-2.5 text-xs text-slate-700 line-clamp-2 font-medium">
        {{ videoInfo?.title || '等待解析视频信息…' }}
      </div>
    </div>

    <div v-if="videoInfo" class="glass-soft p-4 space-y-3">
      <div>
        <div class="text-[11px] font-semibold tracking-[0.14em] uppercase text-slate-400 mb-1.5">解析信息</div>
        <div class="text-xs text-slate-800 truncate">{{ videoInfo.title }}</div>
        <div class="mt-0.5 text-[11px] text-slate-500">
          {{ videoInfo.uploader || '未知作者' }}
        </div>
      </div>
      <div>
        <div class="text-[11px] font-semibold tracking-[0.14em] uppercase text-slate-400 mb-1.5">下载分辨率</div>
        <div class="grid grid-cols-1 sm:grid-cols-2 gap-2">
          <button
            v-for="f in videoInfo.formats || []"
            :key="f.format_id"
            type="button"
            class="group rounded-2xl border px-3 py-2 text-left transition shadow-sm"
            :class="
              isSelected(f)
                ? 'border-blue-400 bg-blue-50/70 ring-2 ring-blue-400/40'
                : 'border-slate-200 bg-white hover:border-blue-200 hover:bg-blue-50/50'
            "
            data-magnetic
            @click="selectFormat(f)"
          >
            <div class="flex items-center justify-between gap-2">
              <div class="text-xs font-semibold text-slate-900">
                {{ f.width && f.height ? `${f.width}×${f.height}` : '音频/未知' }}
              </div>
              <div class="flex items-center gap-1.5">
                <span
                  v-if="isUltraHdFormat(f)"
                  class="px-1.5 py-0.5 rounded-full text-[9px] font-semibold border border-amber-300 bg-amber-50 text-amber-800"
                >
                  PRO
                </span>
                <div class="text-[10px] text-slate-500">{{ isSelected(f) ? '已选' : '选择' }}</div>
              </div>
            </div>
            <div class="mt-0.5 text-[10px] text-slate-500 leading-snug">
              {{ f.ext }} · {{ formatSizeLabel(f) }}
            </div>
          </button>
        </div>
        <div class="mt-3 space-y-2">
          <p v-if="isDownloading" class="text-[11px] text-blue-700 bg-blue-50 border border-blue-100 rounded-lg px-2.5 py-1.5">
            正在下载，请稍候… 完成后浏览器将开始保存文件。
          </p>
          <button
            type="button"
            class="w-full rounded-xl py-2.5 text-xs font-semibold text-white bg-[#2563eb] hover:bg-blue-600 disabled:opacity-50 disabled:cursor-not-allowed shadow-sm transition"
            :disabled="!selectedFormatId || isDownloading"
            data-magnetic
            @click="onStartDownload"
          >
            {{ isDownloading ? '正在下载…' : '开始下载' }}
          </button>
          <p v-if="!selectedFormatId && (videoInfo.formats || []).length" class="text-[10px] text-slate-400 text-center">
            请先点选一种分辨率或格式
          </p>
        </div>
      </div>
    </div>
  </section>
</template>
