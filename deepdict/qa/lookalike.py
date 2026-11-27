"""Lookalike (misread-word) detection.

The hallucination mode this targets: the model silently reads a rare headword
as a much more frequent neighbor (deference -> difference, causal -> casual)
and writes the neighbor's senses with high self-reported confidence. The
self-reported scores cannot catch this; string geometry can.

A word is flagged when a much more frequent vocabulary word sits within
Damerau-Levenshtein (OSA) distance <= 2, excluding pairs that are just
inflections of the same stem. Candidate pairs are found with a SymSpell-style
depth-2 deletion index so the scan stays near-linear.
"""

COMMON_ENDINGS = ("ing", "ed", "es", "est", "er", "ly", "s", "e")


def osa_distance(a, b, max_dist=2):
    """Optimal string alignment distance with cutoff.

    Returns the distance if <= max_dist, else max_dist + 1.
    """
    la, lb = len(a), len(b)
    if abs(la - lb) > max_dist:
        return max_dist + 1
    prev2 = None
    prev = list(range(lb + 1))
    for i in range(1, la + 1):
        cur = [i] + [0] * lb
        best = cur[0]
        for j in range(1, lb + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            value = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            if (
                prev2 is not None
                and i > 1
                and j > 1
                and a[i - 1] == b[j - 2]
                and a[i - 2] == b[j - 1]
            ):
                value = min(value, prev2[j - 2] + 1)
            cur[j] = value
            if value < best:
                best = value
        if best > max_dist:
            return max_dist + 1
        prev2, prev = prev, cur
    return prev[lb] if prev[lb] <= max_dist else max_dist + 1


def _strip_ending(word):
    for ending in COMMON_ENDINGS:
        if word.endswith(ending) and len(word) - len(ending) >= 3:
            return word[: -len(ending)]
    return word


def same_stem(a, b):
    """Cheap check for 'these are inflections of one stem', to avoid flagging
    token/tokens or grade/graded as lookalike risks."""
    if a == b:
        return True
    sa, sb = _strip_ending(a), _strip_ending(b)
    if sa == sb:
        return True
    # e-drop inflection: grade -> grading
    if sa.rstrip("e") == sb.rstrip("e"):
        return True
    # y -> ie: study -> studies
    if sa.rstrip("y").rstrip("i") == sb.rstrip("y").rstrip("i") and abs(len(sa) - len(sb)) <= 1:
        return True
    return False


def deletions(word, depth):
    variants = {word}
    frontier = {word}
    for _ in range(depth):
        next_frontier = set()
        for w in frontier:
            for i in range(len(w)):
                next_frontier.add(w[:i] + w[i + 1 :])
        next_frontier -= variants
        variants |= next_frontier
        frontier = next_frontier
    return variants


def build_deletion_index(vocab, depth=2):
    index = {}
    for word in vocab:
        for variant in deletions(word, depth):
            index.setdefault(variant, []).append(word)
    return index


def find_lookalikes(word, index, max_dist=2):
    """Return vocab words within OSA distance <= max_dist of word, excluding
    same-stem pairs. Sorted by distance."""
    candidates = set()
    for variant in deletions(word, max_dist):
        for vocab_word in index.get(variant, ()):
            candidates.add(vocab_word)
    hits = []
    for candidate in candidates:
        if same_stem(word, candidate):
            continue
        dist = osa_distance(word, candidate, max_dist)
        if dist <= max_dist:
            hits.append((dist, candidate))
    hits.sort()
    return hits
