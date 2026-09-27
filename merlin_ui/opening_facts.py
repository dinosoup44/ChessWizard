"""Minimal owner-validation window; all book knowledge comes from shared services."""
import sqlite3
from tkinter import ttk
from merlin_ui.information_panel import InformationPanel
from opening_intelligence_review import OpeningReviewSession
from opening_intelligence_presentation import opening_summary


class OpeningFactsWindow:
    def __init__(self,root,review):
        self.root,self.review=root,review
        self.session=OpeningReviewSession(review.database_path)
        root.title('Opening book facts — read only');root.geometry('660x580')
        toolbar=ttk.Frame(root);toolbar.pack(fill='x',padx=8,pady=8)
        ttk.Button(toolbar,text='Manage Books…',command=review.open_opening_library).pack(side='left')
        ttk.Button(toolbar,text='Refresh',command=lambda:self.refresh(force=True)).pack(side='left',padx=5)
        self.picker=ttk.Combobox(root,state='disabled');self.picker.pack(fill='x',padx=8)
        self.info=InformationPanel(root);self.info.pack(fill='both',expand=True,padx=8,pady=8)
        self.info.show('Choose an installed Opening Book in Game Review.')

    def use_installed(self,library,installation_id):
        if installation_id is None:
            self.session=OpeningReviewSession(self.review.database_path)
            self.picker.set('No book / None')
            self.info.show('No active opening reference. Choose an installed book in Game Review.');return
        item=library.get(installation_id)
        if item.snapshot is None:raise ValueError(item.error)
        self.picker.set(item.label)
        if self.session.library_path!=item.path or self.session.book_id!=item.snapshot.book.book_id:
            self.session=OpeningReviewSession(self.review.database_path)
            self.session.select(item.path,item.snapshot.book.book_id,library_identity=item.library_id)
        self.refresh()

    def refresh(self,*,force=False):
        if self.session.library_path is None:return
        try:
            assessment=self.session.refresh(self.review.current_game,self.review.moves,force=force)
            self.info.show(opening_summary(assessment,self.review.current_step,proof=self.review.line_playback is not None)
                           if assessment else 'No game selected.')
        except (ValueError,OSError,sqlite3.Error) as error:self.info.show('Opening facts unavailable: '+str(error))
