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
    description. Returns the input unchanged if it's empty."""
    if not html:
        return html
    return _STRAY_TOGGLE_RE.sub("", html)
