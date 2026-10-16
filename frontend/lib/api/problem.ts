// FastAPI 오류(RFC 9457 problem+json) — 화면·Server Action 이 같은 모양으로 다룬다

export interface ProblemBody {
  type?: string;
  title: string;
  status: number;
  code: string;
  detail?: string;
  errors?: { field: string; message: string }[];
}

export class ApiError extends Error {
  readonly status: number;
  readonly problem: ProblemBody;

  constructor(problem: ProblemBody) {
    super(problem.title);
    this.name = "ApiError";
    this.status = problem.status;
    this.problem = problem;
  }
}

export async function readJson<T>(res: Response): Promise<T> {
  if (res.status === 204) return undefined as T; // 본문 없음(로그아웃 등)
  if (res.ok) return (await res.json()) as T;
  const type = res.headers.get("content-type") ?? "";
  if (type.includes("json")) throw new ApiError((await res.json()) as ProblemBody);
  throw new ApiError({ title: res.statusText || "오류", status: res.status, code: `http_${res.status}` });
}
