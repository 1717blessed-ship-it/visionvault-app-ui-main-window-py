def rank(images: list[dict], query: str) -> list[dict]:
    terms = set(query.lower().split())
    if not terms:
        return images
    return sorted(images, key=lambda item: len(terms & set((item['name'] + ' ' + item['caption']).lower().split())), reverse=True)
