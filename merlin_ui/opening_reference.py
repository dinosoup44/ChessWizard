"""One flat managed-opening selector, preserving explicit session intent across games."""
from pathlib import Path
import sqlite3
import threading
from queue import SimpleQueue
from opening_library_metadata import library_fingerprint
import tkinter as tk
from tkinter import ttk
from opening_library_listing import managed_book_choices
from opening_library_reference import OpeningReferenceService
from opening_intelligence_review import OpeningReviewSession


class OpeningReferencePicker(ttk.Frame):
    """Present opening choices without exposing physical library containers.

    Args:
        parent: Opening Review header.
        review: Existing board/game coordinator.
    """
    def __init__(self, parent: tk.Misc, review: object) -> None:
        """Create idle opening controls and register committed-library notifications.

        Args:
            parent: Header container.
            review: Current Game Review view.
        """
        super().__init__(parent)
        self.review=review;self.service=OpeningReferenceService(review.database_path)
        self.selected_id=self.selected_library_id=self.game_id=None
        self.closed=False;self.generation=0;self.worker=None;self.pending=None
        self.events=SimpleQueue();self.load_key=None;self.loaded_item=None
        self.poll_id=self.after(20,self._poll)
        self.choices=();self.fingerprint=None;self.refreshing=False
        self.summary_session=OpeningReviewSession(review.database_path)
        self.columnconfigure(1,weight=1)
        ttk.Label(self,text='Opening:').grid(row=0,column=0,sticky='w',padx=(0,6))
        self.picker=ttk.Combobox(self,state='readonly',width=24,postcommand=self.refresh)
        self.picker.grid(row=0,column=1,sticky='ew')
        self.picker.set('Select an Opening')
        self.picker.bind('<<ComboboxSelected>>',self.select)
        ttk.Button(self,text='Refresh',command=self._refresh_all).grid(row=0,column=2,padx=4)
        self.status=ttk.Label(self,text='',wraplength=500)
        self.status.grid(row=1,column=0,columnspan=3,sticky='ew')
        from merlin_ui.opening_library_events import register
        register(self)
        self.bind('<Destroy>',self._destroyed)
        self.focus_pending=None
        self.focus_binding=review.root.bind('<FocusIn>',self.on_focus,add='+')

    def managed_root(self) -> Path:
        """Return the authoring notification namespace.

        Returns:
            Canonical managed library directory.
        """
        return self.service.library.repository.root

    def library_changed(self) -> None:
        """Refresh committed opening changes while retaining the selected identity."""
        self.refresh(force=True)

    def on_focus(self, event: tk.Event) -> None:
        """Coalesce focus notifications to one cheap catalog fingerprint check.

        Args:
            event: Desktop focus event.
        """
        if self.focus_pending is None:self.focus_pending=self.after_idle(self._focus_refresh)

    def _focus_refresh(self) -> None:
        self.focus_pending=None
        if self.winfo_exists():self.refresh()

    def _destroyed(self, event: tk.Event) -> None:
        if event.widget is self:
            from merlin_ui.opening_library_events import unregister
            unregister(self)
            self.closed=True;self.generation+=1;self.pending=None
            self.after_cancel(self.poll_id)
            if self.focus_pending is not None:self.after_cancel(self.focus_pending)
            self.review.root.unbind('<FocusIn>',self.focus_binding)

    def _refresh_all(self) -> None:
        self.refresh(force=True)
        self.review.opening_workspace.request_analysis(force=True)

    def refresh(self, *, force: bool = False) -> None:
        """Refresh cheap headers and schedule only an explicitly chosen opening.

        Args:
            force: Revalidate committed revisions, including externally edited files.
        """
        if self.refreshing or self.closed:return
        self.refreshing=True
        try:
            game=self.review.current_game
            gid=game['game_id'] if game else None
            fingerprint=library_fingerprint(self.service.library.repository)
            source_changed=fingerprint!=self.fingerprint
            changed=force or source_changed
            if changed:
                self.choices=managed_book_choices(self.service.library)
                self.picker.configure(values=['Select an Opening',*[c.label for c in self.choices]])
            manual=self.service.manual_selection
            selected=manual.book_reference_id if manual else None
            choice=next((c for c in self.choices if c.reference_id==selected),None)
            selection_changed=selected!=self.selected_id
            self.refresh_notice=bool(choice and not selection_changed and source_changed)
            self.selected_id=choice.reference_id if choice else None
            self.selected_library_id=choice.library_id if choice else manual.library_id if manual else None
            self.game_id,self.fingerprint=gid,fingerprint
            self.picker.current(next((i+1 for i,c in enumerate(self.choices) if c==choice),0))
            # Include loaded move content: changing a game under the same ID cannot
            # publish facts derived from an earlier displayed history.
            moves=tuple(dict(m) for m in self.review.moves)
            game_key=(dict(game),moves) if game else None
            key=(self.selected_id,fingerprint,game_key)
            if not force and key==self.load_key:return
            self.load_key=key;self.generation+=1
            self.summary_session=OpeningReviewSession(self.review.database_path)
            self.loaded_item=None
            if source_changed or selection_changed or choice is None:
                self.review.opening_workspace.set_book(None)
            self.review.opening_workspace.refresh_detail(None,None)
            if source_changed or selection_changed:
                self.review.opening_exploration=None
            self.review.refresh_board()
            if choice is None:
                self.pending=None
                self.status.configure(text='No opening selected. Choose an Opening to begin.' if self.choices else
                    'No managed openings yet. Create or import one in Opening Studio.')
                self.refresh_summary()
                return
            loading=('Opening changed — refreshing review… ' if self.refresh_notice else '')+f'Loading {choice.name}...'
            self.status.configure(text=loading)
            self.review.opening_workspace.status.configure(text=loading)
            self.pending=(self.generation,key,choice,dict(game) if game else None,moves)
            self._start_load()
        except (ValueError,OSError,sqlite3.Error) as error:
            self.generation+=1;self.pending=None;self.loaded_item=None
            self.status.configure(text=str(error))
            self.review.opening_panel.show(None,error=str(error))
            self.review.opening_workspace.set_book(None)
        finally:self.refreshing=False

    def _start_load(self) -> None:
        if self.closed or self.worker is not None or self.pending is None:return
        token,key,choice,game,moves=self.pending;self.pending=None
        library=self.service.library;database=self.review.database_path;events=self.events
        def work() -> None:
            try:
                item=library.get(choice.reference_id)
                session=OpeningReviewSession(database)
                session.select(item.path,item.snapshot.book.book_id,library_identity=item.library_id)
                session.refresh(game,moves)
                events.put((token,key,item,session,None))
            except Exception as error:
                events.put((token,key,None,None,str(error)))
        self.worker=threading.Thread(target=work,name='opening-selection',daemon=True)
        self.worker.start()

    def _poll(self) -> None:
        if self.closed:return
        while not self.events.empty():
            token,key,item,session,error=self.events.get()
            self.worker=None
            if token!=self.generation or key!=self.load_key:continue
            if library_fingerprint(self.service.library.repository)!=self.fingerprint:
                self.refresh(force=True)
                continue
            if error:
                self.status.configure(text='Opening unavailable: '+error)
                self.review.opening_panel.show(None,error='Opening facts unavailable: '+error)
                continue
            self.loaded_item=item;self.summary_session=session
            book=item.snapshot.book
            side=book.repertoire_side.value if book.repertoire_side else 'unspecified — set Opening Side in Studio Opening Details'
            self.status.configure(text=f'{book.status.capitalize()} · v{book.version} · Opening Side: {side}')
            self.review.opening_workspace.set_book(item,lookup=session.lookup,refresh_notice=self.refresh_notice)
            self.sync_facts()
        self._start_load()
        self.poll_id=self.after(20,self._poll)

    def select(self, event: tk.Event | None = None) -> None:
        """Keep an explicit opening or None choice until the owner changes it.

        Args:
            event: Optional combobox event.
        """
        index=self.picker.current()
        self.service.select(self.game_id,self.choices[index-1].reference_id if index>0 else None)
        self.refresh(force=True)

    def defaults(self) -> None:
        """Return to the unselected instructional state without automatic matching."""
        self.service.clear_selection();self.refresh(force=True)

    def refresh_summary(self) -> None:
        """Render completed facts only; navigation performs no graph or game reads."""
        session=self.summary_session
        if self.selected_id is None:
            self.review.opening_panel.show(None)
            if self.review.opening_exploration is not None:
                self.review.opening_exploration=None
                self.review.refresh_all()
            return
        if self.loaded_item is None:return
        assessment=session.assessment
        state=self.review.opening_exploration
        if state is not None and (assessment is None or not state.is_current(assessment)):
            self.review.opening_exploration=None
            self.review.refresh_all()
            return
        self.review.opening_workspace.refresh_detail(assessment,session.lookup,self.loaded_item.library_name)

    def sync_facts(self) -> None:
        """Refresh the single in-place opening context view."""
        self.refresh_summary()
        self.review.refresh_board()
