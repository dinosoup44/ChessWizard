"""Validate pinned opening rows and apply explicit, engine-free content curation."""
from dataclasses import dataclass, replace
import csv
import hashlib
import io
import json
from pathlib import Path
import re
import chess
import chess.pgn
from opening_book_models import position_identity


@dataclass(frozen=True)
class OpeningSourceRow:
    """Hold a legally replayed source route and its reviewed display hierarchy.

    Args:
        source: Source filename and line number.
        eco: Official ECO code.
        name: Unmodified upstream name.
        pgn: Validated source movetext.
        uci: Legal main-line moves.
        epd: Final board with legally capturable en-passant convention.
        positions: Canonical positions after each ply, excluding the initial board.
        family: Reviewed visible family, empty before curation.
        hierarchy: Reviewed variation components, empty for a family route.
    """
    source: str
    eco: str
    name: str
    pgn: str
    uci: tuple[str, ...]
    epd: str
    positions: tuple[str, ...]
    family: str = ''
    hierarchy: tuple[str, ...] = ()


def parse_source_row(row: dict[str, str], source: str) -> OpeningSourceRow:
    """Reject malformed PGN or incompatible supplied UCI/EPD without repairing it.

    Args:
        row: Official TSV columns; UCI/EPD are optional upstream derived columns.
        source: Human-readable row location for audit records.

    Returns:
        Immutable legally replayed row.

    Raises:
        ValueError: The name, ECO, PGN, UCI or EPD is invalid or inconsistent.
    """
    if not re.fullmatch(r'[A-E]\d\d', row['eco']):
        raise ValueError('Invalid ECO code.')
    name = row['name']
    if not name.strip() or name != name.strip() or name.count(':') > 1:
        raise ValueError('Invalid opening name.')
    game = chess.pgn.read_game(io.StringIO(row['pgn']))
    if game is None or game.errors or game.variations == []:
        raise ValueError('Invalid or empty PGN.')
    board = chess.Board()
    moves = tuple(game.mainline_moves())
    if board.variation_san(moves) != row['pgn']:
        raise ValueError('Noncanonical PGN, annotations or unparsed movetext.')
    positions = []
    for move in moves:
        if move not in board.legal_moves:
            raise ValueError('Illegal source move.')
        board.push(move)
        positions.append(position_identity(board).canonical_fen)
    uci = tuple(m.uci() for m in moves)
    if row.get('uci') is not None and tuple(row['uci'].split()) != uci:
        raise ValueError('Source UCI differs from PGN.')
    if row.get('epd') is not None and row['epd'] != board.epd():
        raise ValueError('Source EPD differs from legal replay.')
    return OpeningSourceRow(source, row['eco'], name, row['pgn'], uci,
                            board.epd(), tuple(positions))


def load_source(directory: Path) -> tuple[tuple[OpeningSourceRow, ...], tuple[dict, ...]]:
    """Read hash-pinned official files, returning row errors explicitly.

    Args:
        directory: Folder containing manifest.json and a.tsv through e.tsv.

    Returns:
        Validated rows and rejected-row audit records.

    Raises:
        ValueError: A pinned input hash or TSV header differs.
    """
    manifest = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))
    for name, info in manifest['files'].items():
        path = (directory / name).resolve()
        if not path.is_relative_to(directory.resolve()) or hashlib.sha256(path.read_bytes()).hexdigest() != info['sha256']:
            raise ValueError(f'Pinned source changed: {name}')
    rows, rejected = [], []
    for letter in 'abcde':
        path = directory / f'{letter}.tsv'
        if hashlib.sha256(path.read_bytes()).hexdigest() != manifest['files'][path.name]['sha256']:
            raise ValueError(f'Pinned source changed: {path.name}')
        with path.open(encoding='utf-8', newline='') as stream:
            reader = csv.DictReader(stream, delimiter='\t')
            if reader.fieldnames not in (['eco', 'name', 'pgn'], ['eco', 'name', 'pgn', 'uci', 'epd']):
                raise ValueError('Unsupported source columns.')
            for line, row in enumerate(reader, 2):
                location = f'{path.name}:{line}'
                try:
                    rows.append(parse_source_row(row, location))
                except (ValueError, KeyError, TypeError) as error:
                    rejected.append(dict(source=location, row=row, reason=str(error)))
    return tuple(rows), tuple(rejected)


def source_hierarchy(name: str, config: dict) -> tuple[str, tuple[str, ...]]:
    """Apply reviewed family aliases before interpreting variation commas.

    Args:
        name: Unmodified upstream name.
        config: Versioned curation configuration.

    Returns:
        Visible family and candidate variation components.
    """
    for prefix, replacement in sorted(config['promotions'].items(), key=lambda p: -len(p[0])):
        if name == prefix or name.startswith(prefix + ', '):
            suffix = name[len(prefix):].removeprefix(', ')
            return replacement[0], tuple(replacement[1:]) + tuple(suffix.split(', ') if suffix else ())
    family, _, suffix = name.partition(': ')
    alias = config['aliases'].get(family, [family])
    return alias[0], (*alias[1:], *(suffix.split(', ') if suffix else ()))


def curate_rows(rows: tuple[OpeningSourceRow, ...], config: dict) -> tuple[tuple[OpeningSourceRow, ...], tuple[dict, ...]]:
    """Select bounded named branches without a fixed per-family quota.

    Args:
        rows: Validated official routes.
        config: Explicit families, semantic major branches and depth bounds.

    Returns:
        Selected rows and every excluded row with its curation reason.
    """
    proposed, excluded = [], []
    for row in rows:
        family, hierarchy = source_hierarchy(row.name, config)
        rule = config['families'].get(family)
        reason = None
        if rule is None:
            reason = 'family outside curated map'
        elif len(row.uci) < max(rule.get('minimum_anchor_plies', 1), config.get('minimum_name_plies', {}).get(row.name, 1)):
            reason = 'setup precedes defensible family entry'
        elif len(hierarchy) > 1 and ', '.join(hierarchy) not in config['subvariations'].get(family, []):
            reason = 'unreviewed nested subvariation'
        elif hierarchy and 'major_variations' in rule and hierarchy[0] not in rule['major_variations']:
            reason = 'sideline outside reviewed major branches'
        else:
            bound = (config['subvariation_max_plies'] if len(hierarchy) > 1 else
                     config['major_max_plies'] if rule.get('major_variations') else config['max_plies'])
            if len(row.uci) > bound:
                reason = 'deep continuation exceeds recognition bound'
        if reason:
            excluded.append(dict(source=row.source, name=row.name, pgn=row.pgn, reason=reason))
        else:
            proposed.append(replace(row, family=family, hierarchy=hierarchy))
    shortest = {}
    for row in proposed:
        key = row.family, row.hierarchy
        shortest[key] = min(shortest.get(key, len(row.uci)), len(row.uci))
    selected = []
    for row in proposed:
        if len(row.uci) > shortest[row.family, row.hierarchy] + config['same_name_extension_plies']:
            excluded.append(dict(source=row.source, name=row.name, pgn=row.pgn,
                                 reason='longer same-name continuation adds little recognition'))
        else:
            selected.append(row)
    return tuple(sorted(selected, key=lambda r: (r.family, len(r.uci), r.hierarchy, r.uci, r.source))), tuple(excluded)
