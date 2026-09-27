"""Deterministic construction of editable opening graphs from curated source routes."""
from collections import Counter, defaultdict
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import chess
from default_opening_source import OpeningSourceRow, load_source, curate_rows, source_hierarchy
from opening_book_models import (BookSnapshot, OpeningBook, OpeningPosition, OpeningMove,
                                 SourceReference, position_identity)
from opening_library_package import write_library_package, inspect_package, semantic_identity
from opening_book_polyglot import export_library_polyglot

MAX_DEFAULT_LIBRARY_BYTES = 8 * 1024 * 1024


def build_snapshots(rows: tuple[OpeningSourceRow, ...], config: dict, manifest: dict) -> tuple[BookSnapshot, ...]:
    """Merge legal routes by canonical position and preserve defining name anchors.

    Args:
        rows: Curated, legally validated routes.
        config: Versioned semantic curation and neutral-weight settings.
        manifest: Exact official source provenance.

    Returns:
        Deterministic multi-book graph with globally unique IDs.

    Raises:
        ValueError: A selected family has no surviving source route.
    """
    root_fen = position_identity(chess.STARTING_FEN).canonical_fen
    fens = sorted({root_fen, *(fen for row in rows for fen in row.positions)})
    ids = {fen: index for index, fen in enumerate(fens, 1)}
    groups = defaultdict(list)
    for row in rows:
        groups[row.family].append(row)
    absent = set(config['families']) - groups.keys()
    if absent:
        raise ValueError(f'Curated families without routes: {sorted(absent)}')
    snapshots, move_id, source_id = [], 0, 0
    for book_id, family in enumerate(sorted(groups), 1):
        routes = groups[family]
        endpoints = defaultdict(list)
        for row in routes:
            endpoints[row.positions[-1]].append(row)
        anchors = sorted(endpoints)
        metadata = dict(repertoire_side=config['families'][family]['side'],
            opening_entry=dict(version=1, positions=anchors),
            default_content=dict(version=config['version'], repository=manifest['repository'],
                commit=manifest['commit'], license=manifest['license']))
        stamp = manifest['commit_date']
        book = OpeningBook(book_id, ids[root_fen], family,
            'Recognition map from Lichess chess-openings (CC0). Neutral weights; no preferred theory. Editable copy.',
            f"1.{manifest['commit'][:8]}", 'active', 1, json.dumps(metadata, sort_keys=True), stamp, stamp)
        used, edges = {root_fen}, {}
        for row in routes:
            board = chess.Board()
            for uci, target in zip(row.uci, row.positions):
                before = position_identity(board).canonical_fen
                move = board.parse_uci(uci)
                edges[before, uci] = (board.san(move), target)
                board.push(move)
                used.add(target)
        positions = tuple(OpeningPosition(ids[fen], fen, position_identity(fen).polyglot_key,
            position_identity(fen).side_to_move, '', '{}') for fen in sorted(used, key=ids.get))
        moves = []
        for (before, uci), (san, target) in sorted(edges.items()):
            named = [r for r in endpoints[target] if r.hierarchy]
            # A name labels its defining board, including alternate incoming routes.
            paths = sorted({r.hierarchy for r in named})
            if len(paths) > 1:
                raise ValueError(f'Conflicting names at one defining position: {family} {paths}')
            path = paths[0] if paths else ()
            parents = ()
            if len(path) > 1:
                route = named[0]
                witnessed = {r.hierarchy for r in routes if r.positions[-1] in route.positions[:-1]}
                if all(path[:n] in witnessed for n in range(1, len(path))):
                    parents = path[:-1]
                else:
                    # Keep the full compound name; never invent an unvisited parent.
                    path = (' / '.join(path),)
            detail = dict(opening_source_rows=sorted(r.source for r in endpoints[target]))
            if parents:
                detail['opening_named_parents'] = parents
            move_id += 1
            moves.append(OpeningMove(move_id, book_id, ids[before], uci, san, ids[target],
                config['neutral_weight'], False, True, '', '', json.dumps(detail, sort_keys=True),
                path[-1] if path else '', 'Source-defined position; neutral recognition label.' if path else ''))
        sources = []
        for row in routes:
            source_id += 1
            sources.append(SourceReference(source_id, book_id, ids[row.positions[-1]], None,
                row.name, 'Lichess contributors', manifest['commit'], row.eco, row.source,
                f"CC0-1.0 | {row.pgn} | {manifest['repository']}"))
        snapshots.append(BookSnapshot(book, positions, tuple(moves), tuple(sources)))
    return tuple(snapshots)


def generate_library(source: Path, curation: Path, output: Path) -> dict:
    """Build a fresh bounded library, companion and independently readable receipt.

    Args:
        source: Hash-pinned official TSV directory.
        curation: Reviewed JSON selection configuration.
        output: New output directory; existing content is never overwritten.

    Returns:
        Counts, exact hashes, curated routes, exclusions and provenance.

    Raises:
        ValueError: Input validation, curation, export or size limits fail.
        FileExistsError: Output already exists.
    """
    output.mkdir(parents=True, exist_ok=False)
    config = json.loads(curation.read_text(encoding='utf-8-sig'))
    manifest = json.loads((source / 'manifest.json').read_text(encoding='utf-8'))
    rows, rejected = load_source(source)
    (output / 'rejected_rows.json').write_text(json.dumps(rejected, indent=2), encoding='utf-8')
    if rejected:
        raise ValueError(f'{len(rejected)} malformed source rows; inspect rejected_rows.json.')
    selected, excluded = curate_rows(rows, config)
    snapshots = build_snapshots(selected, config, manifest)
    path = output / 'ChessWizard Default Openings.cwbook'
    write_library_package(snapshots, path)
    if path.stat().st_size > MAX_DEFAULT_LIBRARY_BYTES:
        raise ValueError('Default content exceeds the 8 MiB editorial review guard.')
    checked = inspect_package(path)
    if tuple(semantic_identity(s) for s in checked.books) != tuple(semantic_identity(s) for s in snapshots):
        raise ValueError('Generated package roundtrip changed authored content.')
    polyglot = export_library_polyglot(snapshots, output / 'ChessWizard Default Openings.bin')
    variations = {(s.book.name, (*json.loads(m.metadata_json).get('opening_named_parents', []), m.variation_name))
                  for s in snapshots for m in s.moves if m.variation_name}
    multiplicity = Counter((r.family, r.hierarchy) for r in selected)
    incoming = Counter((s.book.book_id, m.to_position_id) for s in snapshots for m in s.moves)
    report = dict(source=manifest, curation_sha256=hashlib.sha256(curation.read_bytes()).hexdigest(),
        families=len(snapshots), variations=len(variations), source_rows=len(rows), selected_rows=len(selected),
        rejected_rows=rejected, excluded_rows=len(excluded), positions=len({p.canonical_fen for s in snapshots for p in s.positions}),
        entry_positions=sum(len(json.loads(s.book.metadata_json)['opening_entry']['positions']) for s in snapshots),
        alternate_named_entries=sum(n-1 for n in multiplicity.values()),
        shared_graph_positions=sum(n > 1 for n in incoming.values()),
        cwbook_bytes=path.stat().st_size, cwbook_sha256=checked.file_sha256, polyglot=polyglot,
        family_details=[dict(family=s.book.name, side=config['families'][s.book.name]['side'],
            routes=[asdict(r) for r in selected if r.family==s.book.name],
            variations=sorted(' / '.join(v) for f,v in variations if f==s.book.name)) for s in snapshots])
    ranking = Counter(source_hierarchy(r.name, config)[0] for r in rows)
    (output / 'family_candidates.json').write_text(json.dumps([dict(family=f, source_rows=n,
        selected=f in config['families'], rank_basis='source breadth, NOT measured playing frequency')
        for f,n in ranking.most_common()], ensure_ascii=False, indent=2), encoding='utf-8')
    (output / 'excluded_rows.json').write_text(json.dumps(excluded, ensure_ascii=False, indent=2), encoding='utf-8')
    (output / 'build.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    (output / 'manifest.json').write_text(json.dumps({k:report[k] for k in
        ('source','curation_sha256','cwbook_sha256','families','variations','positions','entry_positions','polyglot')},indent=2),encoding='utf-8')
    (output / 'COPYING.txt').write_bytes((source / 'COPYING.txt').read_bytes())
    return report
