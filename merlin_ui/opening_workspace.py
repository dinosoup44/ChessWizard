"""In-place multi-game opening workspace; all aggregation runs on read-only workers."""
from opening_library_models import InstalledBook
from queue import SimpleQueue
import threading
import tkinter as tk
from tkinter import ttk, font
from analysis_control import AnalysisCancelled
from opening_analysis_service import OpeningAnalysisService
from opening_intelligence_lookup import OpeningBookLookup
from opening_intelligence_models import OpeningGameAssessment
from opening_intelligence_presentation import context_text
from opening_workspace import opening_game_sort, opening_metric_text
from opening_review_navigation import OpeningOccurrence, OpeningGameSelection, deviation_occurrences, variation_occurrences
from merlin_ui.opening_occurrences import OpeningOccurrences
from merlin_ui.notebook import MerlinNotebook
from merlin_ui.information_panel import style_information_tree
from merlin_ui.review_splitter import ReviewSplitter
from merlin_ui.opening_review_panel import OpeningReviewPanel


class OpeningWorkspace(ttk.Frame):
    """Keep multi-game opening context beside the existing single board.

    Args:
        parent: Main right-side notebook.
        review: Shared loaded-game coordinator.
    """
    def __init__(self, parent: tk.Misc, review: object) -> None:
        """Build a background-driven workspace without starting any engine.

        Args:
            parent: Right-side notebook.
            review: Existing board/game state.
        """
        super().__init__(parent)
        self.review=review;self.item=self.result=self.key=self.result_key=None
        self.busy=self.closed=False;self.minimum_id=None;self.generation=0;self.cancel=threading.Event()
        self.browsing = False
        self.selected_game: OpeningGameSelection | None = None
        self.events=SimpleQueue();self.worker=None;self.sort_column='date';self.descending=True
        self.columnconfigure(0,weight=1);self.rowconfigure(3,weight=1)
        self.header=ttk.Frame(self);self.header.grid(row=0,column=0,sticky='ew',padx=6,pady=6)
        self.metrics=ttk.Label(self,text='Choose an Opening.',wraplength=570,justify='left')
        self.metrics.grid(row=1,column=0,sticky='ew',padx=6)
        self.status=ttk.Label(self,text='',wraplength=570)
        self.status.grid(row=2,column=0,sticky='ew',padx=6,pady=3)
        from merlin_ui.layout_metrics import AutomaticSizeGuard
        self._automatic_size_guard=AutomaticSizeGuard()
        self.splitter=ReviewSplitter(self,fraction=.65,on_resize=lambda fraction:None,background=review.ui_skin['panel_bg'])
        self.splitter.grid(row=3,column=0,sticky='nsew',padx=5)
        self.upper=ttk.Frame(self.splitter)
        self.upper.columnconfigure(0,weight=1);self.upper.rowconfigure(0,weight=1)
        self.summary_splitter = ReviewSplitter(self.upper, fraction=.5,
            on_resize=lambda fraction: None, background=review.ui_skin['panel_bg'])
        self.summary_splitter.grid(row=0, column=0, sticky='nsew')
        self.tabs=MerlinNotebook(self.summary_splitter)
        self.affected=OpeningOccurrences(self.summary_splitter,self.select_game)
        self.summary_splitter.add_panels(self.tabs,self.affected)
        self.selected_game_label=ttk.Label(self.upper,text='Select a game, then an Opening Moment.')
        self.selected_game_label.grid(row=1,column=0,sticky='ew',padx=4,pady=2)
        self.group_rows={};self.refresh_notice=False;self._affected_key=None
        self.detail=OpeningReviewPanel(self.splitter,review)
        self.splitter.add_panels(self.upper,self.detail)
        self.games_grid=self._table('Games',('game','date','opponent','result','variation','accuracy','adherence','user','opponent_deviation','reentry'),
            ('Game ID','Date','Opponent','Result','Variation','Opening Accuracy','Opening Adherence','First User Deviation','First Opponent Deviation','Re-entry'))
        for column in self.games_grid['columns']:
            self.games_grid.heading(column,command=lambda name=column:self.sort_games(name))
        self.games_grid.bind('<<TreeviewSelect>>',self._choose_game)
        self.variations=self._table('Variations',('variation','games','accuracy','coverage','adherence'),('Variation','Games','Opening Accuracy','Scored / eligible','Opening Adherence'))
        self.deviations=self._table('Deviations',('party','move','opening','games','count','loss','variation'),('Who','Actual move','Opening move','Games','Visits','Mean loss (cp)','Variation'))
        self.gaps=self._table('Opening Gaps',('move','games','count','variation'),('Opponent move','Games','Visits','Variation'))
        for tree in (self.variations,self.deviations,self.gaps):
            tree.bind('<<TreeviewSelect>>',lambda event,t=tree:self._choose_summary(t))
            for column in tree['columns']:
                tree.heading(column,command=lambda t=tree,c=column:self._sort_summary(t,c))
        self.tabs.bind('<<NotebookTabChanged>>',self._context_changed)
        self.summary_sort={}
        self.bind('<Configure>',self._resize)
        self.bind('<Map>',self._mapped)
        self.bind('<Destroy>',self._destroyed)
        self.poll_id=self.after(60,self._poll)

    def _table(self, title: str, columns: tuple[str, ...], labels: tuple[str, ...]) -> ttk.Treeview:
        frame=ttk.Frame(self.tabs);frame.rowconfigure(0,weight=1);frame.columnconfigure(0,weight=1)
        tree=ttk.Treeview(frame,columns=columns,show='headings',height=6,selectmode='browse')
        style_information_tree(tree)
        for column,label in zip(columns,labels):
            tree.heading(column,text=label)
            width={'game':60,'date':95,'opponent':120,'result':60,'variation':180}.get(column,120)
            tree.column(column,width=width,minwidth=45,stretch=False)
        tree.grid(row=0,column=0,sticky='nsew')
        vertical=ttk.Scrollbar(frame,command=tree.yview);vertical.grid(row=0,column=1,sticky='ns')
        horizontal=ttk.Scrollbar(frame,orient='horizontal',command=tree.xview);horizontal.grid(row=1,column=0,sticky='ew')
        tree.configure(yscrollcommand=vertical.set,xscrollcommand=horizontal.set)
        self.tabs.add(frame,text=title)
        return tree

    def _mapped(self, event: tk.Event) -> None:
        if event.widget is self:
            self.splitter._schedule_layout()
            self.summary_splitter._schedule_layout()
            if self.minimum_id is None:self.minimum_id=self.after_idle(self._minimums)

    def _resize(self, event: tk.Event) -> None:
        if event.widget is not self:return
        for label in (self.metrics,self.status):label.configure(wraplength=max(180,event.width-18))
        if self.minimum_id is None:self.minimum_id=self.after_idle(self._minimums)

    def _minimums(self) -> None:
        self.minimum_id=None
        if not self.winfo_ismapped():return
        row=font.nametofont('TkFixedFont',root=self).metrics('linespace')+8
        tree=self._active_tree()
        top=self.tabs.winfo_reqheight()-tree.winfo_reqheight()+3*row
        middle=self.affected.winfo_reqheight()-self.affected.tree.winfo_reqheight()+3*row
        lower=self.detail.winfo_reqheight()-self.detail.events.winfo_reqheight()+3*row
        upper=top+self.selected_game_label.winfo_reqheight()+4
        if tree is not self.games_grid:
            upper+=middle+self.summary_splitter.sash_size
        sizes=(upper,lower)
        context=(self.winfo_width(),float(self.tk.call('tk','scaling')),str(tree))
        was_blocked=self._automatic_size_guard.blocked
        if not self._automatic_size_guard.allow(context,sizes):
            if not was_blocked:
                import logging
                logging.getLogger(__name__).warning('Automatic opening pane resizing paused: unstable size sequence.')
            return
        for splitter, minimums in ((self.summary_splitter,(top,middle)),(self.splitter,sizes)):
            if splitter.minimum_heights != minimums:
                splitter.minimum_heights=minimums
                for pane,height in zip(splitter.panes(),minimums):
                    splitter.paneconfigure(pane,minsize=height)
                splitter._schedule_layout()

    def set_book(self, item: InstalledBook | None, *, lookup: OpeningBookLookup | None = None,
                 refresh_notice: bool = False) -> None:
        """Invalidate changed opening/owner contexts while preserving the loaded game.

        Args:
            item: Resolved managed opening, or None for an explicit empty selection.
            lookup: Optional index already prepared by the selection worker.
            refresh_notice: Preserve the visible explanation of an edited opening.
        """
        owner=self.review.current_game.get('user_id') if self.review.current_game else None
        key=(item.installation_id,item.snapshot.identity,owner) if item else None
        if key==self.key:return
        self.lookup=lookup
        self.refresh_notice=refresh_notice or bool(self.item and item and self.item.installation_id==item.installation_id)
        self.cancel.set();self.generation+=1
        self.item,self.key,self.result,self.result_key=item,key,None,None
        for table in (self.games_grid,self.variations,self.deviations,self.gaps):table.delete(*table.get_children())
        self.group_rows={};self.selected_game=None;self.browsing=False
        self.selected_game_label.configure(text='Select a game, then an Opening Moment to navigate.')
        self._affected_key=None
        self.affected.show((),'Select a summary to see affected games.')
        self.metrics.configure(text='Choose an Opening.' if item is None else 'Opening metrics have not been computed for this opening.')
        self.status.configure(text='Opening changed — refreshing review…' if self.refresh_notice else '')
        self.request_analysis()

    def request_analysis(self, *, force: bool = False) -> None:
        """Aggregate stored facts on a worker; selection never requests Stockfish.

        Args:
            force: Explicitly recompute the current opening/history snapshot.
        """
        if self.closed or self.item is None:return
        if self.review.workspace_tabs.select()!=str(self):return
        if self.item.snapshot.book.repertoire_side is None:
            self.status.configure(text='Set Opening Side in Studio → Opening Details (White, Black or Both / Reference).')
            return
        if force:
            self.result_key=None;self.cancel.set();self.generation+=1
        if self.busy or self.result_key==self.key:return
        self.generation+=1;token=self.generation;self.cancel=threading.Event();self.busy=True
        self.status.configure(text=('Opening changed — refreshing review… ' if self.refresh_notice else '')+f'Analyzing {self.item.snapshot.book.name}…')
        item=self.item;prepared_lookup=getattr(self,'lookup',None)
        owner=self.key[-1];key=self.key;cancel=self.cancel;events=self.events
        service=OpeningAnalysisService(self.review.database_path)
        def work() -> None:
            try:
                lookup=prepared_lookup or OpeningBookLookup(item.snapshot,library_identity=item.library_id)
                events.put((token,key,'result',service.analyze_lookup(lookup,user_id=owner,cancel=cancel,
                progress=lambda value:events.put((token,key,'progress',value)))))
            except AnalysisCancelled:events.put((token,key,'cancelled',None))
            except Exception as error:events.put((token,key,'error',str(error)))
        self.worker=threading.Thread(target=work,name='opening-review-facts',daemon=False);self.worker.start()

    def _poll(self) -> None:
        if self.closed:return
        restart=False
        while not self.events.empty():
            token,key,kind,value=self.events.get()
            if kind!='progress':self.busy=False
            if token!=self.generation or key!=self.key:
                if kind!='progress':restart=True
                continue
            if kind=='progress':
                count=f' · {value.completed}/{value.total} games examined' if value.total else ''
                notice='Opening changed — refreshing review… ' if self.refresh_notice else ''
                self.status.configure(text=notice+f'Analyzing {self.item.snapshot.book.name}… {value.phase}{count}')
                continue
            if kind=='result':
                self.result=value;self.result_key=key;self.refresh_notice=False;self._populate()
                self.review.opening_reference.refresh_summary()
            elif kind=='error':
                self.result_key=key;self.status.configure(text='Opening analysis unavailable: '+value)
            else:self.status.configure(text='Opening computation cancelled.')
        if restart:self.request_analysis()
        self.poll_id=self.after(60,self._poll)

    def _populate(self) -> None:
        result=self.result
        self.metrics.configure(text=opening_metric_text(result))
        self.status.configure(text=('No matching games for this opening and Opening Side.' if not result.games else
            f'{len(result.games)} matching games · {result.matching_set.repertoire_side.value} Opening Side · stored facts only.')
            +f' Excluded {len(result.matching_set.exclusions)}; unavailable/invalid {len(result.matching_set.errors)}.')
        if self.selected_game:
            gid=self.selected_game.game.context.game_id
            game=next((g for g in result.games if g.context.game_id==gid),None)
            self.selected_game=OpeningGameSelection(game,(OpeningOccurrence(game),)) if game else None
        self._render_games()
        for table in (self.variations,self.deviations,self.gaps):table.delete(*table.get_children())
        number=lambda n:'—' if n is None else f'{n:.2f}'
        self.group_rows={}
        for index,row in enumerate(result.variation_accuracy):
            key=f'variation:{index}'
            self.group_rows[key]=variation_occurrences(result,row.game_ids)
            self.variations.insert('','end',iid=key,values=(context_text(row.context,result.matching_set.provenance.book_name),len(row.game_ids),number(row.accuracy.quality.accuracy)+' ('+row.accuracy.status+')',
                f'{row.accuracy.quality.evaluated_moves}/{row.accuracy.quality.total_moves}',f'{row.adherence.in_book_moves}/{row.adherence.opportunities}'))
        for group in (*result.user_deviations,*result.opponent_deviations):
            for move in group.moves:
                key=f'deviation:{len(self.group_rows)}'
                rows=deviation_occurrences(result,group.position,move.move_uci,group.party)
                self.group_rows[key]=rows
                self.deviations.insert('','end',iid=key,values=('You' if group.party=='user' else 'Opponent',
                    ' / '.join(dict.fromkeys(r.move.move_label for r in rows)),
                    ', '.join(m.san for m in group.alternatives) or '—',len(move.game_ids),move.count,
                    number(move.quality.average_loss_cp),
                    ' | '.join(context_text(c,result.matching_set.provenance.book_name) for c in group.variations)))
        for index,gap in enumerate(result.repertoire_gaps):
            key=f'gap:{index}'
            self.group_rows[key]=deviation_occurrences(result,gap.position,gap.move_uci,'opponent')
            self.gaps.insert('','end',iid=key,values=(gap.move_san,len(gap.game_ids),gap.count,
                ' | '.join(context_text(c,result.matching_set.provenance.book_name) for c in gap.variations)))
        self._context_changed()

    def _render_games(self) -> None:
        self.games_grid.delete(*self.games_grid.get_children())
        if self.result is None:return
        for game in opening_game_sort(self.result.games,self.sort_column,self.descending):
            c=game.context;q=game.accuracy.user
            score='—' if q is None or q.quality.accuracy is None else f'{q.quality.accuracy:.2f}'+(' (partial)' if not q.quality.complete else '')
            user=game.first_user_deviation;other=game.first_opponent_deviation
            self.games_grid.insert('','end',iid=str(c.game_id),values=(c.game_id,c.played_at[:10].replace('.','-') if c.played_at else 'Unknown',c.black_username if c.user_color=='white' else c.white_username,
                c.result,context_text(game.book.final_variation,game.book.provenance.book_name),score,
                f'{game.adherence.in_book_moves}/{game.adherence.opportunities}'+(f' · {game.adherence.percentage:.2f}%' if game.adherence.percentage is not None else ''),
                user.book.move_label if user else '—',other.book.move_label if other else '—','Yes' if game.book.reentry_count else ''))
        if self.selected_game:
            gid=str(self.selected_game.game.context.game_id)
            if self.games_grid.exists(gid):self.games_grid.selection_set(gid)

    def refresh_detail(self, assessment: OpeningGameAssessment | None,
                       lookup: OpeningBookLookup | None, library_name: str = '') -> None:
        """Refresh browsing facts independently of the displayed board assessment.

        Args:
            assessment: Current displayed game's fallback facts.
            lookup: Current opening index, shared across games.
            library_name: Friendly library context.
        """
        plies=None
        if self.browsing:
            assessment=self.selected_game.game.book if self.selected_game else None
            plies=self.selected_game.plies if self.selected_game else None
        self.detail.show(assessment,lookup,library_name,plies=plies)
        if self.selected_game:
            context=self.selected_game.game.context
            opponent=context.black_username if context.user_color=='white' else context.white_username
            self.selected_game_label.configure(text=f'Selected game: {context.game_id} · vs {opponent}')
        else:
            self.selected_game_label.configure(text='Select a game, then an Opening Moment to navigate.')

    def select_game(self, selection: OpeningGameSelection) -> None:
        """Select an exact game/occurrence filter without changing the displayed board.

        Args:
            selection: Immutable facts belonging to the current opening result.
        """
        self.browsing=True
        self.selected_game=selection
        self.review.opening_reference.refresh_summary()

    def sort_games(self, column: str) -> None:
        """Sort the current matching set without changing the loaded game.

        Args:
            column: Supported grid column identity.
        """
        self.descending=not self.descending if column==self.sort_column else False
        self.sort_column=column
        if self.result:
            visible=set(self.games_grid.get_children())
            ordered=opening_game_sort(self.result.games,column,self.descending)
            for index,game in enumerate(g for g in ordered if str(g.context.game_id) in visible):
                self.games_grid.move(str(game.context.game_id),'',index)

    def _choose_game(self, event: tk.Event | None = None) -> None:
        if self._active_tree() is not self.games_grid:return
        selected=self.games_grid.selection()
        if not selected or self.result is None:return
        game=next((g for g in self.result.games if str(g.context.game_id)==selected[0]),None)
        if game:self.select_game(OpeningGameSelection(game,(OpeningOccurrence(game),)))

    def _active_tree(self) -> ttk.Treeview:
        return next((tree for tree in (self.games_grid,self.variations,self.deviations,self.gaps)
                     if str(tree.master)==self.tabs.select()),self.games_grid)

    def _context_changed(self, event: tk.Event | None = None) -> None:
        tree=self._active_tree()
        if tree is self.games_grid:
            self.summary_splitter.paneconfigure(self.affected,hide=True)
            self._choose_game()
        else:
            self.summary_splitter.paneconfigure(self.affected,hide=False)
            self._choose_summary(tree)
        self.summary_splitter._schedule_layout()
        if self.minimum_id is None:self.minimum_id=self.after_idle(self._minimums)

    def _choose_summary(self, tree: ttk.Treeview) -> None:
        if tree is not self._active_tree():return
        selected=tree.selection()
        key=(self.result.result_identity if self.result else None,str(tree),selected)
        if key==self._affected_key:return
        self._affected_key=key
        rows=self.group_rows.get(selected[0],()) if selected else ()
        caption=(f'{len(rows)} occurrences · '+('Coverage gap; no authored reply after the opponent move.'
                 if tree is self.gaps else 'Select a game to see its Opening Moments.'))
        if tree is self.variations:caption=f'{len(rows)} affected games in this variation'
        self.affected.show(rows,caption if rows else 'Select a summary to see affected games.')
        self.selected_game=None;self.browsing=True
        self.review.opening_reference.refresh_summary()

    def _sort_summary(self, tree: ttk.Treeview, column: str) -> None:
        reverse=not self.summary_sort.get((str(tree),column),False)
        self.summary_sort[str(tree),column]=reverse
        def key(item: str) -> tuple:
            value=tree.set(item,column)
            try:return (0,float(value))
            except ValueError:return (1,value.casefold())
        for index,item in enumerate(sorted(tree.get_children(),key=key,reverse=reverse)):
            tree.move(item,'',index)

    def close(self) -> None:
        """Cancel the read-only worker and detach callbacks without changing data."""
        if not self.closed:
            self.closed=True;self.cancel.set();self.after_cancel(self.poll_id)
            if self.minimum_id is not None:self.after_cancel(self.minimum_id)

    def _destroyed(self, event: tk.Event) -> None:
        if event.widget is self:self.close()
