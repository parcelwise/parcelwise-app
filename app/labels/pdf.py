"""Printable labels. One 4x6 page per label, in the order given."""

PAGE_SIZE_IN = (4, 6)


def render_labels(labels) -> list[str]:
    return [label.pdf_url for label in labels]
