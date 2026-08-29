import { Spin } from "antd";

type AdminPageLoadingProps = {
  minHeightClassName?: string;
};

export function AdminPageLoading({
  minHeightClassName = "min-h-[240px]",
}: AdminPageLoadingProps) {
  return (
    <div className={`flex ${minHeightClassName} items-center justify-center`}>
      <Spin />
    </div>
  );
}
