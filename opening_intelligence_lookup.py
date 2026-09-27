"""Indexed, reusable position lookup over a frozen authored snapshot."""
from collections import deque
from dataclasses import asdict
from pathlib import Path
import chess
from opening_book_models import position_identity, BookSnapshot, OpeningMove
from opening_entry import OpeningEntryContract
from opening_book_reader import read_book
from opening_intelligence_models import (OpeningMatchPolicy, BookProvenance, NamedVariation,
    VariationContext, OpeningPositionLookup, identity)


def advance_context(context, move):
    """Only a traversed named anchor extends a played context; repeat visits do not nest it."""
    paths=[]
    for path in context.paths:
        if move.variation_name and move.move_id not in {v.move_id for v in path}:
            path=(*path,NamedVariation(move.move_id,move.variation_name))
        if path not in paths:paths.append(path)
    return VariationContext(tuple(paths),context.observed,context.complete)


class OpeningBookLookup:
    """Index immutable authored membership, optional entry anchors and named positions.

    Args:
        snapshot: Validated authoring snapshot.
        library_identity: Stable managed-library provenance.
        policy: Existing matching and bounded context policy.
    """

    def __init__(self, snapshot: BookSnapshot, *, library_identity: str = 'in_memory',
                 policy: OpeningMatchPolicy = OpeningMatchPolicy()) -> None:
        """Validate/index the graph without engines, database access or mutations.

        Args:
            snapshot: Authored immutable graph.
            library_identity: Library provenance namespace.
            policy: Shared matching and bounded context policy.

        Raises:
            ValueError: Graph identity, legality or optional entry metadata is invalid.
        """
        self.snapshot,self.policy=snapshot,policy
        self.entry_contract = OpeningEntryContract.from_snapshot(snapshot)
        positions={p.position_id:p for p in snapshot.positions}
        if snapshot.book.root_position_id not in positions:raise ValueError('Book root missing.')
        self.identities={}
        for position in positions.values():
            canonical=position_identity(position.canonical_fen)
            if canonical.canonical_fen!=position.canonical_fen or canonical.polyglot_key!=position.polyglot_key:
                raise ValueError('Invalid book position identity.')
            self.identities[position.position_id]=canonical
        self.outgoing={}
        for move in snapshot.moves:
            if move.from_position_id not in positions or move.to_position_id not in positions:
                raise ValueError('Invalid book move references.')
            board=chess.Board(positions[move.from_position_id].canonical_fen)
            actual=board.parse_uci(move.move_uci)
            if not actual or board.san(actual)!=move.san:raise ValueError('Invalid saved book move.')
            board.push(actual)
            if position_identity(board)!=self.identities[move.to_position_id]:raise ValueError('Book move destination mismatch.')
            if move.active:self.outgoing.setdefault(move.from_position_id,[]).append(move)
        reachable,pending=set(),[snapshot.book.root_position_id]
        while pending:
            position=pending.pop()
            if position in reachable:continue
            reachable.add(position)
            pending.extend(m.to_position_id for m in self.outgoing.get(position,()))
        self.positions={positions[p].canonical_fen:positions[p] for p in reachable}
        self.outgoing={p:tuple(sorted(self.outgoing.get(p,()),key=lambda m:m.move_id)) for p in reachable}
        self.contexts,self.contexts_complete=self._contexts()
        membership = (self.identities[snapshot.book.root_position_id].canonical_fen,
                      sorted((positions[m.from_position_id].canonical_fen,m.move_uci,positions[m.to_position_id].canonical_fen)
                             for p in reachable for m in self.outgoing[p]))
        if self.entry_contract:
            membership = (*membership, sorted(self.entry_contract.positions))
        label_content = (snapshot.book.name, [(m.move_id,m.variation_name,m.variation_description) for m in snapshot.moves])
        if self.entry_contract:
            label_content = (*label_content, {p:[[asdict(n) for n in path] for path in paths] for p,paths in self.entry_contract.labels.items()})
        self.provenance=BookProvenance(library_identity,snapshot.book.book_id,snapshot.book.name,
            snapshot.book.version,snapshot.book.revision,snapshot.identity,
            identity(membership),
            identity(label_content),
            identity([(m.move_id,m.weight,m.preferred) for m in snapshot.moves]),identity(asdict(policy)))

    @classmethod
    def from_library(cls,path,book_id,*,policy=OpeningMatchPolicy()):
        return cls(read_book(path,book_id),library_identity=identity(str(Path(path).resolve()).casefold()),policy=policy)

    def advance_context(self, context: VariationContext, move: OpeningMove) -> VariationContext:
        """Resolve position labels for anchored books and preserve legacy edge naming.

        Args:
            context: Supported context before the move.
            move: Authored move reaching the next board.

        Returns:
            Named context at the destination board.
        """
        if self.entry_contract:
            return self.entry_contract.context_at(move.to_position_id, context)
        return advance_context(context, move)

    def _contexts(self):
        root=self.snapshot.book.root_position_id
        contexts={root:[()]};pending=deque([(root,())]);complete=True
        while pending:
            position,path=pending.popleft()
            for move in self.outgoing.get(position,()):
                for next_path in self.advance_context(VariationContext((path,)),move).paths:
                    known=contexts.setdefault(move.to_position_id,[])
                    if next_path in known:continue
                    if len(next_path)>self.policy.max_named_depth or len(known)>=self.policy.max_variation_contexts:
                        complete=False;continue
                    known.append(next_path);pending.append((move.to_position_id,next_path))
        return {p:tuple(paths) for p,paths in contexts.items()},complete

    def lookup(self,position,*,context=None):
        key=position_identity(position)
        found=self.positions.get(key.canonical_fen)
        available=self.outgoing.get(found.position_id,()) if found else ()
        named=context if context is not None and found else VariationContext(
            self.contexts.get(found.position_id,()) if found else (),False,self.contexts_complete)
        return OpeningPositionLookup(self.provenance,key,found.position_id if found else None,available,
                                     next((m for m in available if m.preferred),None),named)
