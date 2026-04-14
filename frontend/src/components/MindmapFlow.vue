<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue';
import { VueFlow, useVueFlow } from '@vue-flow/core';
import { Background } from '@vue-flow/background';
import '@vue-flow/core/dist/style.css';
import '@vue-flow/core/dist/theme-default.css';
import { toPng, toSvg } from 'html-to-image';
// 轻编辑版：不做一级折叠/多布局，减少心智与工具栏负担

const props = defineProps({
  mindmap: { type: Object, default: () => ({ title: '视频主题', children: [] }) },
});
const emit = defineEmits(['change']);

const flowWrap = ref(null);
const renameInputRef = ref(null);
const selectedNodeId = ref('');
const isFullscreen = ref(false);
const isExporting = ref(false);

const RENAME_DIALOG_CLOSED = { visible: false, nodeId: '', value: '', title: '重命名节点', isNew: false };
const renameDialog = ref({ ...RENAME_DIALOG_CLOSED });
const contextMenu = ref({ visible: false, x: 0, y: 0, nodeId: '' });

const nodes = ref([]);
const edges = ref([]);
const nodeMap = ref(new Map());
const { fitView, zoomIn, zoomOut } = useVueFlow();

/** 柔和 pastel，与「文本+下划线」风格搭配 */
const BRANCH_PALETTE = ['#d97757', '#6ea8d9', '#8b7cb8', '#6b9e7d', '#c4a35a', '#5a9ba8', '#d4a574', '#7b9ed1'];

/** 仅由节点 id 决定颜色，避免拖拽后子节点顺序变化导致配色跳变 */
function stableBranchColor(nodeId) {
  let h = 2166136261;
  const s = String(nodeId || 'x');
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return BRANCH_PALETTE[(Math.abs(h) >>> 0) % BRANCH_PALETTE.length];
}

/** 当前导图数据（用于布局/导出/保存） */
const mindmapInternal = ref({ title: '视频主题', children: [] });

function cleanName(name) {
  const s = String(name || '').trim();
  if (!s) return '';
  if (/^[\-\_=~`!@#$%^&*(){}\[\]|\\:;"'<>,.?/，。！？；：、（）【】《》]+$/.test(s)) return '';
  return s.slice(0, 40);
}

function sanitizeTree(root) {
  const title = cleanName(root?.title) || '视频主题';
  const dedup = new Set();
  function walk(node, depth = 1) {
    if (!node || depth > 4) return null;
    const name = cleanName(node.name || node.title);
    const children = (Array.isArray(node.children) ? node.children : []).map((c) => walk(c, depth + 1)).filter(Boolean);
    if (!name && children.length === 0) return null;
    return {
      id: String(node.id || `n_${Math.random().toString(16).slice(2, 8)}`),
      name: name || '节点',
      start: Number(node.start || 0),
      end: Number(node.end || 0),
      importance: Math.max(1, Math.min(5, Number(node.importance || 3))),
      children: children.slice(0, 8),
    };
  }
  const children = [];
  for (const c of root?.children || []) {
    const x = walk(c, 1);
    if (!x) continue;
    const k = x.name.toLowerCase().replace(/\s+/g, '');
    if (dedup.has(k)) continue;
    dedup.add(k);
    children.push(x);
  }
  return { title, children: children.slice(0, 8) };
}

function mindmapStructureSignature(tree) {
  function nodeSig(node) {
    return [node.id, node.name, (node.children || []).map(nodeSig)];
  }
  return JSON.stringify([tree.title, (tree.children || []).map(nodeSig)]);
}

function edgeDefaults(stroke, strokeWidth) {
  return {
    type: 'default',
    animated: false,
    style: {
      '--mm-edge': stroke,
      stroke: stroke,
      fill: 'none',
      strokeWidth,
      strokeOpacity: 0.88,
      strokeLinecap: 'round',
      strokeLinejoin: 'round',
    },
  };
}

/** 文本框风：白底 + 圆角 + 细边框 */
function cleanNodeStyle(color, { isRoot = false, depth = 1 } = {}) {
  const accent = color || '#94a3b8';
  const borderAlpha = isRoot ? 0.55 : depth <= 2 ? 0.45 : 0.35;
  const bg = isRoot ? 'rgba(255,255,255,0.94)' : 'rgba(255,255,255,0.92)';
  // html-to-image 在部分浏览器/环境下对 color-mix/复杂阴影兼容性较差，导出会出现黑块伪影
  const safeBorder = `rgba(148, 163, 184, ${borderAlpha})`;
  return {
    '--mm-border-accent': accent,
    '--mm-edge': accent,
    background: bg,
    border: `1px solid ${safeBorder}`,
    color: isRoot ? '#0f172a' : depth <= 2 ? '#1e293b' : '#334155',
    borderRadius: isRoot ? '12px' : '10px',
    padding: isRoot ? '8px 12px' : '7px 10px',
    fontWeight: isRoot ? '600' : depth <= 2 ? '500' : '400',
    fontSize: isRoot ? '14px' : '13px',
    maxWidth: '240px',
    lineHeight: '1.5',
    boxShadow: 'none',
  };
}

function buildGraphBilateral(tree, opts = {}) {
  const preservePositions = opts.preservePositions !== false;
  const onlyRight = opts.onlyRight === true;
  const prevPos = preservePositions ? new Map(nodes.value.map((x) => [x.id, { ...x.position }])) : new Map();

  const n = [];
  const e = [];
  const map = new Map();

  const colW = 248;
  const rowH = 86;
  const gapY = 16;
  const gapBranch = 32;
  const branchDeltaX = 40;

  function subtreeHeight(node) {
    const ch = node.children || [];
    if (ch.length === 0) return rowH;
    let h = 0;
    ch.forEach((c, i) => {
      h += subtreeHeight(c);
      if (i < ch.length - 1) h += gapY;
    });
    return Math.max(rowH, h);
  }

  function placeDescendants(parentNode, parentId, bandTop, bandBottom, sign, color, branchIdx, depth) {
    const children = parentNode.children || [];
    if (children.length === 0) return;
    const totalInner = children.reduce((acc, c, i) => acc + subtreeHeight(c) + (i < children.length - 1 ? gapY : 0), 0);
    let y = bandTop + (bandBottom - bandTop - totalInner) / 2;
    const x = sign * (colW * depth + branchIdx * branchDeltaX);

    children.forEach((child) => {
      const h = subtreeHeight(child);
      const cy = y + h / 2;
      n.push({
        id: child.id,
        type: 'default',
        position: { x, y: cy },
        data: { label: child.name, mmBranchColor: color },
        class: depth <= 2 ? 'mm-node--l1' : 'mm-node--deep',
        style: cleanNodeStyle(color, { isRoot: false, depth }),
        draggable: true,
      });
      e.push({
        id: `e_${parentId}_${child.id}`,
        source: parentId,
        target: child.id,
        ...edgeDefaults(color, 1.15),
      });
      map.set(child.id, child);
      placeDescendants(child, child.id, y, y + h, sign, color, branchIdx, depth + 1);
      y += h + gapY;
    });
  }

  function placeSide(sideList, sign) {
    if (!sideList.length) return;
    const totalH = sideList.reduce((s, it) => s + subtreeHeight(it.node) + gapBranch, 0) - gapBranch;
    let yTop = -totalH / 2;

    sideList.forEach((item, branchIdx) => {
      const th = subtreeHeight(item.node);
      const yCenter = yTop + th / 2;
      n.push({
        id: item.node.id,
        type: 'default',
        position: { x: sign * colW, y: yCenter },
        data: { label: item.node.name, mmBranchColor: item.color },
        class: 'mm-node--l1',
        style: cleanNodeStyle(item.color, { isRoot: false, depth: 2 }),
        draggable: true,
      });
      e.push({
        id: `e_root_${item.node.id}`,
        source: 'root',
        target: item.node.id,
        ...edgeDefaults(item.color, 1.35),
      });
      map.set(item.node.id, item.node);
      placeDescendants(item.node, item.node.id, yTop, yTop + th, sign, item.color, branchIdx, 2);
      yTop += th + gapBranch;
    });
  }

  n.push({
    id: 'root',
    type: 'default',
    position: { x: 0, y: 0 },
    data: { label: tree.title, mmRoot: true },
    class: 'mm-node--root',
    style: cleanNodeStyle('#64748b', { isRoot: true, depth: 0 }),
    draggable: true,
  });
  map.set('root', { title: tree.title, children: [] });

  if (onlyRight) {
    const right = [];
    (tree.children || []).forEach((c) => {
      right.push({ node: c, parent: 'root', color: stableBranchColor(c.id) });
    });
    placeSide(right, 1);
  } else {
    const right = [];
    const left = [];
    (tree.children || []).forEach((c, idx) =>
      (idx % 2 === 0 ? right : left).push({ node: c, parent: 'root', color: stableBranchColor(c.id) })
    );
    placeSide(right, 1);
    placeSide(left, -1);
  }

  if (preservePositions) {
    for (const node of n) {
      const p = prevPos.get(node.id);
      if (p) node.position = { ...p };
    }
  }

  nodes.value = n;
  edges.value = e;
  nodeMap.value = map;
}

function buildGraphTreeDown(tree, opts = {}) {
  const preservePositions = opts.preservePositions !== false;
  const prevPos = preservePositions ? new Map(nodes.value.map((x) => [x.id, { ...x.position }])) : new Map();
  const NODE_W = 240;
  const NODE_H = 80;
  const GAP_X = 36;
  const GAP_Y = 44;
  const n = [];
  const e = [];
  const map = new Map();

  function subtreeSpanWidth(node) {
    const ch = node.children || [];
    if (!ch.length) return NODE_W;
    let total = 0;
    ch.forEach((c, i) => {
      total += subtreeSpanWidth(c) + (i > 0 ? GAP_X : 0);
    });
    return Math.max(NODE_W, total);
  }

  function placeBranch(node, parentId, centerX, topY, color, depth) {
    const isL1 = depth === 1;
    const col = color || stableBranchColor(node.id);
    n.push({
      id: node.id,
      type: 'default',
      position: { x: centerX - NODE_W / 2, y: topY },
      data: { label: node.name, mmBranchColor: col },
      class: isL1 ? 'mm-node--l1' : 'mm-node--deep',
      style: cleanNodeStyle(col, { isRoot: false, depth }),
      draggable: true,
    });
    map.set(node.id, node);
    if (parentId) {
      e.push({
        id: `e_${parentId}_${node.id}`,
        source: parentId,
        target: node.id,
        ...edgeDefaults(col, depth <= 1 ? 1.35 : 1.15),
      });
    }
    const ch = node.children || [];
    if (!ch.length) return;
    const widths = ch.map(subtreeSpanWidth);
    const totalW = widths.reduce((a, b) => a + b, 0) + (ch.length - 1) * GAP_X;
    let x0 = centerX - totalW / 2;
    const childY = topY + NODE_H + GAP_Y;
    ch.forEach((child, i) => {
      const w = widths[i];
      const cx = x0 + w / 2;
      placeBranch(child, node.id, cx, childY, col, depth + 1);
      x0 += w + GAP_X;
    });
  }

  n.push({
    id: 'root',
    type: 'default',
    position: { x: -NODE_W / 2, y: 0 },
    data: { label: tree.title, mmRoot: true },
    class: 'mm-node--root',
    style: cleanNodeStyle('#64748b', { isRoot: true, depth: 0 }),
    draggable: true,
  });
  map.set('root', { title: tree.title, children: [] });

  const children = tree.children || [];
  if (children.length) {
    const widths = children.map(subtreeSpanWidth);
    const totalW = widths.reduce((a, b) => a + b, 0) + (children.length - 1) * GAP_X;
    let x0 = -totalW / 2;
    const childY = NODE_H + GAP_Y;
    children.forEach((child, i) => {
      const w = widths[i];
      const cx = x0 + w / 2;
      placeBranch(child, 'root', cx, childY, stableBranchColor(child.id), 1);
      x0 += w + GAP_X;
    });
  }

  if (preservePositions) {
    for (const node of n) {
      const p = prevPos.get(node.id);
      if (p) node.position = { ...p };
    }
  }

  nodes.value = n;
  edges.value = e;
  nodeMap.value = map;
}

function buildGraph(tree, opts = {}) {
  // 轻编辑版固定单侧向右布局，减少心智与 UI
  buildGraphBilateral(tree, { ...opts, onlyRight: true });
}

function exportTreeFromGraph() {
  const idToNode = new Map();
  const root = { title: '', children: [] };
  const rootNode = nodes.value.find((x) => x.id === 'root');
  root.title = String(rootNode?.data?.label || '视频主题');
  for (const n of nodes.value) {
    if (n.id === 'root') continue;
    const raw = nodeMap.value.get(n.id) || {};
    idToNode.set(n.id, { id: n.id, name: String(n.data?.label || '节点'), start: Number(raw.start || 0), end: Number(raw.end || 0), importance: Number(raw.importance || 3), children: [] });
  }
  const edgeBySource = new Map();
  for (const x of edges.value) {
    const arr = edgeBySource.get(x.source) || [];
    arr.push(x.target);
    edgeBySource.set(x.source, arr);
  }
  function buildChildren(parentId) {
    const ids = edgeBySource.get(parentId) || [];
    return ids.map((id) => {
      const node = idToNode.get(id);
      if (!node) return null;
      node.children = buildChildren(id);
      return node;
    }).filter(Boolean);
  }
  root.children = buildChildren('root');
  return sanitizeTree(root);
}

function emitChange() {
  const visible = exportTreeFromGraph();
  mindmapInternal.value = JSON.parse(JSON.stringify(visible));
  emit('change', mindmapInternal.value);
}

function onNodeClick(payload) {
  const node = payload?.node;
  if (!node) return;
  selectedNodeId.value = node.id;
}

function onNodeDragStop() {
  emitChange();
}

function closeContextMenu() {
  contextMenu.value = { ...contextMenu.value, visible: false };
}

function openRenameDialog(nodeId, opts = {}) {
  const node = nodes.value.find((x) => x.id === nodeId);
  if (!node) return;
  closeContextMenu();
  renameDialog.value = {
    visible: true,
    nodeId,
    value: String(node.data?.label || ''),
    title: opts.title || '重命名节点',
    isNew: Boolean(opts.isNew),
  };
}

function openAddNodeDialog(pid) {
  const parent = nodes.value.find((x) => x.id === pid);
  if (!parent) return;
  closeContextMenu();
  const id = `n_${Date.now().toString(16)}_${Math.random().toString(16).slice(2, 6)}`;
  const p = parent;
  const branchColor = p.data?.mmBranchColor || (pid === 'root' ? stableBranchColor(id) : '#64748b');
  nodes.value.push({
    id,
    position: { x: p.position.x + 220, y: p.position.y + 40 },
    data: { label: '新节点', mmBranchColor: branchColor },
    class: 'mm-node--deep',
    style: cleanNodeStyle(branchColor, { isRoot: false, depth: 3 }),
    draggable: true,
  });
  edges.value.push({
    id: `e_${pid}_${id}`,
    source: pid,
    target: id,
    type: 'default',
    animated: false,
    style: {
      '--mm-edge': branchColor,
      stroke: 'var(--mm-edge)',
      strokeWidth: 1.8,
    },
  });
  selectedNodeId.value = id;
  renameDialog.value = {
    visible: true,
    nodeId: id,
    value: '',
    title: '新建节点',
    isNew: true,
  };
}

function confirmRenameDialog() {
  const { nodeId, value } = renameDialog.value;
  const node = nodes.value.find((x) => x.id === nodeId);
  if (node) {
    const t = String(value || '').trim() || (nodeId === 'root' ? '视频主题' : '节点');
    node.data = { ...node.data, label: t.slice(0, 40) };
    emitChange();
  }
  renameDialog.value = { ...RENAME_DIALOG_CLOSED };
}

function cancelRenameDialog() {
  const { nodeId, isNew } = renameDialog.value;
  if (isNew && nodeId) {
    nodes.value = nodes.value.filter((n) => n.id !== nodeId);
    edges.value = edges.value.filter((e) => e.target !== nodeId && e.source !== nodeId);
    if (selectedNodeId.value === nodeId) selectedNodeId.value = '';
    emitChange();
  }
  renameDialog.value = { ...RENAME_DIALOG_CLOSED };
}

function onNodeContextMenu(evt) {
  const e = evt?.event || evt;
  if (e?.preventDefault) e.preventDefault();
  if (e?.stopPropagation) e.stopPropagation();
  const node = evt?.node;
  if (!node) return;
  contextMenu.value = { visible: true, x: e.clientX, y: e.clientY, nodeId: node.id };
}

function onPaneContextMenu(evt) {
  const e = evt?.event || evt;
  if (e?.preventDefault) e.preventDefault();
  if (e?.stopPropagation) e.stopPropagation();
  // 画布右键：默认对 root 添加子节点
  contextMenu.value = { visible: true, x: e.clientX, y: e.clientY, nodeId: 'root' };
}

function onWrapContextMenu(e) {
  if (e?.preventDefault) e.preventDefault();
  // 若是节点区域，节点自身右键逻辑会先处理；这里兜底画布右键
  contextMenu.value = { visible: true, x: e.clientX, y: e.clientY, nodeId: 'root' };
}

function onNodeDoubleClick(evt) {
  const node = evt?.node;
  if (node) openRenameDialog(node.id);
}

function onPaneClick() {
  closeContextMenu();
}

function contextAddChild() {
  const pid = contextMenu.value.nodeId || 'root';
  closeContextMenu();
  openAddNodeDialog(pid);
}

function contextAddSibling() {
  const sid = contextMenu.value.nodeId;
  closeContextMenu();
  if (!sid || sid === 'root') return;
  const parentEdge = edges.value.find((x) => x.target === sid);
  if (!parentEdge) return;
  openAddNodeDialog(parentEdge.source);
}

function contextRename() {
  const id = contextMenu.value.nodeId;
  closeContextMenu();
  if (id) openRenameDialog(id);
}

function contextDelete() {
  const sid = contextMenu.value.nodeId;
  closeContextMenu();
  if (!sid || sid === 'root') return;
  selectedNodeId.value = sid;
  deleteNode();
}

function addChild() {
  const pid = selectedNodeId.value || 'root';
  openAddNodeDialog(pid);
}

function addSibling() {
  const sid = selectedNodeId.value;
  if (!sid || sid === 'root') return;
  const parentEdge = edges.value.find((x) => x.target === sid);
  if (!parentEdge) return;
  openAddNodeDialog(parentEdge.source);
}

function deleteNode() {
  const sid = selectedNodeId.value;
  if (!sid || sid === 'root') return;
  const removeSet = new Set([sid]);
  let changed = true;
  while (changed) {
    changed = false;
    for (const e of edges.value) {
      if (removeSet.has(e.source) && !removeSet.has(e.target)) {
        removeSet.add(e.target);
        changed = true;
      }
    }
  }
  nodes.value = nodes.value.filter((n) => !removeSet.has(n.id));
  edges.value = edges.value.filter((e) => !removeSet.has(e.source) && !removeSet.has(e.target));
  selectedNodeId.value = '';
  emitChange();
}

function toggleFullscreen() {
  isFullscreen.value = !isFullscreen.value;
  setTimeout(() => fitView({ padding: 0.2, includeHiddenNodes: true }), 60);
}

const EXPORT_BG = '#f8fafc';

function exportImageFilter(node) {
  if (!node || node.nodeType !== 1) return true;
  const el = node;
  if (typeof el.classList?.contains === 'function' && el.classList.contains('vue-flow__controls')) {
    return false;
  }
  return true;
}

function onExportClone(_clonedDoc, clonedElement) {
  const wrap =
    clonedElement?.classList?.contains?.('flow-wrap') === true
      ? clonedElement
      : clonedElement?.querySelector?.('.flow-wrap');
  if (!wrap) return;
  wrap.style.setProperty('backdrop-filter', 'none', 'important');
  wrap.style.setProperty('-webkit-backdrop-filter', 'none', 'important');
  wrap.style.setProperty('background', EXPORT_BG, 'important');
}

function normalizeSvgExportString(raw) {
  let s = String(raw ?? '').trim().replace(/^\uFEFF/, '');
  if (!s) return null;
  const head = s.slice(0, 64).toLowerCase();
  if (head.startsWith('data:image/svg+xml')) {
    const comma = s.indexOf(',');
    if (comma === -1) return null;
    const meta = s.slice(0, comma);
    const data = s.slice(comma + 1);
    if (/;base64/i.test(meta)) {
      try {
        s = atob(data);
      } catch {
        return null;
      }
    } else {
      try {
        s = decodeURIComponent(data);
      } catch {
        return null;
      }
    }
  }
  const t = s.trim();
  if (!/^<\?xml/i.test(t) && !/^<svg/i.test(t)) return null;
  if (!/^<\?xml/i.test(t)) {
    s = `<?xml version="1.0" encoding="UTF-8"?>\n${t}`;
  }
  return s;
}

async function prepareMindmapForExport() {
  buildGraph(mindmapInternal.value, { preservePositions: false });
  await nextTick();
  fitView({ padding: 0.15, includeHiddenNodes: true, duration: 0 });
  await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
}

const imageExportBaseOptions = {
  cacheBust: true,
  backgroundColor: EXPORT_BG,
  filter: exportImageFilter,
  skipFonts: true,
  onclone: onExportClone,
};

async function exportSvg() {
  if (!flowWrap.value) return;
  isExporting.value = true;
  try {
    await prepareMindmapForExport();
    const raw = await toSvg(flowWrap.value, imageExportBaseOptions);
    const svg = normalizeSvgExportString(raw);
    if (!svg) {
      window.alert('SVG 导出失败：无法生成有效矢量内容，请尝试导出 PNG。');
      return;
    }
    const blob = new Blob([svg], { type: 'image/svg+xml;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = '思维导图.svg';
    a.click();
    URL.revokeObjectURL(url);
  } catch (e) {
    window.alert(`SVG 导出失败：${String(e?.message || e)}`);
  } finally {
    isExporting.value = false;
  }
}

async function exportPng4k() {
  if (!flowWrap.value) return;
  isExporting.value = true;
  try {
    await prepareMindmapForExport();
    const rect = flowWrap.value.getBoundingClientRect();
    const scale = Math.min(3, Math.max(2, Math.ceil(3840 / Math.max(1, rect.width))));
    const dataUrl = await toPng(flowWrap.value, { ...imageExportBaseOptions, pixelRatio: scale });
    const a = document.createElement('a');
    a.href = dataUrl;
    a.download = '思维导图_4k.png';
    a.click();
  } catch (e) {
    window.alert(`PNG 导出失败：${String(e?.message || e)}`);
  } finally {
    isExporting.value = false;
  }
}

const lastMindmapSig = ref('');
const didInitialFit = ref(false);

watch(
  () => props.mindmap,
  async (v) => {
    const cleaned = sanitizeTree(v || { title: '视频主题', children: [] });
    const sig = mindmapStructureSignature(cleaned);
    if (sig === lastMindmapSig.value && lastMindmapSig.value !== '') return;
    lastMindmapSig.value = sig;
    mindmapInternal.value = JSON.parse(JSON.stringify(cleaned));
    buildGraph(mindmapInternal.value, { preservePositions: true });
    if (!didInitialFit.value) {
      didInitialFit.value = true;
      await nextTick();
      setTimeout(() => fitView({ padding: 0.2, includeHiddenNodes: true }), 20);
    }
  },
  { immediate: true }
);

const rootCls = computed(() => (isFullscreen.value ? 'mindmap-root mindmap-root-fullscreen' : 'mindmap-root'));

const contextMenuDeleteDisabled = computed(() => {
  const id = contextMenu.value.nodeId;
  return !id || id === 'root';
});

const contextMenuSiblingDisabled = computed(() => {
  const id = contextMenu.value.nodeId;
  return !id || id === 'root';
});

function onKeydown(e) {
  if (renameDialog.value.visible) {
    if (e.key === 'Escape') {
      e.preventDefault();
      cancelRenameDialog();
    }
    return;
  }
  if (e.key === 'Escape') {
    closeContextMenu();
    if (isFullscreen.value) {
      e.preventDefault();
      isFullscreen.value = false;
    }
    return;
  }
  const tag = (e.target && e.target.tagName) || '';
  if (tag === 'INPUT' || tag === 'TEXTAREA' || e.target?.isContentEditable) return;
  // 轻编辑版：不提供 F2 / Del 等编辑器快捷键，避免误触
}

watch(
  () => renameDialog.value.visible,
  async (v) => {
    if (!v) return;
    await nextTick();
    renameInputRef.value?.focus?.();
    renameInputRef.value?.select?.();
  }
);

onMounted(() => {
  window.addEventListener('keydown', onKeydown);
  window.addEventListener('click', onWindowClickCloseMenu);
});

onUnmounted(() => {
  window.removeEventListener('keydown', onKeydown);
  window.removeEventListener('click', onWindowClickCloseMenu);
});

function onWindowClickCloseMenu(e) {
  if (!contextMenu.value.visible) return;
  const t = e.target;
  if (t && t.closest && t.closest('.mindmap-context-menu')) return;
  closeContextMenu();
}
</script>

<template>
  <div :class="rootCls">
    <div class="toolbar">
      <button @click="addChild">添加子节点</button>
      <button @click="addSibling">添加同级节点</button>
      <button @click="deleteNode">删除</button>
      <span class="sep"></span>
      <button @click="() => fitView({ padding: 0.2, includeHiddenNodes: true })">适应画布</button>
      <button @click="zoomOut">缩小</button>
      <button @click="zoomIn">放大</button>
      <button type="button" @click="toggleFullscreen">{{ isFullscreen ? '退出全屏' : '全屏' }}</button>
      <span class="sep"></span>
      <button :disabled="isExporting" @click="exportSvg">导出 SVG</button>
      <button :disabled="isExporting" @click="exportPng4k">导出 PNG（4K+）</button>
    </div>
    <div ref="flowWrap" class="flow-wrap" @contextmenu.prevent="onWrapContextMenu">
      <VueFlow
        v-model:nodes="nodes"
        v-model:edges="edges"
        :min-zoom="0.2"
        :max-zoom="2.5"
        :nodes-draggable="true"
        :nodes-selectable="false"
        :elements-selectable="false"
        :nodes-focusable="false"
        :edges-focusable="false"
        :select-nodes-on-drag="false"
        :elevate-nodes-on-select="false"
        :elevate-edges-on-select="false"
        :pan-on-drag="true"
        @node-drag-stop="onNodeDragStop"
        @node-click="onNodeClick"
        @node-double-click="onNodeDoubleClick"
        @node-context-menu="onNodeContextMenu"
        @pane-context-menu="onPaneContextMenu"
        @pane-click="onPaneClick"
      >
        <Background variant="dots" :gap="22" :size="1" pattern-color="#e2e8f0" bg-color="#f8fafc" />
      </VueFlow>
    </div>

    <Teleport to="body">
      <div
        v-if="contextMenu.visible"
        class="mindmap-context-menu"
        :style="{ position: 'fixed', left: `${contextMenu.x}px`, top: `${contextMenu.y}px`, zIndex: 80 }"
        @click.stop
      >
        <button type="button" @click="contextAddChild">添加子节点</button>
        <button type="button" :disabled="contextMenuSiblingDisabled" @click="contextAddSibling">添加同级节点</button>
        <button type="button" @click="contextRename">重命名</button>
        <button type="button" :disabled="contextMenuDeleteDisabled" class="danger" @click="contextDelete">删除</button>
      </div>
    </Teleport>

    <Teleport to="body">
      <div v-if="renameDialog.visible" class="mindmap-rename-overlay" @click.self="cancelRenameDialog">
        <div class="mindmap-rename-box" @click.stop>
          <div class="mindmap-rename-title">{{ renameDialog.title }}</div>
          <input
            ref="renameInputRef"
            v-model="renameDialog.value"
            class="mindmap-rename-input"
            maxlength="40"
            :placeholder="renameDialog.isNew ? '输入节点名称' : ''"
            @keyup.enter="confirmRenameDialog"
          />
          <div class="mindmap-rename-actions">
            <button type="button" @click="cancelRenameDialog">取消</button>
            <button type="button" class="primary" @click="confirmRenameDialog">确定</button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.mindmap-root { display: flex; flex-direction: column; gap: 8px; }
.mindmap-root-fullscreen {
  position: fixed;
  inset: 16px;
  z-index: 60;
  padding: 10px;
  box-sizing: border-box;
  background: #fff;
  border-radius: 16px;
  box-shadow: 0 24px 60px rgba(15, 23, 42, 0.22);
}
.mindmap-root-fullscreen .flow-wrap {
  flex: 1;
  min-height: 0;
  height: auto;
}
.toolbar { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.toolbar button { border: 1px solid #d1d5db; background: #fff; border-radius: 6px; padding: 4px 10px; font-size: 12px; }
.toolbar .sep { width: 1px; background: #e5e7eb; margin: 0 2px; align-self: stretch; min-height: 20px; }
.toolbar-hint { font-size: 11px; color: #94a3b8; margin-left: 4px; }
.toolbar-layout-label { font-size: 12px; color: #64748b; margin-right: 2px; }
.toolbar-select {
  border: 1px solid #d1d5db;
  background: #fff;
  border-radius: 6px;
  padding: 4px 8px;
  font-size: 12px;
  color: #0f172a;
  max-width: 9rem;
}
.flow-wrap {
  height: 520px;
  border: 1px solid #e2e8f0;
  border-radius: 16px;
  overflow: hidden;
  background: #f8fafc;
}
/* 节点：文本框风（避免覆盖 inline style，否则导出会出现伪影） */
.flow-wrap :deep(.vue-flow__node) {
  transition: none !important;
}
.flow-wrap :deep(.vue-flow__node-default:focus),
.flow-wrap :deep(.vue-flow__node-default:focus-visible) {
  outline: none !important;
}
.flow-wrap :deep(.vue-flow__node-label) {
  display: inline-block;
  max-width: 240px;
  line-height: 1.5;
  word-break: break-word;
  border-bottom: none;
  padding-bottom: 0;
}
.flow-wrap :deep(.vue-flow__handle) {
  width: 8px !important;
  height: 8px !important;
  min-width: 8px !important;
  min-height: 8px !important;
  border: 1.5px solid var(--mm-edge, #94a3b8) !important;
  background: #fff !important;
  border-radius: 50%;
}
.flow-wrap :deep(.vue-flow__node.selected),
.flow-wrap :deep(.vue-flow__node:focus),
.flow-wrap :deep(.vue-flow__node:focus-visible),
.flow-wrap :deep(.vue-flow__node.dragging) {
  box-shadow: none !important;
  outline: none !important;
  opacity: 1 !important;
  filter: none !important;
}
/* 锁定边线颜色，避免 hover/selected/focus 发生视觉变色 */
.flow-wrap :deep(.vue-flow__edge),
.flow-wrap :deep(.vue-flow__edge:hover),
.flow-wrap :deep(.vue-flow__edge.selected),
.flow-wrap :deep(.vue-flow__edge:focus),
.flow-wrap :deep(.vue-flow__edge:focus-visible),
.flow-wrap :deep(.vue-flow__edge-path),
.flow-wrap :deep(.vue-flow__edge:hover .vue-flow__edge-path),
.flow-wrap :deep(.vue-flow__edge.selected .vue-flow__edge-path),
.flow-wrap :deep(.vue-flow__edge:focus .vue-flow__edge-path),
.flow-wrap :deep(.vue-flow__edge:focus-visible .vue-flow__edge-path) {
  transition: none !important;
  filter: none !important;
  opacity: 1 !important;
}
.flow-wrap :deep(.vue-flow__edge-path),
.flow-wrap :deep(.vue-flow__edge.selected .vue-flow__edge-path),
.flow-wrap :deep(.vue-flow__edge:hover .vue-flow__edge-path),
.flow-wrap :deep(.vue-flow__edge:focus .vue-flow__edge-path),
.flow-wrap :deep(.vue-flow__edge:focus-visible .vue-flow__edge-path) {
  stroke: var(--mm-edge) !important;
  fill: none !important;
}
.flow-wrap :deep(.vue-flow__edge-interaction) {
  stroke: transparent !important;
}
.mindmap-context-menu {
  display: flex;
  flex-direction: column;
  min-width: 140px;
  padding: 4px 0;
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  box-shadow: 0 10px 40px rgba(15, 23, 42, 0.15);
}
.mindmap-context-menu button {
  border: none;
  background: transparent;
  text-align: left;
  padding: 8px 14px;
  font-size: 13px;
  cursor: pointer;
}
.mindmap-context-menu button:hover:not(:disabled) { background: #f1f5f9; }
.mindmap-context-menu button:disabled { opacity: 0.45; cursor: not-allowed; }
.mindmap-context-menu button.danger { color: #b91c1c; }
.mindmap-rename-overlay {
  position: fixed;
  inset: 0;
  z-index: 85;
  background: rgba(15, 23, 42, 0.35);
  display: flex;
  align-items: center;
  justify-content: center;
}
.mindmap-rename-box {
  background: #fff;
  border-radius: 12px;
  padding: 16px 18px;
  min-width: 280px;
  box-shadow: 0 20px 50px rgba(15, 23, 42, 0.2);
}
.mindmap-rename-title { font-size: 14px; font-weight: 600; margin-bottom: 10px; color: #0f172a; }
.mindmap-rename-input {
  width: 100%;
  box-sizing: border-box;
  padding: 8px 10px;
  border: 1px solid #d1d5db;
  border-radius: 8px;
  font-size: 14px;
}
.mindmap-rename-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 14px; }
.mindmap-rename-actions button {
  padding: 6px 14px;
  border-radius: 6px;
  border: 1px solid #d1d5db;
  background: #fff;
  font-size: 13px;
  cursor: pointer;
}
.mindmap-rename-actions button.primary { background: #0f172a; color: #fff; border-color: #0f172a; }
</style>

