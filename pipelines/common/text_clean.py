"""Shared text/HTML cleanup lessons ported from jseek's own production
code (`core/monitors/greenhouse.py`'s `_clean_text`/`_clean_description`)
— hard-won against real boards (e.g. their Varda Space case study), not
reinvented. Reusable across any adapter returning free-text titles/
locations or HTML job descriptions, not just Greenhouse.
"""

import re

# Href-less anchors whose text is a collapsed-section toggle. Some ATS
# boards paste HTML from WYSIWYG editors that leave stranded
# ``<a>Read more</a>``/``<a>Learn more</a>`` artifacts - no href, purely
# decorative. Strip them so they don't trail the description.
_STRAY_TOGGLE_RE = re.compile(
    r"<a(?![^>]*\shref=)[^>]*>\s*(?:read|learn|show|see|view)\s+more\s*</a>",
    re.IGNORECASE,
)


def clean_text(value: str | None) -> str | None:
    """Collapse source formatting whitespace in a display field (title,
    location, department, ...). Returns None for empty/blank input."""
    if not value:
        return None
    cleaned = " ".join(value.split())
    return cleaned or None


def clean_description(html: str | None) -> str | None:
    """Strip stray WYSIWYG toggle-anchor artifacts from an HTML job
    description. Returns the input unchanged if it's empty — this
    deliberately keeps the HTML intact (job-search-web renders it as
    rich text), it does not produce plain text. Use html_to_text() for
    that (TF-IDF/embeddings input, where tags/inline-styles are noise,
    not signal)."""
    if not html:
        return html
    return _STRAY_TOGGLE_RE.sub("", html)


_TAG_RE = re.compile(r"<[^>]+>")
_ENTITY_RE = re.compile(r"&(amp|lt|gt|quot|#39|nbsp);")
_ENTITY_MAP = {"amp": "&", "lt": "<", "gt": ">", "quot": '"', "#39": "'", "nbsp": " "}


def html_to_text(html: str | None) -> str:
    """Plain text for text-analysis input (TF-IDF, embeddings) — strips
    tags/attributes entirely (found necessary via T040/T041's own live
    test: descriptions.content is stored as HTML, and inline
    style="min-height:5em" attributes were polluting TF-IDF's top terms
    with 'min height'/'5em'/'style' instead of real skill terms)."""
    if not html:
        return ""
    text = _TAG_RE.sub(" ", html)
    text = _ENTITY_RE.sub(lambda m: _ENTITY_MAP[m.group(1)], text)
    return " ".join(text.split())
