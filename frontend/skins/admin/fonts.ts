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
  // 2,057,688 바이트 — 미리 싣기(preload)를 끈다: 관리 화면 첫 진입마다 다른 자원보다 먼저 2MB 를 받지 않게(코드 검토 v1 N-2).
  // display:swap 이라 그동안은 대체 글꼴로 그린다. 한글 부분 글꼴(unicode-range 나눔) 여부는 측정으로 정한다(관리디자인 지시서 §8)
  preload: false,
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-jetbrains",
  display: "swap",
});

/** CSS 변수(--font-pretendard·--font-jetbrains)를 만드는 생성 class — 관리 화면 맨 바깥 요소 하나에만 붙인다 */
export const adminFontVariables = `${pretendard.variable} ${jetbrainsMono.variable}`;
