<script setup>
import { Play, Crown } from 'lucide-vue-next';

defineProps({
  me: { type: Object, default: null },
  isPro: { type: Boolean, default: false },
});

defineEmits(['open-upgrade']);
</script>

<template>
  <header class="px-4 sm:px-6 pt-4 sm:pt-5 pb-4 border-b border-slate-200/80 flex items-center justify-between gap-3 bg-white/80 backdrop-blur-sm">
    <div class="flex items-center gap-3">
      <div
        class="h-10 w-10 rounded-xl bg-[#2563eb] flex items-center justify-center shadow-md shadow-blue-500/25"
        aria-hidden="true"
      >
        <Play class="w-5 h-5 text-white fill-white translate-x-0.5" />
      </div>
      <div class="leading-tight text-left">
        <div class="text-base font-bold tracking-tight text-slate-900">万能下载</div>
        <div class="hidden sm:block mt-0.5 text-xs text-slate-500">粘贴链接 · 一键解析 · 多清晰度保存</div>
      </div>
    </div>

    <div class="flex items-center gap-2 shrink-0">
      <button
        type="button"
        class="pro-button px-3 py-2 rounded-full text-xs font-semibold transition inline-flex items-center gap-1.5"
        data-magnetic
        @click="$emit('open-upgrade')"
      >
        <Crown class="w-3.5 h-3.5 text-amber-700" />
        升级 Pro
      </button>
      <div v-if="me?.user" class="pill-soft px-2.5 py-1.5 flex items-center gap-1.5 text-xs text-slate-700">
        <span class="h-1.5 w-1.5 rounded-full" :class="isPro ? 'bg-emerald-500' : 'bg-slate-400'"></span>
        <span>{{ isPro ? 'Pro' : 'Free' }}</span>
      </div>
      <button
        v-else
        type="button"
        class="px-3 py-2 rounded-full text-xs font-medium text-slate-700 border border-slate-200 bg-white hover:bg-slate-50 transition"
        data-magnetic
        @click="$emit('open-upgrade')"
      >
        登录
      </button>
    </div>
  </header>
</template>
