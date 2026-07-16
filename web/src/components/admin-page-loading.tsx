import { Spin } from "antd";

type AdminPageLoadingProps = {
  tip: string;
  minHeightClassName?: string;
};

export function AdminPageLoading({
  tip,
  minHeightClassName = "min-h-[240px]",
}: AdminPageLoadingProps) {
  return (
    <div className={`flex ${minHeightClassName} items-center justify-center`}>
      <Spin tip={tip} />
    </div>
  );
}
