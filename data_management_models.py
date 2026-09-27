"""Immutable preview contracts; execution must revalidate the approved impact."""
from dataclasses import dataclass


@dataclass(frozen=True)
class GameDeletionPlan:
    database_path: str
    game_ids: tuple[int, ...]
    identities: tuple[tuple[str, str], ...]
    counts: tuple[tuple[str, int], ...]
    fingerprint: str
    reset: bool = False
    clear_ignored: bool = False

    def summary(self, *, ignore_future_imports=False):
        lines = ["Reset Chess Data?" if self.reset else f"Delete {len(self.game_ids)} selected games?", "",
                 *[f"{name.replace('_', ' ')}: {count:,}" for name, count in self.counts if count]]
        if self.reset:
            lines += ["", "Ignored future imports: " + ("CLEAR" if self.clear_ignored else "KEEP"),
                      "Themes, appearance, app settings and schema are preserved."]
        elif ignore_future_imports:
            lines += ["", f"Suppress future imports for {len(self.identities)} source identities."]
        else:
            lines += ["", "These games may return on a later manual import."]
        lines += ["Historical QA notes are preserved but detached from deleted records.",
                  "This removes the listed data permanently."]
        return "\n".join(lines)


@dataclass(frozen=True)
class GameDeletionResult:
    counts: tuple[tuple[str, int], ...]
    ignored_added: int = 0
