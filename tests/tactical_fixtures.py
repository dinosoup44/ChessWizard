"""Deterministic legal PV fixtures; synthetic scores are contract tests, not engine proof."""
import chess


def move_context(fen,played,move_id=1):
    board = chess.Board(fen)
    move = board.parse_uci(played)
    row = {"move_id":move_id,"game_id":1,"ply_number":1,"move_number":board.fullmove_number,
           "color":"white" if board.turn else "black","san_played":board.san(move),
           "uci_played":played,"fen_before":board.fen(),"source":"synthetic","source_game_id":"gold",
           "white_username":"white","black_username":"black"}
    board.push(move)
    row["fen_after"] = board.fen()
    return row


def scripted_evidence(row,prefix,cp=300):
    board = chess.Board(row["fen_before"])
    assert board.is_valid()
    color = board.turn
    fens,sans,ucis = [board.fen()],[],[]
    for san in prefix.split():
        move = board.parse_san(san)
        sans.append(board.san(move)); ucis.append(move.uci())
        board.push(move); fens.append(board.fen())
    seen = {" ".join(f.split()[:4]) for f in fens}
    while len(sans) < 20:
        for move in sorted(board.legal_moves,key=lambda m:(board.piece_type_at(m.from_square)!=chess.PAWN,m.uci())):
            if board.is_capture(move) or board.gives_check(move) or move.promotion:
                continue
            after = board.copy(stack=False); after.push(move)
            key = " ".join(after.fen().split()[:4])
            if key not in seen:
                break
        else:
            raise AssertionError("Fixture lacks quiet continuation")
        sans.append(board.san(move)); ucis.append(move.uci())
        board.push(move); fens.append(board.fen()); seen.add(key)
    indices = {fen:i for i,fen in enumerate(fens)}
    def evaluate(fen,profile):
        score = 0 if fen==row["fen_after"] else cp if fen in indices else -1000
        i = indices.get(fen,len(sans))
        return {"score_type":"cp","score_cp":score if color else -score,"mate":None,
                "score_pov":"white","principal_variation":" ".join(sans[i:]),
                "best_move_uci":ucis[i] if i<len(ucis) else None,"cache_id":None}
    return evaluate,fens
