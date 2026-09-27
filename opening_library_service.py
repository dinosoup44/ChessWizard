"""Canonical installed-book management; safe file operations stay outside the UI."""
from dataclasses import asdict, replace
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import uuid
from opening_library_repository import OpeningLibraryRepository
from opening_library_models import InstalledBook, ImportResult, RemovalPreview
from opening_library_package import inspect_package, semantic_identity, write_package
from opening_book_models import BookDetails
from opening_book_repository import OpeningBookRepository


class OpeningLibraryService:
    def __init__(self, repository=None):
        self.repository=repository or OpeningLibraryRepository()

    def list_libraries(self):
        return self._libraries_from_rows(self.repository.rows())

    def _libraries_from_rows(self,rows):
        from opening_book_reader import read_library
        from opening_library_catalog import LibraryOptions
        from opening_library_models import ManagedLibrary
        result=[]
        for row in rows:
            library_id=row['installation_id'];path=self.repository.path(library_id)
            try:
                snapshots=read_library(path)
                options=LibraryOptions.from_row(row,snapshots)
                deleted=set(json.loads(row['provenance_json']).get('studio_deleted_books',()))
                books=tuple(InstalledBook(options.reference_id(library_id,s.book.book_id),path,s,
                    options.enabled(s.book.book_id),options.primary_book_id==s.book.book_id,
                    row['origin'],row['provenance_json'],library_id=library_id,library_name=options.name) for s in snapshots if s.book.book_id not in deleted)
                name=options.name;error=''
            except (ValueError,OSError,sqlite3.Error) as exc:
                books=();name='Unavailable library';error=str(exc)
            result.append(ManagedLibrary(library_id,name,path,books,row['origin'],error))
        return tuple(sorted(result,key=lambda item:(item.name.casefold(),item.library_id)))

    def list_books(self):
        return tuple(book for library in self.list_libraries() for book in library.books)

    def get_library(self,library_id):
        item=next((lib for lib in self.list_libraries() if lib.library_id==library_id),None)
        if item is None:raise ValueError('Library is no longer managed.')
        if item.error:raise ValueError(item.error)
        return item

    def library_for_path(self,path):
        path=Path(path).resolve()
        return next((lib for lib in self.list_libraries() if lib.path.resolve()==path),None)

    def create_library(self,name):
        from opening_book_models import text
        text(name,'Library name',required=True)
        return self._create_library((),name,'user authored',{},deduplicate=False)

    def authoring_library(self, *, create=False):
        """One stable destination for new Studio books; reads never create storage."""
        for row in self.repository.rows():
            if json.loads(row['provenance_json']).get('studio_home'):
                return self.get_library(row['installation_id'])
        if not create:return None
        return self._create_library((), 'My ChessWizard Opening Library', 'user authored',
                                    {'studio_home':True}, deduplicate=False)

    def _create_library(self,snapshots,name,origin,provenance,*,deduplicate,allow_partial_overlap=False):
        from opening_library_package import write_library_package
        snapshots=tuple(snapshots)
        identifier=str(uuid.uuid4());destination=self.repository.path(identifier);created=False
        data=dict(provenance,library_name=name,library_contract=2)
        try:
            with self.repository.write() as db:
                if provenance.get('studio_home'):
                    for row in db.execute('SELECT installation_id,provenance_json FROM installed_books'):
                        if json.loads(row[1]).get('studio_home'):return self.get_library(row[0])
                if deduplicate:
                    expected={semantic_identity(s) for s in snapshots}
                    columns=('installation_id','enabled','is_primary','origin','provenance_json')
                    rows=tuple(dict(zip(columns,row)) for row in db.execute('SELECT * FROM installed_books'))
                    overlap=False
                    for library in self._libraries_from_rows(rows):
                        existing={semantic_identity(b.snapshot) for b in library.books}
                        overlap=overlap or bool(expected & existing)
                        if not library.error and ((expected and expected.issubset(existing)) or (not expected and not existing)):return library
                    if overlap and not allow_partial_overlap:
                        raise ValueError("Some books are already managed. Review the overlap before adding a separate library.")
                write_library_package(snapshots,destination);created=True
                db.execute('INSERT INTO installed_books VALUES (?,1,0,?,?)',(identifier,origin,json.dumps(data,sort_keys=True)))
        except BaseException:
            if created:destination.unlink()
            raise
        return self.get_library(identifier)

    def import_library(self,path,preview,*,name=None,owner_adoption=False,allow_partial_overlap=False):
        current=inspect_package(path,allow_empty=True)
        if current!=preview:raise ValueError('Library changed; inspect a fresh preview.')
        provenance=dict(imported_filename=current.filename,imported_at=datetime.now(timezone.utc).isoformat(),
                        source_file_sha256=current.file_sha256)
        return self._create_library(current.books,name or Path(path).stem,
            'adopted owner library' if owner_adoption else 'external import',provenance,deduplicate=True,allow_partial_overlap=allow_partial_overlap)

    def partial_overlap(self,preview):
        """Describe exact existing books when the whole incoming library cannot be reused."""
        expected={semantic_identity(s) for s in preview.books};matches=[]
        for library in self.list_libraries():
            existing={semantic_identity(b.snapshot) for b in library.books}
            if expected.issubset(existing):return ()
            matches.extend(f'{library.name} / {book.snapshot.book.name}' for book in library.books
                           if semantic_identity(book.snapshot) in expected)
        return tuple(matches)

    def export_library(self,library_id,destination):
        from opening_library_package import write_library_package
        library=self.get_library(library_id);self._export_destination(destination)
        write_library_package(tuple(b.snapshot for b in library.books),destination)
        if library.books:
            actual=inspect_package(destination).books
            if sorted(semantic_identity(s) for s in actual)!=sorted(semantic_identity(b.snapshot) for b in library.books):
                raise ValueError('Library export verification failed.')

    def _export_destination(self,destination):
        destination=Path(destination).absolute()
        if destination==self.repository.root or self.repository.root in destination.parents:
            raise ValueError('Export outside managed storage; the canonical library stays here.')

    def get(self, installation_id: str) -> InstalledBook:
        """Resolve one selected graph without parsing unrelated openings.

        Args:
            installation_id: Stable managed opening reference.

        Returns:
            Fresh selected snapshot and catalog preferences.

        Raises:
            ValueError: The opening is unavailable or removed.
            sqlite3.Error: Reading the selected graph fails.
        """
        from opening_library_metadata import resolve_managed_book
        return resolve_managed_book(self.repository, installation_id)

    @staticmethod
    def preview_import(path):
        return inspect_package(path,allow_empty=True)

    def import_book(self, path, preview, book_id):
        current=inspect_package(path)
        if current!=preview:raise ValueError('Import file changed; inspect a new preview.')
        snapshot=next((s for s in current.books if s.book.book_id==book_id),None)
        if snapshot is None:raise ValueError('Choose a previewed book.')
        provenance=dict(imported_filename=current.filename,imported_at=datetime.now(timezone.utc).isoformat(),
            source_file_sha256=current.file_sha256,original_book_id=book_id,
            original_content_identity=semantic_identity(snapshot))
        return self._install(snapshot,'imported',provenance,deduplicate=True)

    def _install(self,snapshot,origin,provenance,*,deduplicate):
        identifier=str(uuid.uuid4());destination=self.repository.path(identifier)
        created=False
        try:
            with self.repository.write() as db:
                if deduplicate:
                    expected=semantic_identity(snapshot)
                    for row in db.execute('SELECT installation_id FROM installed_books'):
                        existing_library=self.get_library(row[0])
                        for existing in existing_library.books:
                            if semantic_identity(existing.snapshot)==expected:return ImportResult(existing.installation_id,True)
                write_package(snapshot,destination);created=True
                db.execute('INSERT INTO installed_books VALUES (?,1,0,?,?)',
                           (identifier,origin,json.dumps(provenance,sort_keys=True)))
            return ImportResult(identifier,False)
        except BaseException:
            if created:destination.unlink()
            raise

    def export_book(self, installation_id, destination):
        item=self.get(installation_id)
        if item.snapshot is None:raise ValueError(item.error)
        destination=Path(destination).absolute()
        if destination==self.repository.root or self.repository.root in destination.parents:
            raise ValueError('Export outside managed storage; use Clone to create an installed copy.')
        write_package(item.snapshot,destination)
        exported=inspect_package(destination).books[0]
        if semantic_identity(exported)!=semantic_identity(item.snapshot):
            raise ValueError('Export verification failed.')
        return semantic_identity(exported)

    def clone_book(self, installation_id, name):
        item=self.get(installation_id)
        if item.snapshot is None:raise ValueError(item.error)
        metadata=json.loads(item.snapshot.book.metadata_json)
        source=dict(installation_id=installation_id,book_id=item.snapshot.book.book_id,
                    content_identity=semantic_identity(item.snapshot),version=item.snapshot.book.version)
        from chesswizard_version import VERSION
        metadata.update(book_uuid=str(uuid.uuid4()),cloned_from=source,created_with_chesswizard=VERSION)
        details=BookDetails(name, item.snapshot.book.description,item.snapshot.book.version,
                            item.snapshot.book.status,json.dumps(metadata))
        snapshot=replace(item.snapshot,book=replace(item.snapshot.book,**asdict(details)))
        return self._install(snapshot,'user clone',source,deduplicate=False)

    def update_metadata(self, installation_id, *, author='', license='', description=None):
        item=self.get(installation_id)
        if item.snapshot is None:raise ValueError(item.error)
        from opening_book_models import text
        text(author,'Author');text(license,'License')
        metadata=json.loads(item.snapshot.book.metadata_json)
        metadata.update(author=author,license=license)
        details=BookDetails(item.snapshot.book.name,description if description is not None else item.snapshot.book.description,
            item.snapshot.book.version,item.snapshot.book.status,json.dumps(metadata))
        repo=OpeningBookRepository.open(item.path)
        try:repo.update_book(item.snapshot.book.book_id,details)
        finally:repo.close()

    def _preferences(self,db,library_id):
        row=db.execute('SELECT provenance_json FROM installed_books WHERE installation_id=?',(library_id,)).fetchone()
        if row is None:raise ValueError('Library no longer managed.')
        return json.loads(row[0])

    def set_enabled(self, installation_id, enabled):
        if type(enabled) is not bool:raise ValueError('Expected Boolean.')
        item=self.get(installation_id)
        with self.repository.write() as db:
            data=self._preferences(db,item.library_id)
            data.setdefault('book_enabled',{})[str(item.snapshot.book.book_id)]=enabled
            db.execute('UPDATE installed_books SET provenance_json=? WHERE installation_id=?',(json.dumps(data,sort_keys=True),item.library_id))

    def set_primary(self, installation_id=None):
        item=self.get(installation_id) if installation_id is not None else None
        with self.repository.write() as db:
            db.execute('UPDATE installed_books SET is_primary=0 WHERE is_primary=1')
            if item is not None:
                data=self._preferences(db,item.library_id);data['primary_book_id']=item.snapshot.book.book_id
                db.execute('UPDATE installed_books SET is_primary=1,provenance_json=? WHERE installation_id=?',(json.dumps(data,sort_keys=True),item.library_id))

    def set_status(self,installation_id,status):
        item=self.get(installation_id);book=item.snapshot.book
        details=BookDetails(book.name,book.description,book.version,status,book.metadata_json)
        repo=OpeningBookRepository.open(item.path)
        try:repo.update_book(book.book_id,details)
        finally:repo.close()

    def preview_removal(self, installation_id, *, selected_id=None):
        item=self.get(installation_id)
        if item.snapshot is None:raise ValueError('Restore the unavailable file before removing its installation.')
        return RemovalPreview(installation_id,item.snapshot.identity,item.label,item.enabled,item.primary,
                              item.origin,selected_id==installation_id)

    def remove(self, preview, *, clear_primary=False):
        if preview.primary and not clear_primary:raise ValueError('Explicitly clear or replace the primary reference first.')
        current=self.preview_removal(preview.installation_id,selected_id=preview.installation_id if preview.selected_in_review else None)
        if current!=preview:raise ValueError('Book changed; review a fresh removal preview.')
        item=self.get(preview.installation_id)
        library=self.get_library(item.library_id)
        if len(library.books)>1:
            self.set_status(item.installation_id,'archived')
            if item.primary:self.set_primary(None)
            return item.path
        # Uninstall by archiving, preserving recoverable authored work and provenance.
        from theme_core.assets import reject_links
        source=item.path
        archive=self.repository.root/'removed';reject_links(archive);archive.mkdir(exist_ok=True)
        destination=archive/(item.library_id+'.cwbook');reject_links(destination)
        if destination.exists():raise ValueError('Removal archive already exists.')
        moved=False
        try:
            with self.repository.write() as db:
                row=db.execute('SELECT enabled,is_primary FROM installed_books WHERE installation_id=?',(item.library_id,)).fetchone()
                if bool(row[1])!=preview.primary or inspect_package(source).books[0].identity!=preview.content_identity:
                    raise ValueError('Removal preview is stale.')
                source.rename(destination);moved=True
                db.execute('INSERT INTO removed_books(installation_id,provenance_json,origin) SELECT installation_id,provenance_json,origin FROM installed_books WHERE installation_id=?',(item.library_id,))
                db.execute('DELETE FROM installed_books WHERE installation_id=?',(item.library_id,))
        except BaseException:
            if moved:destination.rename(source)
            raise
        return destination

    def delete_book(self, preview):
        """Remove a book from active references, retaining its rows for recovery.

        Keeping the original graph also reserves its ID forever. Deleting the
        highest SQLite book ID must never let a new book inherit old references.
        """
        item=self.get(preview.installation_id)
        with self.repository.write() as db:
            current=self.preview_removal(preview.installation_id, selected_id=preview.installation_id if preview.selected_in_review else None)
            if current!=preview:raise ValueError("Book changed; review a fresh deletion confirmation.")
            data=self._preferences(db,item.library_id)
            deleted=set(data.get('studio_deleted_books',()))
            deleted.add(item.snapshot.book.book_id)
            data['studio_deleted_books']=sorted(deleted)
            if item.primary:data.pop('primary_book_id',None)
            db.execute('UPDATE installed_books SET is_primary=?,provenance_json=? WHERE installation_id=?',
                       (0 if item.primary else int(any(b.primary for b in self.get_library(item.library_id).books)),
                        json.dumps(data,sort_keys=True),item.library_id))
