/**
 * 输电铁塔图标（自绘 SVG）。
 *
 * Ant Design 图标库里没有电力杆塔类的图标——ApartmentOutlined 是公寓楼，
 * ThunderboltOutlined 只剩一道闪电，都撑不起「ATP 模型 = 杆塔 + 几何」这个语义。
 * 这里按 24 格栅格手绘一基格构塔：塔身两腿 + 三层横担 + 层间斜撑 + 塔脚，
 * 线条用 currentColor，颜色跟随电压分档色块。
 */
export function AtpTowerIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      className={className}
      width="1em"
      height="1em"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.7}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
      focusable="false"
    >
      <path d="M12 2.6 7.4 21" />
      <path d="M12 2.6 16.6 21" />
      <path d="M3.8 8h16.4" />
      <path d="M5.6 12.6h12.8" />
      <path d="M7.2 17.2h9.6" />
      <path d="M9.7 8 14.3 12.6M14.3 8 9.7 12.6" strokeWidth={1.1} />
      <path d="M6.2 21h2.6M15.2 21h2.6" />
    </svg>
  );
}
