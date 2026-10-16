import type { ReactNode } from "react";
import { Frame } from "@/components/blocks/Frame";

// 화면 종류 'default' 의 틀(홈블록 설계도 §3.3·§5.1)
export default function Layout({ children }: { children: ReactNode }) {
  return <Frame routeClass="default">{children}</Frame>;
}
