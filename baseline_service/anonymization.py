def mask_spans(text: str, spans: list) -> str:
    """
    Replace each merged region [start:end] in `text` with exactly five asterisks (*****).
    - text: the original string
    - spans: list of dicts with integer 'start' and 'end' keys
    """

    clean_spans = []
    for s in spans:
        st, ed = int(s["start"]), int(s["end"])
        if 0 <= st < ed <= len(text):
            clean_spans.append((st, ed))

    if not clean_spans:
        return text

    clean_spans.sort(key=lambda x: x[0])
    merged = [list(clean_spans[0])]
    for st, ed in clean_spans[1:]:
        last = merged[-1]
        if st <= last[1]:
            last[1] = max(last[1], ed)
        else:
            merged.append([st, ed])

    masked = text
    for st, ed in sorted(merged, key=lambda x: x[0], reverse=True):
        masked = masked[:st] + "*****" + masked[ed:]

    return masked
