import { Spin } from "antd";

type AdminPageLoadingProps = {
  minHeightClassName?: string;
};

/** 页面/标签页级加载态：与 modo-page-card 同构的白卡，
 *  避免加载瞬间内容区裸透明导致灰底露出 */
export function AdminPageLoading({
  minHeightClassName = "min-h-[240px]",
}: AdminPageLoadingProps) {
  return (
    <div className={`modo-page-card flex ${minHeightClassName} items-center justify-center`}>
      <Spin />
    </div>
  );
}
