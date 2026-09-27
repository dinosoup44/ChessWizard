"""Legal, bounded exchange detail from supplied evidence; no engine or database I/O."""
from dataclasses import asdict, dataclass
import chess
from analysis_settings import Settings, setting, MaterialValues
from board_analysis import material_balance
from stored_line import StoredLine
from tactical_proof import play_proof_move

@dataclass(frozen=True)
class ExchangePresentationSettings(Settings):
    max_plies: int = setting(12,'Maximum additional plies in exchange detail; not an admission/proof budget.',minimum=1,maximum=32,current=False)
    quiet_plies: int = setting(2,'Quiet actual plies and lookahead required before presentation settlement.',minimum=1,maximum=4,current=False)

@dataclass(frozen=True)
class ExchangePresentation:
    version: int
    base_fen: str
    short_line: str
    evidence_continuation: str
    continuation_line: str
    full_line: str
    state: str
    reason: str
    player_color: str
    observed_material_cp: int
    settled_material_cp: int | None
    final_material_cp: int
    final_fen: str
    settings: ExchangePresentationSettings
    evidence_source: str

    def to_dict(self):
        return asdict(self)


def _quiet(board, moves):
    position=board.copy(stack=False)
    for move in moves:
        if position.is_check() or position.is_capture(move) or move.promotion or position.gives_check(move):return False
        position.push(move)
    return not position.is_check()


def build_exchange_presentation(fen, short_line, continuation, *, settings=ExchangePresentationSettings(), evidence_source='supplied_pv'):
    """Separate a tactical answer from a bounded continuation and material accounting.

    The supplied continuation starts at the exact short-line endpoint. It must
    replay completely legally. Quiet lookahead prevents stopping before a nearby
    countercapture on another square. Material is whole-line accounting, never
    engine evaluation or automatically causal motif credit.
    """
    short=StoredLine.from_san(fen,short_line)
    if not short.positions:raise ValueError(short.validation_error or 'Missing tactical line')
    tail=StoredLine.from_san(short.positions[-1],continuation)
    if tail.validation_error:raise ValueError(tail.validation_error)
    board=chess.Board(short.positions[-1]);player=chess.Board(fen).turn
    values=MaterialValues().piece_values();initial=material_balance(chess.Board(fen),player,values)
    moves=[chess.Move.from_uci(u) for u in tail.moves_uci];steps=[];quiet=0
    state,reason='incomplete','missing_or_exhausted_continuation'
    for index in range(min(len(moves),settings.max_plies)+1):
        if board.is_game_over():state,reason='terminal','terminal_position';break
        lookahead=moves[index:index+settings.quiet_plies]
        if quiet>=settings.quiet_plies and len(lookahead)==settings.quiet_plies and _quiet(board,lookahead):
            state,reason='settled','quiet_line_and_lookahead';break
        if index==settings.max_plies:state,reason='incomplete','presentation_cap';break
        if index==len(moves):break
        step,forcing=play_proof_move(board,moves[index],player,values,ply=index,user_moves=0,payoff_plies=0)
        steps.append(step);quiet=0 if forcing else quiet+1
    observed=material_balance(board,player,values)-initial
    added=' '.join(s.san for s in steps)
    return ExchangePresentation(1,fen,' '.join(short.moves),continuation,added,
        ' '.join((*short.moves,*(s.san for s in steps))),state,reason,'white' if player else 'black',
        observed,observed if state in ('settled','terminal') else None,material_balance(board,player,values),board.fen(),settings,evidence_source)


def exchange_presentation_from_dict(data, fen, short_line):
    """Recompute all derived fields; stale, tampered or mismatched details fail closed."""
    if not isinstance(data,dict) or data.get('version')!=1 or data.get('base_fen')!=fen or data.get('short_line')!=' '.join(short_line.split()):
        raise ValueError('Exchange detail identity mismatch')
    result=build_exchange_presentation(fen,short_line,data['evidence_continuation'],
        settings=ExchangePresentationSettings(**data['settings']),evidence_source=data['evidence_source'])
    if result.to_dict()!=data:raise ValueError('Exchange detail does not match legal evidence')
    return result


def matching_tactical_continuation(fen, short_line, after_tactic_pv):
    """Reuse the original PV only when its legal prefix matches the short answer.

    This preserves the recorded branch instead of splicing in a different reply.
    Missing, invalid or prefix-mismatched evidence falls back to an endpoint request.
    """
    short=StoredLine.from_san(fen,short_line)
    if not short.positions or not after_tactic_pv:return None
    evidence=StoredLine.from_san(short.positions[1],after_tactic_pv)
    prefix=short.moves_uci[1:]
    if not evidence.positions or evidence.moves_uci[:len(prefix)]!=prefix:return None
    remaining=evidence.moves[len(prefix):]
    return ' '.join(remaining) if remaining else None
