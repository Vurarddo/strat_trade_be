from __future__ import annotations


def trim_leading_none_indicator_values(values: list[float | None]) -> tuple[int, list[float]]:
    """
    Drop leading undefined samples. Remaining entries must be floats (domain calculators
    should not emit gaps after the first defined point).
    """
    idx = 0
    n = len(values)
    while idx < n and values[idx] is None:
        idx += 1
    tail = values[idx:]
    out: list[float] = []
    for v in tail:
        if v is None:
            raise TypeError("trim_leading_none_indicator_values: internal None after leading trim")
        out.append(float(v))
    return idx, out
