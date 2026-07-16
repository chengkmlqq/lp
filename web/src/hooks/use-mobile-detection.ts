import { useEffect, useState } from "react";
import { Grid } from "antd";

export function useMobileDetection() {
  const screens = Grid.useBreakpoint();
  const [isMobile, setIsMobile] = useState(false);

  useEffect(() => {
    // Consider mobile if screen width is below md breakpoint (768px in Ant Design)
    setIsMobile(screens.md === false);
  }, [screens.md]);

  return isMobile;
}
