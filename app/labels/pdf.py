"""Printable labels. One 4x6 page per label, in the order given."""

PAGE_SIZE_IN = (4, 6)


def render_labels(labels) -> list[str]:
    return [label.pdf_url for label in labels]


def render_letter_sheets(labels) -> list[list[str]]:
    """Two labels per US Letter sheet."""
    urls = render_labels(labels)
    return [urls[i : i + 2] for i in range(0, len(urls), 2)]
