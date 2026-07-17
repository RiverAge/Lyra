/**
 * 数字滚动动画——目标值变化时，从当前显示值缓动到新值。
 *
 * 用途：统计卡数字在扫描完成（或数据刷新）时，像股票行情那样从旧值
 * 滚动到新值，而非直接跳变；视觉上与进度条收尾连贯。
 *
 * 缓动：ease-out（先快后慢），符合「数字跳动」的实时感。
 * 时长固定 ~600ms——足够看到跳动，又不拖沓。
 *
 * @param target 目标值 ref/getter（动画终点）
 * @returns display ref（当前动画中的数值，整数）
 */
export function useCountUp(target: () => number) {
  const display = ref(target())
  let raf = 0
  let from = display.value
  let to = display.value
  let startTime = 0
  const DURATION = 600

  function easeOut(t: number): number {
    return 1 - Math.pow(1 - t, 3) // easeOutCubic
  }

  function tick(now: number): void {
    if (startTime === 0) startTime = now
    const t = Math.min(1, (now - startTime) / DURATION)
    const v = from + (to - from) * easeOut(t)
    display.value = Math.round(v)
    if (t < 1) {
      raf = requestAnimationFrame(tick)
    } else {
      display.value = to
      raf = 0
    }
  }

  watch(
    target,
    (next) => {
      if (next === to) return
      if (raf) cancelAnimationFrame(raf)
      from = display.value
      to = next
      startTime = 0
      // 相同或差值为 0 不动画（首屏 / 无变化）
      if (from === to) {
        display.value = to
        return
      }
      raf = requestAnimationFrame(tick)
    },
    { immediate: false },
  )

  onUnmounted(() => {
    if (raf) cancelAnimationFrame(raf)
  })

  return display
}
