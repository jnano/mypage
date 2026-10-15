import Link from "next/link";

// 처음 화면 — 정적. 빌드 때 FastAPI 를 부르지 않는다
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
    </>
  );
}
