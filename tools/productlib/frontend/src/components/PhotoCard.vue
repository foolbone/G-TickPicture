<template>
  <div class="shot" :data-id="photo.id"
       :class="{ inval: photo.is_invalid, 'sel-on': selected, compact }"
       @click="$emit('click', photo.id)">
    <img loading="lazy" :src="photo.thumb" :alt="photo.file" />
    <span class="badge" :class="kindCls(photo.photo_kind || 'unknown')"
          :title="'分类：' + kindName(photo.photo_kind)">{{ kindName(photo.photo_kind) }}</span>
    <span v-if="photo.is_invalid" class="badge invalb"
          title="已标记无效：默认不出现在列表/候选/选图等工作队列">无效</span>
    <span v-for="t in flagBadges" :key="t"
          class="fbadge" :class="t === 'cand' ? 'cand' : 'newp'"
          :title="t === 'cand' ? FLAG_TIP.cand : FLAG_TIP.newprod">{{ t === 'cand' ? '待确认' : '新产品' }}</span>
    <div v-if="codes.length" class="codes">
      编码：<b v-for="(c, i) in codes.slice(0, 3)" :key="i">{{ c }}</b>
      <span v-if="codes.length > 3"> +{{ codes.length - 3 }}</span>
    </div>
    <!-- 紧凑模式下 hover 才浮出：文件名 / 时间 / 大小 -->
    <div class="hinfo">
      <b>{{ photo.file }}</b>
      <i>{{ metaLine(photo) }}</i>
    </div>
    <div class="meta" :title="photo.file">{{ photo.file }}</div>
    <div class="meta faint">{{ metaLine(photo) }}</div>
  </div>
</template>

<script setup>
/* PhotoCard.vue —— 一张照片卡片（对应旧版 photos.js shotCard）
 *
 * ⚠️ 「待确认 / 新产品」角标**不在这里算**：那两个集合要全库模糊匹配 + OCR 聚合，
 * 冷缓存实测 6.6 秒（2738 张）。挂在列表主查询上会把首屏从 0.3s 拖成 6.6s。
 * 由父级在渲染后异步调 /api/photo-flags 补 flagBadges（没到之前不显示，
 * 不是显示 0；两次都没算完就放弃 —— 不显示 ≠ 没有）。 */
import { computed } from 'vue'
import { kindCls, kindName, fmtTaken, fmtGap, diffSec, jparse } from '../lib/core.js'

const FLAG_TIP = {
  cand: '读出了像产品库里某个编码，但还没关联 —— 需要你判断要不要关联',
  newprod: '读出的编码产品库里没有 —— 需要你确认是不是新产品并入库',
}

const props = defineProps({
  photo: { type: Object, required: true },
  selected: { type: Boolean, default: false },
  flags: { type: Array, default: () => [] },   // ['cand'|'newprod']
  prevTaken: { type: String, default: '' },    // 传入则多显示「与上一张间隔」
  compact: { type: Boolean, default: false },  // 紧凑视图：隐藏常显信息，hover 才浮出
})
defineEmits(['click'])

const codes = computed(() => jparse(props.photo.vision_codes, []))

function metaLine(p) {
  const tail = p.govern_state !== 'done'
    ? ' · ' + p.govern_state : ''
  const gap = props.prevTaken ? fmtGap(diffSec(props.prevTaken, p.taken_at)) : ''
  return fmtTaken(p.taken_at)
    + (gap ? ' · ' + gap : '')
    + ' · ' + p.size_mb + 'MB'
    + (p.nlink ? ' · 关联 ' + p.nlink : '')
    + tail
}
</script>

<style scoped>
/* 卡片样式对齐旧版 app.css（.shot 系列）：角标压在图上、紧凑模式 hover 浮出信息 */
.shot {
  position: relative; cursor: pointer; overflow: hidden;
  border: 1px solid var(--el-border-color-light); border-radius: 8px;
  background: var(--el-bg-color);
}
.shot img {
  width: 100%; height: 160px; object-fit: cover; display: block;
  background: var(--el-fill-color);
}
.shot .meta {
  padding: 6px 8px; font-size: 11px; color: var(--el-text-color-secondary);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.shot .badge {
  position: absolute; left: 6px; top: 6px; color: #fff;
  font-size: 10px; padding: 1px 6px; border-radius: 4px;
  background: rgba(0, 0, 0, .6);
}
.shot .badge.invalb { background: var(--el-color-info); left: auto; right: 6px; }
/* 分类色（与旧版一致，只调色不改文案口径） */
.shot .badge.k-label { background: rgba(21, 128, 61, .92); }
.shot .badge.k-product { background: rgba(29, 78, 216, .92); }
.shot .badge.k-packaging { background: rgba(180, 83, 9, .92); }
.shot .badge.k-packing_list { background: rgba(126, 34, 206, .92); }
.shot .badge.k-scene { background: rgba(15, 118, 110, .92); }
.shot .badge.k-unknown { background: rgba(100, 112, 132, .92); }
/* 无效照片：整卡降透明 + 去色 —— 一眼看出「不在工作队列里」 */
.shot.inval { opacity: .45; }
.shot.inval img { filter: grayscale(.7); }
/* 选择模式：描边 + 左上角勾角 */
.shot.sel-on { outline: 2px solid var(--el-color-primary); outline-offset: -2px; }
.shot.sel-on::after {
  content: '✓'; position: absolute; left: 6px; top: 6px; z-index: 3;
  width: 20px; height: 20px; border-radius: 50%;
  background: var(--el-color-primary); color: #fff;
  font-size: 13px; line-height: 20px; text-align: center;
}
/* 编码条：图底部半透深底，编码用等宽高亮 */
.shot .codes {
  position: absolute; left: 0; right: 0; bottom: 0;
  background: rgba(15, 18, 22, .74); color: #fff; font-size: 10px;
  padding: 2px 6px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.shot .codes b { color: #ffd479; font-family: ui-monospace, Consolas, monospace; }
/* 紧凑模式：默认只留缩略图 + 分类角标 */
.shot.compact img { height: 96px; }
.shot.compact .meta, .shot.compact .codes { display: none; }
.shot.compact .badge { font-size: 9px; padding: 0 4px; left: 4px; top: 4px; }
/* 悬停浮层（紧凑模式才显示，浮出文件名/时间/大小） */
.shot .hinfo { display: none; }
.shot:hover .hinfo, .shot.compact:hover .hinfo {
  display: block; position: absolute; left: 0; right: 0; bottom: 0;
  padding: 14px 7px 6px; pointer-events: none; z-index: 2;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0), rgba(255, 255, 255, .97) 40%);
  font-size: 11px; line-height: 1.45;
}
.shot .hinfo b { display: block; font-weight: 600; font-size: 11px; word-break: break-all; }
.shot .hinfo i { font-style: normal; color: var(--el-text-color-secondary); font-size: 10px; }
/* 「待确认 / 新产品」角标放右上：分类角标在左上，两个叠一起就都看不清 */
.fbadge {
  position: absolute; right: 6px; top: 6px; z-index: 2;
  font-size: 10px; font-weight: 700; padding: 1px 6px;
  border-radius: 4px; pointer-events: none;
}
.fbadge.cand { background: var(--el-color-warning); color: #fff; }
.fbadge.newp { background: var(--el-color-primary); color: #fff; }
</style>
