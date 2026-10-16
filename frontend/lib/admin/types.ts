// 관리 API 응답 모양 — backend app/api/admin*.py (설계도 §14.3)

export interface AdminSummary {
  viewer: { member_id: number; is_admin: boolean };
  boards: { id: number; slug: string; name: string }[];
  badges: {
    reports: number;
    pending: number;
    today_posts: number;
    dead_jobs: number | null;
    signups: number | null;
    level_requests: number | null;
    alerts: number | null;
  };
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

export interface AdminBoardRow {
  id: number;
  slug: string;
  name: string;
  kind: string;
  editor: string;
  is_active: boolean;
  is_system: boolean;
  show_in_menu: boolean;
  sort_order: number;
  group: { id: number; name: string } | null;
  posts: number;
  last_post_at: string | null;
  pending: number;
  reports: number;
}

export interface AdminBoards {
  boards: AdminBoardRow[];
  groups: { id: number; name: string; sort_order: number }[];
  templates: { name: string; label: string }[];
}

export interface AdminBoardDetail {
  board: Record<string, unknown> & { id: number; slug: string; name: string; is_system: boolean };
  categories: { id: number; name: string; is_active: boolean; sort_order: number; posts: number }[];
  entries: { subject_type: "member" | "group"; subject_id: number; can_read: boolean; can_write: boolean }[];
  moderators: { id: number; name: string }[];
}

export interface PermissionPreview {
  subject: { member_id: number | null; level: number; is_admin: boolean };
  role: { is_moderator: boolean; listed_read: boolean; listed_write: boolean; sanctions: string[] };
  site_sanctions: string[];
  actions: { action: string; label: string; allowed: boolean }[];
}

export interface AdminPostRow {
  id: number;
  title: string;
  status: string;
  board: { id: number; slug: string; name: string };
  author: { id: number | null; name: string; guest: boolean };
  published_at: string | null;
  created_at: string;
  flags: { pinned: boolean; pin_order: number | null; secret: boolean; blinded: boolean; min_view_level: number | null; posted_as: string };
  comments: number;
  views: number;
  reports: number;
  trash: { trashed_at: string; from: string | null; purge_at: string | null } | null;
}

export interface ReportGroup {
  report_id: number;
  board_id: number | null;
  count: number;
  first_at: string;
  reasons: string[];
  texts: string[];
  target: {
    type: "post" | "comment";
    id: number;
    exists: boolean;
    author?: { id: number | null; name: string };
    blinded?: boolean;
    status?: string;
    board_slug?: string;
    post_id?: number;
    title?: string;
  };
}

export interface AdminCommentRow {
  id: number;
  post: { id: number; title: string };
  board: { slug: string; name: string };
  author: { id: number | null; name: string };
  content: string;
  blinded: boolean;
  blind_source: string | null;
  created_at: string;
}
