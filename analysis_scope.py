"""Pinned validation scopes shared by analysis rollout services."""
import json


def saved_scope_ids(project_root, filename, count):
    saved = json.loads((project_root / "reports" / filename).read_text(encoding="utf-8"))
    ids = saved.get("game_ids", [])
    if (saved.get("games") != count or len(ids) != count or len(set(ids)) != count
            or any(type(value) is not int or value <= 0 for value in ids)):
        raise ValueError(f"Expected exactly {count} distinct game IDs in the saved validation report")
    return sorted(ids)


def validation_scope_ids(project_root):
    return saved_scope_ids(project_root, "scout_preview_500.json", 500)


def heavy_test_game_ids(project_root):
    return saved_scope_ids(project_root, "negative_write_10.json", 10)
