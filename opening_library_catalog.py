"""Typed library preferences in the existing catalog envelope; no schema migration.

V1's catalog row names remain for on-disk compatibility. Each row now describes a
library; per-book choices live in its existing JSON envelope, never in author data.
"""
from dataclasses import dataclass
import json
from opening_book_models import text


@dataclass(frozen=True)
class LibraryOptions:
    name: str
    per_book_enabled: tuple[tuple[int,bool], ...]
    primary_book_id: int | None
    legacy_book_id: int | None

    @classmethod
    def from_row(cls,row,snapshots):
        data=json.loads(row['provenance_json'])
        first=snapshots[0].book if snapshots else None
        name=data.get('library_name') or (first.name if first else 'Empty library')
        text(name,'Library name',required=True)
        legacy=first.book_id if first and data.get('library_contract')!=2 else None
        settings=data.get('book_enabled',{})
        if not isinstance(settings,dict):raise ValueError('Invalid book preferences.')
        preferences=[]
        for bid,enabled in settings.items():
            if not str(bid).isdigit() or int(bid)<1 or type(enabled) is not bool:raise ValueError('Invalid book preference.')
            preferences.append((int(bid),enabled))
        primary=data.get('primary_book_id',legacy) if row['is_primary'] else None
        if primary is not None and (type(primary) is not int or primary<1):raise ValueError('Invalid primary book.')
        if legacy is not None and str(legacy) not in settings:preferences.append((legacy,bool(row['enabled'])))
        return cls(name,tuple(preferences),primary,legacy)

    def reference_id(self,library_id,book_id):
        return library_id if book_id==self.legacy_book_id else f'{library_id}:{book_id}'

    def enabled(self,book_id):return dict(self.per_book_enabled).get(book_id,True)
