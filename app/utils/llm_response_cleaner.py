import re


def clean_response(text: str) -> str:
    # Step 1: Find all URLs and replace them with a placeholder
    url_pattern = r'https?://[^\s]+'
    urls = re.findall(url_pattern, text)

    for i, url in enumerate(urls):
        text = text.replace(url, f"__URL_{i}__")

    # Step 2: Remove dashes from the remaining text
    text = re.sub(r"[—–-]", ", ", text)

    # Step 3: Restore the original URLs
    for i, url in enumerate(urls):
        text = text.replace(f"__URL_{i}__", url)

    return text
