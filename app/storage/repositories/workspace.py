from __future__ import annotations

from uuid import UUID

from app.core.config import Settings
from app.storage.db.session import Database
from app.storage.models.workspace import PersonalWorkspaceCreateInput, WorkspaceAccessRow


class WorkspaceRepository:
    def __init__(self, db: Database, settings: Settings):
        self.db = db
        self.settings = settings

    async def list_workspaces_for_user(self, user_id: UUID) -> list[WorkspaceAccessRow]:
        query = """
            select t.id, t.name, t.slug, tm.role
            from workspace_members tm
            join workspaces t on t.id = tm.workspace_id
            where tm.user_id = %s and tm.status = 'active' and t.status = 'active'
            order by t.name
        """
        async with self.db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, (user_id,))
                rows = await cur.fetchall()
        return [WorkspaceAccessRow.from_row(row) for row in rows]

    async def user_has_workspace_access(self, user_id: UUID, workspace_id: UUID) -> bool:
        query = """
            select exists(
                select 1 from workspace_members
                where workspace_id = %s and user_id = %s and status = 'active'
            ) as allowed
        """
        async with self.db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, (workspace_id, user_id))
                row = await cur.fetchone()
        return bool(row["allowed"]) if row else False

    async def get_workspace_role(self, user_id: UUID, workspace_id: UUID) -> str | None:
        query = """
            select role
            from workspace_members
            where workspace_id = %s and user_id = %s and status = 'active'
            limit 1
        """
        async with self.db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, (workspace_id, user_id))
                row = await cur.fetchone()
        return row["role"] if row else None

    async def get_primary_workspace_for_user(self, user_id: UUID) -> WorkspaceAccessRow | None:
        query = """
            select t.id, t.name, t.slug, tm.role
            from workspace_members tm
            join workspaces t on t.id = tm.workspace_id
            where tm.user_id = %s and tm.status = 'active' and t.status = 'active'
            order by tm.created_at asc
            limit 1
        """
        async with self.db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, (user_id,))
                row = await cur.fetchone()
        return WorkspaceAccessRow.from_row(row) if row else None

    async def create_personal_workspace(self, payload: PersonalWorkspaceCreateInput) -> UUID:
        user_id = payload.user_id
        email = payload.email
        local_part = (email or f"user-{str(user_id)[:8]}").split("@", 1)[0].strip() or f"user-{str(user_id)[:8]}"
        display_name = local_part.replace(".", " ").replace("_", " ").replace("-", " ").strip().title() or "User"
        workspace_name = f"{display_name}'s Workspace"
        workspace_slug = f"workspace-{str(user_id).replace('-', '')[:12]}"
        async with self.db.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    insert into profiles (id, display_name, email, status)
                    values (%s, %s, %s, 'active')
                    on conflict (id) do update set
                        display_name = excluded.display_name,
                        email = coalesce(excluded.email, profiles.email),
                        updated_at = now()
                    """,
                    (user_id, display_name, email),
                )
                await cur.execute(
                    """
                    insert into workspaces (name, slug, plan, status)
                    values (%s, %s, 'personal', 'active')
                    on conflict (slug) do update set
                        name = excluded.name,
                        updated_at = now()
                    returning id
                    """,
                    (workspace_name, workspace_slug),
                )
                workspace = await cur.fetchone()
                workspace_id = workspace["id"]
                await cur.execute(
                    """
                    insert into workspace_members (workspace_id, user_id, role, status)
                    values (%s, %s, 'owner', 'active')
                    on conflict (workspace_id, user_id) do nothing
                    """,
                    (workspace_id, user_id),
                )
                await conn.commit()
        return workspace_id
