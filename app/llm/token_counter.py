import tiktoken


def count_tokens(text: str) -> int:
    try:
        encoder = tiktoken.get_encoding("cl100k_base")
        return len(encoder.encode(text))
    except Exception:
        return max(1, len(text.split()))
