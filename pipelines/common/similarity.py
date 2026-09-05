"""research.md §2/§11 / mcp-server-tools.contract.md find_similar:
the SINGLE similarity-search implementation, called by both
api/app.py's GET /postings/{id}/similar and mcp_server/server.py's
find_similar tool — never a reimplementation.
"""

from uuid import UUID

from pipelines.common.db import get_connection


def find_similar(job_posting_id: UUID | str | None = None, limit: int = 5) -> dict:
    with get_connection() as conn, conn.cursor() as cur:
        target_id = job_posting_id
        if target_id is None:
            cur.execute(
                """
                select job_posting_id from job_events
                 where event_type = 'flagged_for_advancement'
                 order by created_at desc
                 limit 1
                """
            )
            row = cur.fetchone()
            if row is None:
                return {"results": [], "message": "nothing has been flagged yet"}
            target_id = row[0]

        cur.execute("select embedding from job_postings where id = %s", (str(target_id),))
        target = cur.fetchone()
        if target is None or target[0] is None:
            return {"results": [], "message": "the target posting has no embedding yet"}
        target_embedding = target[0]

        cur.execute(
            """
            select jp.id, e.name, jp.title, jp.source_url,
                   jp.embedding <=> %s as distance
              from job_postings jp
              join employers e on e.id = jp.employer_id
             where jp.status = 'open'
               and jp.embedding is not null
               and jp.id != %s
             order by jp.embedding <=> %s
             limit %s
            """,
            (target_embedding, str(target_id), target_embedding, limit),
        )
        rows = cur.fetchall()

    return {
        "results": [
            {
                "id": r[0],
                "employer_name": r[1],
                "title": r[2],
                "source_url": r[3],
                "similarity_score": 1 - r[4],
            }
            for r in rows
        ]
    }
