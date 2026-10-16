import Link from "next/link";
import { DynamicMarker } from "@/components/DynamicMarker";

// 처음 화면 — 정적. 빌드 때 FastAPI 를 부르지 않는다(사이트 메타만 요청 시점 — DynamicMarker)
export default function Home() {
  return (
    <>
      <h1>mypage</h1>
      <ul>
        <li>
          <Link href="/boards/notice">공지</Link>
        </li>
        <li>
          <Link href="/boards/free">자유게시판</Link>
        </li>
      </ul>
      <DynamicMarker />
    </>
  );
}
