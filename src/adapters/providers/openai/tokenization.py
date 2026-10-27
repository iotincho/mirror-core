"""Local cl100k_base tokenization; the encoding is cached in the image."""


def token_count(text: str) -> int:
    import tiktoken

    return len(tiktoken.get_encoding("cl100k_base").encode(text, disallowed_special=()))
