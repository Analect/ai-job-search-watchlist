"""T041: lightweight key-term extraction.

No research.md decision exists for this — genuinely open (see
20260906-phase4-enrichment-and-similarity.md's rationale). Uses TF-IDF
(scikit-learn, already a project dependency from the company-landscape-
mapping work) over the current enrichment batch's own description
texts, rather than a second per-posting Bedrock/LLM call — key_terms
feeds job-search-api.contract.md's `query` free-text filter (a search
aid), not a similarity/training signal, so a free, fast lexical
extraction fits the actual need.
"""

from sklearn.feature_extraction.text import TfidfVectorizer

from pipelines.common.db import get_connection
from pipelines.common.text_clean import html_to_text

TOP_N = 8


def extract_key_terms(texts: list[str]) -> list[list[str]]:
    """Top TOP_N TF-IDF-scoring 1-2 grams per text, relative to the
    given batch as its own corpus. Same order as `texts`."""
    if not texts:
        return []
    vectorizer = TfidfVectorizer(
        max_features=5000, ngram_range=(1, 2), stop_words="english", min_df=1
    )
    matrix = vectorizer.fit_transform(texts)
    terms = vectorizer.get_feature_names_out()
    results = []
    for row in matrix:
        dense = row.toarray().ravel()
        top_idx = dense.argsort()[::-1][:TOP_N]
        results.append([terms[i] for i in top_idx if dense[i] > 0])
    return results


def enrich_key_terms(job_posting_ids: list[str]) -> None:
    if not job_posting_ids:
        return
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            select jp.id, coalesce(nullif(d.content, ''), jp.title)
            from job_postings jp
            left join descriptions d on d.job_posting_id = jp.id and d.locale = 'en'
            where jp.id = any(%s::uuid[])
            """,
            (job_posting_ids,),
        )
        rows = cur.fetchall()
        if not rows:
            return
        ids = [r[0] for r in rows]
        texts = [html_to_text(r[1]) for r in rows]
        key_terms_list = extract_key_terms(texts)
        for posting_id, key_terms in zip(ids, key_terms_list, strict=True):
            cur.execute(
                "update job_postings set key_terms = %s where id = %s",
                (key_terms, str(posting_id)),
            )
        conn.commit()
