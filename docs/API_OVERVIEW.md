# Reusable API overview

Begin here, then follow the [API documentation instructions](DEVELOPMENT.md#api-documentation)
to generate the local `build/pydoc/index.html` with `tools/build_pydoc.py`. The approved list is [tools/public_api.json](../tools/public_api.json).
Generated pages are intentionally absent from Git. Read [ARCHITECTURE.md](ARCHITECTURE.md)
for deeper contracts; rendering documentation does not activate any service.

| Subsystem | Entry points | Boundary |
|---|---|---|
| Paths and clean storage | [application_paths](../application_paths.py), [database_bootstrap](../database_bootstrap.py), [database_schema](../database_schema.py) | Explicit writable profiles; clean initialization is separate from migrations |
| Import, search, collections | [game_import_service](../game_import_service.py), [game_search_service](../game_search_service.py), [game_collection_service](../game_collection_service.py) | Typed requests and repository boundaries; no desktop widgets |
| Board analysis | [board_analysis](../board_analysis/__init__.py), [static exchange](../board_analysis/static_exchange.py) | Geometry, attacks, safety, mobility and advisory exchange facts; no engine/DB/UI |
| Position/range evidence | [position_range_evidence](../position_range_evidence/__init__.py) | Legal replay and factual material/attack/terminal observations |
| Analysis orchestration | [analysis_registry](../analysis_registry.py), [analysis_planner](../analysis_planner.py), [analysis_crawler](../analysis_crawler.py), [analysis_backbone](../analysis_backbone.py) | Scope/planning and specialists remain separate; no historical full-scan launcher |
| Engine/cache and proof | [candidate_line_service](../candidate_line_service.py), [candidate_line_repository](../candidate_line_repository.py), [proof_escalation](../proof_escalation.py) | Exact raw evidence requests, bounded proof and explicit uncertainty |
| Admission and presentation scale | [quality_gate](../quality_gate.py), [the_scale](../the_scale.py) | Gate/proof decide admission; presentation never creates proof |
| Tactic persistence | [tactical_opportunities](../tactical_opportunities.py), [heavy_repository](../heavy_repository.py), [tactic_occurrence_storage](../tactic_occurrence_storage.py) | Structured outcomes and ID-preserving storage, separate training links |
| Opening authoring/library | [opening_book_service](../opening_book_service.py), [opening_library_service](../opening_library_service.py), [opening_studio_service](../opening_studio_service.py) | Managed writable graphs, explicit import/save and safe catalog ownership |
| Opening analysis | [opening_intelligence_service](../opening_intelligence_service.py), [opening_analysis_service](../opening_analysis_service.py), [opening_accuracy_service](../opening_accuracy_service.py) | Authored membership, observed behavior and engine quality stay distinct |
| Opening engine/handoff | [opening_engine_service](../opening_engine_service.py), [opening_studio_handoff](../opening_studio_handoff.py) | On-demand evidence; current-board proposals never silently author moves |
| Default opening content | [default_opening_source](../default_opening_source.py), [default_opening_builder](../default_opening_builder.py), [default_opening_install](../default_opening_install.py) | Pinned offline source, deterministic build and explicit first-profile seeding |
| Evaluation/move quality | [evaluation_service](../evaluation_service.py), [move_quality_service](../move_quality_service.py) | Compatible stored evidence, explicit score POV and result currentness |
| Review/feedback | [game_review_repository](../game_review_repository.py), [tactic_presentation](../tactic_presentation.py), [feedback.generator](../feedback/generator.py), [line_playback](../line_playback.py) | Frontend-neutral facts/results and legal stored-line replay |
| Training | [training_session](../training_session.py), [training_history](../training_history.py) | Session logic and attempts separated from analyzer calculation |
| Themes | [theme_core](../theme_core/__init__.py), [packages](../theme_core/packages.py), [presets](../theme_core/presets.py) | Validated data/assets only; UI consumes shared models |

`merlin_ui/` owns Tk widgets, events and desktop navigation. Domain rules do not belong
there. A future mobile frontend should reuse the services above rather than reimplement
the analysis system. No mobile implementation is part of this repository-readiness pass.

## Documentation contract and known debt

New/materially changed public APIs need explicit annotations and Google-style PEP 257
docstrings with relevant Args/Returns/Raises sections. The pydoc index deliberately
covers interfaces across subsystems, not every historical script or private helper.
Existing older interfaces still have annotation/docstring gaps; the local readiness
report measures these separately. A passing pydoc check proves import/render safety,
not a completed repository-wide documentation rewrite.
