"""Original demonstration theory, authored one legal pending move at a time."""
from opening_book_models import BookDetails, MoveDetails
from opening_book_session import OpeningBookSession

PROOF_LINES = (
    "e4 e5 Nf3 Nc6 Bb5 a6",
    "e4 e5 Bc4 Nf6 d3",
    "e4 c5 Nf3 d6 d4 cxd4 Nxd4",
    "e4 c5 Nc3 Nc6",
    "e4 c6 d4 d5",
    "d4 Nf6 Nf3 d5 c4",
    "Nf3 Nf6 d4",
)


def add_line(session, line):
    session.discard();session.root()
    for notation in line.split():
        move=session.board.parse_san(notation)
        edge=next((m for m in session.snapshot.branches(session.position_id) if m.move_uci==move.uci()),None)
        if edge:
            session.follow(edge.move_id)
        else:
            session.stage(move.uci());session.save(MoveDetails())


def author_proof_book(service):
    book_id=service.create_book(BookDetails("Original V1 proof book","Manually authored functional fixture; not opening advice."))
    session=OpeningBookSession(service,book_id)
    for line in PROOF_LINES:add_line(session,line)
    session.root()
    root=session.position_id
    e4=next(m for m in session.snapshot.branches(root) if m.san=="e4")
    service.edit_move(book_id,e4.move_id,MoveDetails(100,True,True,"An original test branch.",
                                                  "Explore several legal replies; no engine claim.",'{"tags":["fixture","main"]}'))
    service.repository.set_position_note(book_id,root,"Choose a central pawn move or develop a knight.",
                                         '{"provenance":"original isolated fixture"}')
    session.refresh()
    return book_id



FRENCH_LINES = {
    "e4 e6 d4 d5 e5": "Advance Variation",
    "e4 e6 d4 d5 exd5": "Exchange Variation",
    "e4 e6 d4 d5 Nd2": "Tarrasch Variation",
    "e4 e6 d4 d5 Nc3 Bb4": "Winawer Variation",
    "e4 e6 d4 d5 Nc3 Nf6": "Classical Variation",
}


def author_french_book(service, *, named=True):
    """Original owner-acceptance fixture, separate from any user library."""
    book_id = service.create_book(BookDetails("The French"))
    session = OpeningBookSession(service, book_id)
    for line, name in FRENCH_LINES.items():
        add_line(session, line)
        if named:
            service.edit_move(book_id, session.history[-1], MoveDetails(
                variation_name=name, variation_description="An original authoring/navigation example."))
            session.refresh()
    return book_id
