import { JetBrains_Mono } from "next/font/google";
import localFont from "next/font/local";

// 관리 화면 글꼴(관리디자인 지시서 §2.1) — Next 공식 방식 next/font. 관리 레이아웃만 불러 관리 화면에서만 내려받는다.
// 본문: Pretendard 가변(pretendard@1.3.9 의 dist/web/variable/woff2, OFL — fonts/Pretendard-LICENSE.txt)
// 고정폭: JetBrains Mono(Google Fonts, 빌드 때 받아 자체 제공). 표시용 OkDanDan 은 라이선스 확인 전이라 넣지 않는다(§8)
const pretendard = localFont({
  src: "./fonts/PretendardVariable.woff2",
  variable: "--font-pretendard",
  weight: "100 900",
  display: "swap",
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-jetbrains",
  display: "swap",
});

/** CSS 변수(--font-pretendard·--font-jetbrains)를 만드는 생성 class — 관리 화면 맨 바깥 요소 하나에만 붙인다 */
export const adminFontVariables = `${pretendard.variable} ${jetbrainsMono.variable}`;
