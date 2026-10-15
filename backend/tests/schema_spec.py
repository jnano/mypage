"""설계도 §4(v3.0.1) 를 옮겨 적은 스키마 명세 — test_schema_contract.py 의 대조 기준.

설계도 §4 를 바꾸면 이 파일도 같이 바꾼다. 모델에서 베껴 오지 않는다(설계도에서 옮긴다).

칸 표기: "이름 형 [null] [=기본값] [identity] [in(값,…)] [range(하한[,상한])]"
  - null 이 없으면 NOT NULL(§4 R1)
  - in(…)    → CHECK "{칸}_enum"  : 칸 IN (…)
  - range(…) → CHECK "{칸}_range" : 칸 BETWEEN 하한 AND 상한 / 칸 >= 하한
fks:     {칸: "참조표 ON DELETE 동작"}
checks:  {이름: SQL} — in/range 로 표기하지 않은 CHECK
uniques: [(칸, …)]
indexes: {이름: "칸, … [| where 조건] [| using 방식] [| include 칸, …] [| unique]"}
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class T:
    cols: list[str]
    pk: tuple[str, ...] = ("id",)
    fks: dict[str, str] = field(default_factory=dict)
    checks: dict[str, str] = field(default_factory=dict)
    uniques: list[tuple[str, ...]] = field(default_factory=list)
    indexes: dict[str, str] = field(default_factory=dict)
    unlogged: bool = False


ID = "id bigint identity"
CREATED = "created_at timestamptz =now()"
UPDATED = "updated_at timestamptz =now()"
LV = "range(0,99)"

SPEC: dict[str, T] = {
    # ── §4.1 회원·설정 ─────────────────────────────────────
    "members": T(
        cols=[
            ID,
            "display_name varchar(50)",
            "level smallint =1 range(1,99)",
            "is_admin boolean =false",
            "status varchar(10) ='active' in(active,withdrawn)",
            "withdrawn_at timestamptz null",
            CREATED,
            UPDATED,
        ],
        checks={"withdrawn": "(status = 'withdrawn') = (withdrawn_at IS NOT NULL)"},
    ),
    "member_groups": T(
        cols=[ID, "name varchar(50)", "description text null", CREATED],
        uniques=[("name",)],
    ),
    "member_group_members": T(
        cols=["group_id bigint", "member_id bigint"],
        pk=("group_id", "member_id"),
        fks={"group_id": "member_groups CASCADE", "member_id": "members CASCADE"},
    ),
    "site_settings": T(
        cols=["key varchar(40)", "value jsonb", UPDATED, "updated_by bigint null"],
        pk=("key",),
        fks={"updated_by": "members SET NULL"},
    ),
    # ── §4.2 게시판 ────────────────────────────────────────
    "board_groups": T(cols=[ID, "name varchar(50)", "sort_order integer =0", CREATED]),
    "boards": T(
        cols=[
            ID,
            "slug varchar(100)",
            "name varchar(100)",
            "description text null",
            "kind varchar(10) ='default' in(default,gallery,line)",
            "group_id bigint null",
            "sort_order integer =0",
            "is_active boolean =true",
            "is_system boolean =false",
            "show_in_menu boolean =true",
            f"list_level smallint =0 {LV}",
            f"read_level smallint =0 {LV}",
            f"write_level smallint =1 {LV}",
            f"comment_level smallint =1 {LV}",
            f"upload_level smallint =1 {LV}",
            f"download_level smallint =0 {LV}",
            "allow_level_lowering boolean =false",
            "hidden_post_listing varchar(8) ='mask' in(mask,hide)",
            "pinned_display varchar(8) ='strip' in(strip,inline)",
            "allow_secret boolean =false",
            "allow_comments boolean =true",
            "allow_share boolean =true",
            "allow_title_style boolean =false",
            "protect_commented_posts boolean =false",
            "view_count_mode varchar(8) ='daily' in(always,daily,once)",
            "posts_per_page smallint =20 range(5,100)",
            "editor varchar(10) ='rich' in(rich,markdown)",
            "upload_policy jsonb",
            "spam_policy jsonb null",
            "report_auto_blind_threshold smallint null range(1)",
            "indexable boolean =true",
            "exclude_from_search boolean =false",
            "trash_retention_days smallint null range(1)",
            "display jsonb",
            CREATED,
            UPDATED,
        ],
        fks={"group_id": "board_groups SET NULL"},
        uniques=[("slug",)],
    ),
    "board_categories": T(
        cols=[
            ID,
            "board_id bigint",
            "name varchar(50)",
            "sort_order integer =0",
            "is_active boolean =true",
        ],
        fks={"board_id": "boards CASCADE"},
        uniques=[("board_id", "name")],
    ),
    "board_access": T(
        cols=[
            "board_id bigint",
            "subject_type varchar(6) in(member,group)",
            "subject_id bigint",
            "can_read boolean =false",
            "can_write boolean =false",
        ],
        pk=("board_id", "subject_type", "subject_id"),
        fks={"board_id": "boards CASCADE"},
        checks={"grants_something": "can_read OR can_write"},
    ),
    "board_moderators": T(
        cols=["board_id bigint", "member_id bigint"],
        pk=("board_id", "member_id"),
        fks={"board_id": "boards CASCADE", "member_id": "members CASCADE"},
    ),
    "board_slug_history": T(
        cols=["old_slug varchar(100)", "board_id bigint", "changed_at timestamptz =now()"],
        pk=("old_slug",),
        fks={"board_id": "boards CASCADE"},
    ),
    "board_subscriptions": T(
        cols=["board_id bigint", "member_id bigint", CREATED],
        pk=("board_id", "member_id"),
        fks={"board_id": "boards CASCADE", "member_id": "members CASCADE"},
    ),
    "board_daily_stats": T(
        cols=[
            "board_id bigint",
            "day date",
            "posts integer =0",
            "comments integer =0",
            "views integer =0",
            "reports integer =0",
        ],
        pk=("board_id", "day"),
        fks={"board_id": "boards CASCADE"},
    ),
    # ── §4.3 글 ────────────────────────────────────────────
    "posts": T(
        cols=[
            ID,
            "board_id bigint",
            "member_id bigint null",
            "is_guest boolean =false",
            "author_name_snapshot varchar(50)",
            "guest_password_hash varchar(255) null",
            "ip_hash varchar(64) null",
            "ip_hash_period integer null",
            "title varchar(300)",
            "title_bold boolean =false",
            "title_color varchar(10) null",
            "content_format varchar(10) in(rich,markdown)",
            "content_source text null",
            "content_html text",
            "content_rendered text",
            "sanitizer_version smallint",
            "status varchar(10) in(draft,scheduled,pending,published,trashed)",
            "trashed_from_status varchar(10) null in(draft,scheduled,pending,published)",
            "trashed_at timestamptz null",
            "published_at timestamptz null",
            "expires_at timestamptz null",
            "is_pinned boolean =false",
            "pin_order smallint null",
            "is_secret boolean =false",
            "is_blinded boolean =false",
            "blind_source varchar(12) null in(manual,auto_report)",
            "min_view_level smallint null range(0,99)",
            "posted_as varchar(10) ='personal' in(personal,admin)",
            "meta jsonb null",
            "version integer =1",
            "content_updated_at timestamptz null",
            CREATED,
            UPDATED,
        ],
        fks={"board_id": "boards RESTRICT", "member_id": "members SET NULL"},
        checks={
            "guest_author": "(is_guest AND guest_password_hash IS NOT NULL AND member_id IS NULL)"
            " OR (NOT is_guest AND guest_password_hash IS NULL)",
            "trashed_at": "(status = 'trashed') = (trashed_at IS NOT NULL)",
            "trashed_from": "trashed_from_status IS NULL OR status = 'trashed'",
            "published_at": "status NOT IN ('published', 'scheduled') OR published_at IS NOT NULL",
            "content_source": "(content_format = 'markdown') = (content_source IS NOT NULL)",
            "pin_order": "pin_order IS NULL OR is_pinned",
            "blind_source": "blind_source IS NULL OR is_blinded",
            "ip_hash": "(ip_hash IS NULL) = (ip_hash_period IS NULL)",
        },
        indexes={
            "ix_posts_board_list": "board_id, published_at DESC, id DESC"
            " | where status = 'published' AND is_pinned = false | include expires_at",
            "ix_posts_board_pinned": "board_id, pin_order | where status = 'published' AND is_pinned",
            "ix_posts_board_expires": "board_id, expires_at | where expires_at IS NOT NULL",
            "ix_posts_board_pending": "board_id, created_at | where status = 'pending'",
            "ix_posts_trashed": "trashed_at | where status = 'trashed'",
            "ix_posts_board_restricted": "board_id | where status = 'published'"
            " AND (is_secret OR is_blinded OR min_view_level > 0)",
            "ix_posts_member": "member_id, created_at DESC",
            "ix_posts_status_updated": "status, updated_at DESC",
            "ix_posts_sitemap": "published_at | where status = 'published'",
        },
    ),
    "post_stats": T(
        cols=[
            "post_id bigint",
            "view_count integer =0",
            "like_count integer =0",
            "comment_count integer =0",
            "scrap_count integer =0",
            "share_count integer =0",
            UPDATED,
        ],
        pk=("post_id",),
        fks={"post_id": "posts CASCADE"},
    ),
    "post_categories": T(
        cols=["post_id bigint", "category_id bigint"],
        pk=("post_id", "category_id"),
        fks={"post_id": "posts CASCADE", "category_id": "board_categories RESTRICT"},
        indexes={"ix_post_categories_category": "category_id, post_id"},
    ),
    "post_search": T(
        cols=[
            "post_id bigint",
            "board_id bigint",
            "published_at timestamptz null",
            "post_open boolean",
            "grams text[] ='{}'",
            "title_grams text[] ='{}'",
            "content_compact text =''",
            "title_compact text =''",
            UPDATED,
        ],
        pk=("post_id",),
        fks={"post_id": "posts CASCADE"},
        indexes={
            "ix_post_search_grams": "grams | using gin",
            "ix_post_search_title_grams": "title_grams | using gin",
            "ix_post_search_open_published": "published_at DESC | where post_open",
        },
    ),
    "post_relations": T(
        cols=["source_post_id bigint", "target_post_id bigint", "created_by bigint null", CREATED],
        pk=("source_post_id", "target_post_id"),
        fks={
            "source_post_id": "posts CASCADE",
            "target_post_id": "posts CASCADE",
            "created_by": "members SET NULL",
        },
        checks={"not_self": "source_post_id <> target_post_id"},
    ),
    "post_tombstones": T(
        cols=["post_id bigint", "board_slug varchar(100)", "purged_at timestamptz =now()"],
        pk=("post_id",),
    ),
    "post_reactions": T(
        cols=["post_id bigint", "member_id bigint", "kind varchar(10) ='like' in(like)", CREATED],
        pk=("post_id", "member_id", "kind"),
        fks={"post_id": "posts CASCADE", "member_id": "members CASCADE"},
    ),
    "post_scraps": T(
        cols=["post_id bigint", "member_id bigint", CREATED],
        pk=("post_id", "member_id"),
        fks={"post_id": "posts CASCADE", "member_id": "members CASCADE"},
        indexes={"ix_post_scraps_member": "member_id, created_at DESC"},
    ),
    "post_view_once": T(
        cols=["post_id bigint", "viewer_key varchar(64)", CREATED],
        pk=("post_id", "viewer_key"),
        fks={"post_id": "posts CASCADE"},
    ),
    "post_view_daily": T(
        cols=["post_id bigint", "viewer_key varchar(64)", "view_date date"],
        pk=("post_id", "viewer_key", "view_date"),
        fks={"post_id": "posts CASCADE"},
    ),
    # ── §4.4 댓글·첨부 ─────────────────────────────────────
    "comments": T(
        cols=[
            ID,
            "post_id bigint",
            "member_id bigint null",
            "author_name_snapshot varchar(50)",
            "parent_id bigint null",
            "reply_to_comment_id bigint null",
            "content text",
            "status varchar(10) ='published' in(published,deleted)",
            "is_blinded boolean =false",
            "blind_source varchar(12) null in(manual,auto_report)",
            "edited_at timestamptz null",
            CREATED,
            UPDATED,
        ],
        fks={
            "post_id": "posts CASCADE",
            "member_id": "members SET NULL",
            "parent_id": "comments CASCADE",
            "reply_to_comment_id": "comments SET NULL",
        },
        checks={"blind_source": "blind_source IS NULL OR is_blinded"},
        indexes={
            "ix_comments_post": "post_id, created_at",
            "ix_comments_member": "member_id, created_at DESC",
        },
    ),
    "attachments": T(
        cols=[
            ID,
            "post_id bigint null",
            "uploader_id bigint null",
            "role varchar(10) ='attachment' in(attachment,inline)",
            "original_name varchar(255)",
            "storage_key varchar(80)",
            "visibility varchar(8) ='private' in(public,private)",
            "sha256 char(64)",
            "detected_mime varchar(100)",
            "size_bytes bigint",
            "is_image boolean =false",
            "width integer null",
            "height integer null",
            "exif_stripped boolean =false",
            "thumbs_ready boolean =false",
            "sort_order smallint =0",
            "is_cover boolean =false",
            "alt_text varchar(300) null",
            "download_count integer =0",
            CREATED,
        ],
        fks={"post_id": "posts CASCADE", "uploader_id": "members SET NULL"},
        checks={"dimensions": "(width IS NULL) = (height IS NULL)"},
        uniques=[("storage_key",)],
        indexes={
            "ix_attachments_post": "post_id, sort_order",
            "ix_attachments_temp": "created_at | where post_id IS NULL",
        },
    ),
    # ── §4.5 운영·알림·기반 표 ─────────────────────────────
    "reports": T(
        cols=[
            ID,
            "target_type varchar(8) in(post,comment)",
            "target_id bigint",
            "board_id bigint null",
            "reporter_id bigint null",
            "reason_code varchar(20)",
            "reason_text text null",
            "status varchar(20) ='open'"
            " in(open,resolved_blinded,resolved_trashed,resolved_deleted,dismissed)",
            "handled_by bigint null",
            "handled_at timestamptz null",
            "resolution_note text null",
            CREATED,
        ],
        fks={
            "board_id": "boards SET NULL",
            "reporter_id": "members SET NULL",
            "handled_by": "members SET NULL",
        },
        uniques=[("target_type", "target_id", "reporter_id")],
        indexes={"ix_reports_open": "status, created_at | where status = 'open'"},
    ),
    "moderation_logs": T(
        cols=[
            ID,
            "actor_id bigint null",
            "board_id bigint null",
            "action varchar(40)",
            "target_type varchar(10) in(board,post,comment,report,member,sanction,setting)",
            "target_id bigint",
            "before jsonb null",
            "after jsonb null",
            "reason text null",
            CREATED,
            "redacted_at timestamptz null",
        ],
        fks={"actor_id": "members SET NULL", "board_id": "boards SET NULL"},
    ),
    "member_sanctions": T(
        cols=[
            ID,
            "member_id bigint",
            "scope_board_id bigint null",
            "actions text[]",
            "starts_at timestamptz =now()",
            "ends_at timestamptz null",
            "reason text",
            "created_by bigint null",
            "revoked_at timestamptz null",
            CREATED,
        ],
        fks={
            "member_id": "members CASCADE",
            "scope_board_id": "boards CASCADE",
            "created_by": "members SET NULL",
        },
        checks={
            "actions": "actions <@ ARRAY['write', 'comment', 'upload']::text[]"
            " AND cardinality(actions) > 0"
        },
        indexes={"ix_member_sanctions_active": "member_id | where revoked_at IS NULL"},
    ),
    "notifications": T(
        cols=[
            ID,
            "recipient_id bigint",
            "type varchar(30)",
            "actor_id bigint null",
            "actor_count integer =1",
            "post_id bigint null",
            "comment_id bigint null",
            "title_snapshot varchar(300)",
            "group_key varchar(100)",
            "dedupe_key varchar(100)",
            CREATED,
            UPDATED,
            "read_at timestamptz null",
        ],
        fks={
            "recipient_id": "members CASCADE",
            "actor_id": "members SET NULL",
            "post_id": "posts SET NULL",
            "comment_id": "comments SET NULL",
        },
        uniques=[("dedupe_key",)],
        indexes={
            "ix_notifications_recipient": "recipient_id, created_at DESC",
            "ix_notifications_unread": "recipient_id | where read_at IS NULL",
            "uq_notifications_group_unread": "recipient_id, group_key"
            " | where read_at IS NULL | unique",
        },
    ),
    "notification_prefs": T(
        cols=["member_id bigint", "type varchar(30)", "enabled boolean =true"],
        pk=("member_id", "type"),
        fks={"member_id": "members CASCADE"},
    ),
    "outbox_events": T(
        cols=[
            ID,
            "type varchar(40)",
            "payload jsonb",
            "dedupe_key varchar(100) null",
            "available_at timestamptz =now()",
            "attempts smallint =0",
            "last_error text null",
            "processed_at timestamptz null",
            "dead_at timestamptz null",
            CREATED,
        ],
        uniques=[("dedupe_key",)],
        indexes={
            "ix_outbox_events_pending": "available_at"
            " | where processed_at IS NULL AND dead_at IS NULL",
        },
    ),
    "worker_schedules": T(
        cols=[
            "name varchar(40)",
            "interval_sec integer",
            "last_run_at timestamptz null",
            "next_run_at timestamptz =now()",
            "locked_until timestamptz null",
        ],
        pk=("name",),
    ),
    "idempotency_keys": T(
        cols=[
            "scope varchar(80)",
            "key varchar(80)",
            "request_hash char(64)",
            "status_code smallint null",
            "response jsonb null",
            CREATED,
        ],
        pk=("scope", "key"),
    ),
    "rate_limit_counters": T(
        cols=["key varchar(120)", "window_start timestamptz", "count integer =0"],
        pk=("key", "window_start"),
        unlogged=True,
    ),
    "search_terms": T(
        cols=["term varchar(100)", "count bigint =0", "last_searched_at timestamptz"],
        pk=("term",),
    ),
    "search_synonyms": T(
        cols=["term varchar(100)", "synonym varchar(100)"],
        pk=("term", "synonym"),
    ),
}
