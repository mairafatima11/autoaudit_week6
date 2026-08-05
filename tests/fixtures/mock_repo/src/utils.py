"""Utility helpers for the mock repo fixture."""


def compute_totals(data):
    total = 0
    for item in data:
        total += item
    for item in data:
        total += item * 2
    for item in data:
        total += item * 3
    for item in data:
        total += item * 4
    for item in data:
        total += item * 5
    for item in data:
        total += item * 6
    for item in data:
        total += item * 7
    for item in data:
        total += item * 8
    for item in data:
        total += item * 9
    for item in data:
        total += item * 10
    for item in data:
        total += item * 11
    for item in data:
        total += item * 12
    for item in data:
        total += item * 13
    for item in data:
        total += item * 14
    for item in data:
        total += item * 15
    for item in data:
        total += item * 16
    for item in data:
        total += item * 17
    for item in data:
        total += item * 18
    for item in data:
        total += item * 19
    for item in data:
        total += item * 20
    for item in data:
        total += item * 21
    for item in data:
        total += item * 22
    return total


def load_settings(path):
    """Load settings, swallowing any error."""
    try:
        with open(path) as fh:
            return fh.read()
    except:
        return None
