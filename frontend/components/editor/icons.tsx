/**
 * RichTextEditor 전용 단색 아이콘 세트 — 24 그리드, stroke 1.8, round cap.
 *
 * [불변량 2] 순수 prop 컴포넌트. currentColor 를 상속해 버튼 색을 따른다.
 * 이식 시 따라오는 의존성: 없음(순수 SVG).
 */

import type { SVGProps } from "react";

type IconProps = SVGProps<SVGSVGElement> & { size?: number };

function Svg({ size = 20, children, ...rest }: IconProps & { children: React.ReactNode }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...rest}
    >
      {children}
    </svg>
  );
}

export const Icon = {
  undo: (p: IconProps) => (
    <Svg {...p}>
      <path d="M8 8 4 12l4 4" />
      <path d="M4 12h10a4.5 4.5 0 0 1 0 9h-2" />
    </Svg>
  ),
  redo: (p: IconProps) => (
    <Svg {...p}>
      <path d="M16 8l4 4-4 4" />
      <path d="M20 12H10a4.5 4.5 0 0 0 0 9h2" />
    </Svg>
  ),
  bold: (p: IconProps) => (
    <Svg {...p} strokeWidth={2.1}>
      <path d="M7 5h6.2a3.4 3.4 0 0 1 0 6.8H7z" />
      <path d="M7 11.8h7a3.6 3.6 0 0 1 0 7.2H7z" />
    </Svg>
  ),
  italic: (p: IconProps) => (
    <Svg {...p}>
      <path d="M14.5 5h-4" />
      <path d="M13.5 5 10 19" />
      <path d="M14 19h-4" />
    </Svg>
  ),
  underline: (p: IconProps) => (
    <Svg {...p}>
      <path d="M7 5v5.5a5 5 0 0 0 10 0V5" />
      <path d="M5.5 20h13" />
    </Svg>
  ),
  strike: (p: IconProps) => (
    <Svg {...p}>
      <path d="M5 12.4h14" />
      <path d="M8.4 8.6c.2-1.7 1.8-2.6 3.8-2.6 1.7 0 3 .6 3.5 1.7" />
      <path d="M15.4 15.2c-.1 1.8-1.7 2.8-3.8 2.8-1.9 0-3.4-.8-3.8-2.3" />
    </Svg>
  ),
  sup: (p: IconProps) => (
    <Svg {...p}>
      <path d="M4 7l8 11M12 7 4 18" />
      <path d="M17 5.3c0-1 1.4-1.3 2.1-.8.8.5.5 1.5-.1 2L17 8.5h3.2" />
    </Svg>
  ),
  sub: (p: IconProps) => (
    <Svg {...p}>
      <path d="M4 6l8 11M12 6 4 17" />
      <path d="M17 16.3c0-1 1.4-1.3 2.1-.8.8.5.5 1.5-.1 2L17 19.5h3.2" />
    </Svg>
  ),
  code: (p: IconProps) => (
    <Svg {...p}>
      <path d="M9.5 8 5.5 12l4 4" />
      <path d="M14.5 8l4 4-4 4" />
    </Svg>
  ),
  clear: (p: IconProps) => (
    <Svg {...p}>
      <path d="M6 7V5.5h12V7" />
      <path d="M11 5.6 9.4 14" />
      <path d="m14.5 14.5 5 5M19.5 14.5l-5 5" />
    </Svg>
  ),
  highlight: (p: IconProps) => (
    <Svg {...p}>
      <path d="M5 19h6" />
      <path d="m8 16-2.5.7.8-2.6 7-7 1.8 1.8z" />
      <path d="m14.3 8.9 1.8 1.8" />
    </Svg>
  ),
  bullet: (p: IconProps) => (
    <Svg {...p}>
      <circle cx="5" cy="7" r="1.3" fill="currentColor" stroke="none" />
      <circle cx="5" cy="12" r="1.3" fill="currentColor" stroke="none" />
      <circle cx="5" cy="17" r="1.3" fill="currentColor" stroke="none" />
      <path d="M10 7h10M10 12h10M10 17h10" />
    </Svg>
  ),
  numbered: (p: IconProps) => (
    <Svg {...p}>
      <path d="M10 7h10M10 12h10M10 17h10" />
      <path d="M4.4 5.6 5.6 5v4" />
      <path d="M4.2 16.2c0-.9 2-.9 2 .1s-2 1.4-2 2.6h2.2" />
    </Svg>
  ),
  check: (p: IconProps) => (
    <Svg {...p}>
      <rect x="3.3" y="5" width="5.4" height="5.4" rx="1.6" />
      <path d="m4.6 7.6 1 1 1.5-1.7" />
      <rect x="3.3" y="14" width="5.4" height="5.4" rx="1.6" />
      <path d="M11.5 7.7h9M11.5 16.7h9" />
    </Svg>
  ),
  alignLeft: (p: IconProps) => (
    <Svg {...p}>
      <path d="M4 6.5h16M4 12h10M4 17.5h13" />
    </Svg>
  ),
  alignCenter: (p: IconProps) => (
    <Svg {...p}>
      <path d="M4 6.5h16M7 12h10M5.5 17.5h13" />
    </Svg>
  ),
  alignRight: (p: IconProps) => (
    <Svg {...p}>
      <path d="M4 6.5h16M10 12h10M7 17.5h13" />
    </Svg>
  ),
  justify: (p: IconProps) => (
    <Svg {...p}>
      <path d="M4 6.5h16M4 12h16M4 17.5h16" />
    </Svg>
  ),
  indent: (p: IconProps) => (
    <Svg {...p}>
      <path d="M4 6.5h16M11 12h9M11 17.5h9" />
      <path d="M4 9.3l4 2.7-4 2.7z" fill="currentColor" stroke="none" />
    </Svg>
  ),
  outdent: (p: IconProps) => (
    <Svg {...p}>
      <path d="M4 6.5h16M11 12h9M11 17.5h9" />
      <path d="M8 9.3l-4 2.7 4 2.7z" fill="currentColor" stroke="none" />
    </Svg>
  ),
  link: (p: IconProps) => (
    <Svg {...p}>
      <path d="M10.5 13.5a3.6 3.6 0 0 0 5.1 0l2-2a3.6 3.6 0 0 0-5.1-5.1l-1 1" />
      <path d="M13.5 10.5a3.6 3.6 0 0 0-5.1 0l-2 2a3.6 3.6 0 0 0 5.1 5.1l1-1" />
    </Svg>
  ),
  codeBlock: (p: IconProps) => (
    <Svg {...p}>
      <rect x="3.5" y="5" width="17" height="14" rx="2.5" />
      <path d="M9.5 9.5 7 12l2.5 2.5M14.5 9.5 17 12l-2.5 2.5" />
    </Svg>
  ),
  image: (p: IconProps) => (
    <Svg {...p}>
      <rect x="3.5" y="5" width="17" height="14" rx="2.5" />
      <circle cx="8.5" cy="9.5" r="1.4" />
      <path d="m4.5 17 4.2-3.6 3 2.2 3.6-3.4 4.2 3.8" />
    </Svg>
  ),
  divider: (p: IconProps) => (
    <Svg {...p}>
      <path d="M5 8h14" />
      <path d="M4 12h16" />
      <path d="M5 16h9" />
    </Svg>
  ),
  table: (p: IconProps) => (
    <Svg {...p}>
      <rect x="3.5" y="5" width="17" height="14" rx="2" />
      <path d="M3.5 10.5h17M3.5 15h17M9.5 5v14M15 5v14" />
    </Svg>
  ),
  header: (p: IconProps) => (
    <Svg {...p}>
      <rect x="3.5" y="5" width="17" height="14" rx="2" />
      <path d="M4.5 5.6h15v4.4h-15z" fill="currentColor" stroke="none" />
      <path d="M3.5 10h17M9.5 10v9M15 10v9" />
    </Svg>
  ),
  wrap: (p: IconProps) => (
    <Svg {...p}>
      <rect x="13.5" y="6" width="6.5" height="6.5" rx="1.3" />
      <path d="M4 7h7M4 11h7M4 15h16M4 19h16" />
    </Svg>
  ),
  caret: (p: IconProps) => (
    <Svg {...p} size={p.size ?? 14} strokeWidth={2.2}>
      <path d="m6 9 6 6 6-6" />
    </Svg>
  ),
  more: (p: IconProps) => (
    <Svg {...p} fill="currentColor" stroke="none">
      <circle cx="5" cy="12" r="1.7" />
      <circle cx="12" cy="12" r="1.7" />
      <circle cx="19" cy="12" r="1.7" />
    </Svg>
  ),
  trash: (p: IconProps) => (
    <Svg {...p}>
      <path d="M5 7h14M9 7V5.5h6V7M6.5 7l.7 12h9.6l.7-12" />
    </Svg>
  ),
  expand: (p: IconProps) => (
    <Svg {...p}>
      <path d="M9 4.5H4.5V9M15 4.5h4.5V9M9 19.5H4.5V15M15 19.5h4.5V15" />
    </Svg>
  ),
  compress: (p: IconProps) => (
    <Svg {...p}>
      <path d="M4.5 8.5H9V4M19.5 8.5H15V4M4.5 15.5H9V20M19.5 15.5H15V20" />
    </Svg>
  ),
};

export type IconName = keyof typeof Icon;
