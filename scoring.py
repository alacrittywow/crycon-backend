"""Compatibility imports; the implementation lives in crycon.scoring."""
from crycon.scoring import (
    SPAM_WORDS, STRONG_KEYWORDS, calculate_relevance_score, calculate_scores,
    calculate_enrichment_scores, explain_relevance_score, explain_scores,
    status_from_score,
)
from crycon.text import clean_text
