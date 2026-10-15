// 관리 API 응답 모양 — backend app/api/admin*.py (설계도 §14.3)

export interface AdminSummary {
  viewer: { member_id: number; is_admin: boolean };
  boards: { id: number; slug: string; name: string }[];
  badges: { reports: number; pending: number; today_posts: number; dead_jobs: number | null };
}

export interface ModerationLogItem {
  id: number;
  actor: { id: number | null; name: string | null };
  board: { id: number; slug: string | null } | null;
  action: string;
  target: { type: string; id: number };
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  reason: string | null;
  created_at: string;
  redacted: boolean;
}

export interface Page<T> {
  items: T[];
  next_cursor: number | string | null;
}
