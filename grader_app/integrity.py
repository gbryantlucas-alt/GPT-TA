from __future__ import annotations

import math
import re
from collections import Counter

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from grader_app.models import SimilarityFlag


SENTENCE_SPLIT = re.compile(r"[.!?]+\s+")
WORD_RE = re.compile(r"\b\w+\b")


def similarity_flags(texts: dict[str, str], threshold: float = 0.75) -> list[SimilarityFlag]:
    if len(texts) < 2:
        return []
    students = list(texts.keys())
    corpus = [texts[s] for s in students]
    tfidf = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), min_df=1)
    mat = tfidf.fit_transform(corpus)
    scores = cosine_similarity(mat)
    flags: list[SimilarityFlag] = []
    for i in range(len(students)):
        for j in range(i + 1, len(students)):
            sc = float(scores[i, j])
            if sc >= threshold:
                flags.append(SimilarityFlag(students[i], students[j], round(sc, 3)))
    return sorted(flags, key=lambda x: x.score, reverse=True)


def ai_usage_signal_score(text: str) -> tuple[float, str]:
    sentences = [s.strip() for s in SENTENCE_SPLIT.split(text) if s.strip()]
    words = [w.lower() for w in WORD_RE.findall(text)]
    if not sentences or not words:
        return 0.0, "Insufficient text for signal analysis."

    sent_lens = [len(WORD_RE.findall(s)) for s in sentences]
    mean_len = sum(sent_lens) / len(sent_lens)
    variance = sum((x - mean_len) ** 2 for x in sent_lens) / len(sent_lens)
    std = math.sqrt(variance)

    vocab_diversity = len(set(words)) / max(len(words), 1)
    top_repeat = Counter(words).most_common(10)
    repetition_ratio = sum(c for _, c in top_repeat) / len(words)

    score = 0.0
    if std < 5:
        score += 35
    if 0.25 < vocab_diversity < 0.42:
        score += 25
    if repetition_ratio < 0.24:
        score += 20
    if len(sentences) > 15 and mean_len > 16:
        score += 20
    score = min(100.0, round(score, 1))

    note = (
        "Signal-only estimate based on sentence-length uniformity, lexical patterns, and repetition. "
        "Not a definitive verdict and should never be the sole evidence of misconduct."
    )
    return score, note
