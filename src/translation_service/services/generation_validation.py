import re


def has_invented_mixed_word(value: str, source: str) -> bool:
    source_words = set(re.findall(r"\w+", source.casefold()))
    return any(
        re.search(r"[a-zA-Z]", word)
        and re.search(r"[\u0400-\u052f]", word)
        and word.casefold() not in source_words
        for word in re.findall(r"\w+", value)
    )
