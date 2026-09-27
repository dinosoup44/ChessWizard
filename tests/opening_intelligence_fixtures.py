"""Original isolated opening knowledge; no imported instructional prose."""
import chess
import chess.pgn
from opening_book_models import BookDetails,MoveDetails
from opening_book_session import OpeningBookSession
from tests.opening_book_fixtures import add_line

FRENCH_CASES={
    'trunk':'e4 e6 d4 d5',
    'advance':'e4 e6 d4 d5 e5 c5 c3 Nc6 Nf3',
    'exchange':'e4 e6 d4 d5 exd5 exd5 Nf3',
    'tarrasch':'e4 e6 d4 d5 Nd2 c5',
    'nested':'e4 e6 d4 d5 Nc3 Bb4 e5 c5',
    'user_deviation':'e4 e6 d4 d5 a3',
    'opponent_deviation':'e4 e6 d4 d5 e5 a6',
    'legal_outside':'e4 e6 d4 d5 Nc3 Nf6 Bg5',
    'reentry':'d4 e6 e4 d5 e5 c5 c3 Nc6 Nf3',
    'never_entered':'b3 e5 Bb2 Nc6',
    'nonpreferred':'e4 e6 d4 d5 exd5 exd5',
}


def ucis(line,fen=chess.STARTING_FEN):
    board=chess.Board(fen);result=[]
    for san in line.split():
        move=board.parse_san(san);result.append(move.uci());board.push(move)
    return tuple(result)


def french_book(service):
    bid=service.create_book(BookDetails('The French','Original application fixture'))
    session=OpeningBookSession(service,bid)
    lines=[('e4 e6 d4 d5 e5 c5 c3 Nc6 Nf3',4,'Advance Variation'),
           ('e4 e6 d4 d5 exd5 exd5 Nf3',4,'Exchange Variation'),
           ('e4 e6 d4 d5 Nd2 c5',4,'Tarrasch Variation'),
           ('e4 e6 d4 d5 Nc3 Bb4 e5 c5',4,'Nc3 branches'),
           ('e4 e6 d4 d5 Nc3 Nf6',5,'Classical Variation')]
    for line,index,name in lines:
        add_line(session,line)
        service.edit_move(bid,session.history[index],MoveDetails(weight=80 if name=='Advance Variation' else 40,
            preferred=name=='Advance Variation',variation_name=name))
        session.refresh()
    add_line(session,'e4 e6 d4 d5 Nc3 Bb4 e5 c5')
    service.edit_move(bid,session.history[5],MoveDetails(variation_name='Winawer Variation'))
    service.edit_move(bid,session.history[6],MoveDetails(variation_name='Advance structure'))
    session.refresh()
    return bid


def transposed_book(service):
    bid=service.create_book(BookDetails('Transposition fixture'))
    session=OpeningBookSession(service,bid)
    for line,name in [('d4 Nf6 Nf3 d5 Nc3','Pawn route'),('Nf3 Nf6 d4 d5 Nc3','Knight route')]:
        add_line(session,line)
        service.edit_move(bid,session.history[0],MoveDetails(variation_name=name));session.refresh()
    return bid


def pgn(line,identity):
    game=chess.pgn.Game();game.headers.update({'White':'Example_User','Black':'Opponent','Result':'1-0',
        'UTCDate':'2026.09.20','UTCTime':'12:00:00','Link':f'https://www.chess.com/game/live/{identity}'})
    node=game
    for uci in ucis(line):node=node.add_variation(chess.Move.from_uci(uci))
    return str(game)
