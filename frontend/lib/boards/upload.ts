// 첨부 올리기 한 곳 — 첨부 패널과 리치 에디터(사진 단추·끌어 놓기·붙여넣기)가 같이 쓴다.
// Route Handler /api/uploads 로 본문을 그대로 보낸다(출처 검사·내부 비밀은 그쪽이 맡는다, §11).

export interface UploadedAttachment {
  id: number;
  name: string;
  is_image: boolean;
}

interface UploadResponse {
  attachment?: UploadedAttachment;
  title?: string;
  errors?: { message: string }[];
}

export type UploadResult = { ok: true; attachment: UploadedAttachment } | { ok: false; message: string };

export async function uploadAttachment(boardSlug: string, file: File): Promise<UploadResult> {
  try {
    const res = await fetch(`/api/uploads?board=${encodeURIComponent(boardSlug)}`, {
      method: "POST",
      body: file,
      headers: {
        "content-type": file.type || "application/octet-stream",
        "x-upload-filename": encodeURIComponent(file.name),
        "idempotency-key": crypto.randomUUID(),
      },
    });
    const body = (await res.json()) as UploadResponse;
    if (res.ok && body.attachment) return { ok: true, attachment: body.attachment };
    return { ok: false, message: body.errors?.[0]?.message ?? body.title ?? "올리지 못했습니다" };
  } catch {
    return { ok: false, message: "올리지 못했습니다(연결 오류)" };
  }
}
