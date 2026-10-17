import { AccountNav } from "@/components/auth/AccountNav";

// 쿠키 유무만 보는 기존 부품 — FastAPI 를 부르지 않는다(화면당 호출 예산). 요청 시점이라 부르는 쪽이 <Suspense> 안에 둔다
export function AccountBlock() {
  return (
    <div data-slot="account">
      <AccountNav />
    </div>
  );
}
