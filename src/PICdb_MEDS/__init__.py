"""The PIC (Paediatric Intensive Care database) MEDS ETL — a configuration package, not a library.

This distribution ships no code. Its content is ``PICdb_MEDS/event_configs.yaml``, a MESSY
(MEDS-Extract Specification Syntax YAML) document declaring where the raw PIC data comes from and how
every event is extracted from it, and ``PICdb_MEDS/sumeds_rules.yaml``, the suMEDS rules that enrich
the code metadata it writes. ``pyproject.toml`` registers the first with MEDS-Extract's
``MEDS_extract.pipelines`` entry-point group and the second with suMEDS's ``sumeds.rules`` group, both
under the name ``PICdb``. The spec declares suMEDS's ``sumeds_enrich`` post-stage with these rules, so
the ETL and its enrichment run as one command::

    meds-extract-run spec=PICdb output_dir=$MEDS_OUTPUT_DIR

and the plain ETL with ``skip_stages=[sumeds_enrich]`` added.

This package exists so the YAML files are addressable as package data —
``importlib.resources.files("PICdb_MEDS")`` — from an installed wheel. Nothing here is importable API.
"""
