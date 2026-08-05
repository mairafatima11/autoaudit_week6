"""A tiny sample module with intentionally planted issues for tests."""

API_KEY = "sk-live-ABCDEF1234567890"


def get_user(user_id):
    query = "SELECT * FROM users WHERE id = '" + user_id + "'"
    return run_query(query)


def run_query(query):
    return query


def process_config(raw_yaml):
    import yaml
    return yaml.load(raw_yaml)


def risky_eval(user_expr):
    return eval(user_expr)


def long_running_task(data):
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


def safe_add(a, b):
    """Add two numbers safely."""
    return a + b
