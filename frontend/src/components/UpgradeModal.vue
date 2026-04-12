<script setup>
const open = defineModel({ type: Boolean, default: false });

defineProps({
  me: { type: Object, default: null },
  isPro: { type: Boolean, default: false },
  billingState: { type: Object, default: () => ({ loading: false, error: '', lastOrder: null }) },
});

defineEmits(['oauth', 'logout', 'create-order', 'mock-paid']);

function close() {
  open.value = false;
}
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="fixed inset-0 z-[90]">
      <div class="absolute inset-0 bg-slate-900/40 backdrop-blur-sm" @click="close"></div>
      <div class="absolute inset-0 flex items-center justify-center p-4">
        <div
          class="w-full max-w-lg rounded-3xl border border-slate-200 bg-white shadow-[0_24px_60px_rgba(15,23,42,0.15)] p-5 sm:p-6"
        >
          <div class="flex items-start justify-between gap-3">
            <div>
              <div class="text-base font-semibold text-slate-900">升级 Pro</div>
              <div class="mt-1 text-xs text-slate-500">解锁 4K 下载、更高额度与高级分析体验</div>
            </div>
            <button class="px-2 py-1 text-xs text-slate-500 hover:text-slate-800 rounded-lg hover:bg-slate-100" @click="close">
              关闭
            </button>
          </div>

          <div class="mt-5">
            <div v-if="!me?.user" class="space-y-3">
              <div class="text-xs text-slate-500">先登录以继续</div>
              <div class="grid grid-cols-1 sm:grid-cols-3 gap-2">
                <button
                  class="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2.5 text-xs font-medium text-slate-700 hover:bg-slate-100"
                  data-magnetic
                  @click="$emit('oauth', 'github')"
                >
                  GitHub
                </button>
                <button
                  class="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2.5 text-xs font-medium text-slate-700 hover:bg-slate-100"
                  data-magnetic
                  @click="$emit('oauth', 'google')"
                >
                  Google
                </button>
                <button
                  class="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2.5 text-xs font-medium text-slate-700 hover:bg-slate-100"
                  data-magnetic
                  @click="$emit('oauth', 'wechat')"
                >
                  微信
                </button>
              </div>
            </div>

            <div v-else class="space-y-3">
              <div class="flex items-center justify-between">
                <div class="text-xs text-slate-500">
                  当前：<span class="font-medium text-slate-900">{{ isPro ? 'Pro' : 'Free' }}</span>
                </div>
                <button class="text-xs text-slate-500 hover:text-[#2563eb]" @click="$emit('logout')">退出登录</button>
              </div>

              <div class="grid grid-cols-1 sm:grid-cols-2 gap-2">
                <button
                  class="rounded-2xl border border-slate-200 bg-white p-3 text-left hover:border-blue-200 hover:bg-blue-50/40 transition shadow-sm"
                  data-magnetic
                  :disabled="billingState.loading"
                  @click="$emit('create-order', 'wechatpay')"
                >
                  <div class="text-xs font-semibold text-slate-900">微信支付</div>
                  <div class="text-[11px] text-slate-500 mt-0.5">¥19.99 / 月</div>
                </button>
                <button
                  class="rounded-2xl border border-slate-200 bg-white p-3 text-left hover:border-blue-200 hover:bg-blue-50/40 transition shadow-sm"
                  data-magnetic
                  :disabled="billingState.loading"
                  @click="$emit('create-order', 'alipay')"
                >
                  <div class="text-xs font-semibold text-slate-900">支付宝</div>
                  <div class="text-[11px] text-slate-500 mt-0.5">¥19.99 / 月</div>
                </button>
              </div>

              <div v-if="billingState.error" class="text-xs text-rose-600 break-all">
                {{ billingState.error }}
              </div>

              <div v-if="billingState.lastOrder" class="rounded-2xl border border-slate-200 bg-slate-50 p-3">
                <div class="text-xs text-slate-600">
                  订单：<span class="font-mono text-slate-900">{{ billingState.lastOrder.order_id }}</span>
                </div>
                <div class="text-xs text-slate-500 mt-1">
                  {{ billingState.lastOrder.message || '订单已创建' }}
                </div>
                <div class="mt-2 flex gap-2">
                  <button
                    class="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs text-slate-700 hover:bg-slate-50"
                    data-magnetic
                    :disabled="billingState.loading"
                    @click="$emit('mock-paid')"
                  >
                    开发模式：模拟支付成功
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>
