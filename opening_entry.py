"""Optional position-entry and transposition-label contract for authored books."""
from dataclasses import dataclass
import json
from opening_book_models import BookSnapshot, OpeningMove, position_identity
from opening_intelligence_models import NamedVariation, VariationContext


@dataclass(frozen=True)
class OpeningEntryContract:
    """Keep family entry independent from overlapping setup moves.

    Args:
        positions: Explicit canonical family-defining boards.
        labels: Canonical named paths at defining positions, retaining source IDs.
    """
    positions: frozenset[str]
    labels: dict[int, tuple[tuple[NamedVariation, ...], ...]]

    @classmethod
    def from_snapshot(cls, snapshot: BookSnapshot) -> 'OpeningEntryContract | None':
        """Load an opt-in metadata contract; legacy authored books retain their policy.

        Args:
            snapshot: Immutable authoring graph.

        Returns:
            Validated entry contract, or None for a legacy/unanchored book.

        Raises:
            ValueError: Entry metadata has an unsupported or malformed contract.
        """
        value = json.loads(snapshot.book.metadata_json).get('opening_entry')
        if value is None:
            return None
        if not isinstance(value, dict) or value.get('version') != 1 or not isinstance(value.get('positions'), list):
            raise ValueError('Unsupported opening entry contract.')
        anchors = value['positions']
        if not anchors or any(not isinstance(f, str) or position_identity(f).canonical_fen != f for f in anchors):
            raise ValueError('Entry anchors must be explicit canonical positions.')
        known = {p.canonical_fen for p in snapshot.positions}
        if not set(anchors) <= known:
            raise ValueError('Opening entry position is absent from the authored graph.')
        paths, representatives = {}, {}
        for move in snapshot.moves:
            if not move.active or not move.variation_name:
                continue
            parents = json.loads(move.metadata_json).get('opening_named_parents', [])
            if not isinstance(parents, list) or any(not isinstance(s, str) or not s for s in parents):
                raise ValueError('Named parent components must be nonempty strings.')
            path = (*parents, move.variation_name)
            paths[move.move_id] = path
            for length in range(1, len(path)+1):
                key = path[:length]
                representatives[key] = min(representatives.get(key, move.move_id), move.move_id)
        labels = {}
        for move in snapshot.moves:
            path = paths.get(move.move_id)
            if path:
                nodes = tuple(NamedVariation(representatives[path[:i+1]], name) for i,name in enumerate(path))
                labels.setdefault(move.to_position_id, set()).add(nodes)
        return cls(frozenset(anchors), {p:tuple(sorted(values, key=lambda v:tuple(n.name for n in v)))
                                       for p,values in labels.items()})

    def context_at(self, position_id: int, fallback: VariationContext) -> VariationContext:
        """Activate a name only at its defining board, regardless of incoming route.

        Args:
            position_id: Board reached by the actual game or graph walk.
            fallback: Previously supported context when no new label defines this board.

        Returns:
            Defining labels with shared IDs, or unchanged prior context.
        """
        paths = self.labels.get(position_id)
        return VariationContext(paths, fallback.observed, True) if paths else fallback
