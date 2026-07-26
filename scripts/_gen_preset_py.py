"""Gitignored codegen: turn Word evidence into a committed Python module of
authoritative VML geometry for the selected AutoShape types.

Each entry carries Word's own path (which may reference formula variables
@0..@N), the default adjustment, and the ordered <v:f eqn> formulas, so the
DOCX writer can emit them verbatim and let Word evaluate exact geometry.
Run after re-running scripts/_probe_word_presets.py when the corpus changes.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
presets = json.loads((ROOT / "evidence" / "presets.json").read_text(encoding="utf-8"))
out = ROOT / "src" / "doc2docx" / "ooxml" / "_vml_preset_formulas.py"

TARGETS = {
    4,
    13,
    15,
    16,
    21,
    22,
    23,
    53,
    54,
    55,
    57,
    59,
    60,
    64,
    65,
    66,
    67,
    68,
    69,
    70,
    71,
    72,
    73,
    77,
    78,
    80,
    81,
    82,
    84,
    85,
    86,
    87,
    88,
    92,
    93,
    94,
    96,
    97,
    102,
    103,
    104,
    105,
    107,
    108,
    *range(109, 121),
    122,
    125,
    126,
    127,
    128,
    129,
    130,
    131,
    132,
    133,
    134,
    176,
    177,
    183,
    184,
    185,
    186,
    187,
    *range(189, 201),
}
by_spt = {v["spt"]: (k, v) for k, v in presets.items()}

header = '''"""Authoritative VML preset geometry for OfficeArt AutoShape types.

Generated from Word's own VML <v:shapetype> definitions (see
evidence/presets.json / artifacts/word_native_paths) for AutoShape types
that carry adjustment formulas. Each entry stores Word's authoritative path
(which may reference formula variables @0..@N), the default adjustment
("adj"), and the ordered <v:f eqn> formulas so the consuming application
evaluates exact geometry instead of an approximated literal path.

VML_PRESET_PATH_ATTRIBUTES carries optional <v:path> child attributes from
Word's shapetype (e.g. limo) required for correct quadratic evaluation.
VML_PRESET_HANDLES carries Word SaveAs <v:handles>/<v:h> definitions needed
for adjusted presets (e.g. modern can) to render at full fidelity.

Do not edit by hand; regenerate via scripts/_gen_preset_py.py.
"""

from __future__ import annotations

'''
# repr() (not json) so integer shape-type keys stay integers in the output.
# Preserve verified definitions that are not present in the local, gitignored
# evidence snapshot, plus hand-maintained path attributes and handles.
existing_paths: dict[int, str] = {}
existing_formulas: dict[int, tuple[str | None, list[str]]] = {}
existing_attrs: dict[int, dict[str, str]] = {}
existing_handles: dict[int, list[dict[str, str]]] = {}
if out.exists():
    namespace: dict[str, object] = {}
    exec(out.read_text(encoding="utf-8"), namespace)
    raw_paths = namespace.get("VML_PRESET_FORMULA_PATHS") or {}
    if isinstance(raw_paths, dict):
        existing_paths = {int(k): str(v) for k, v in raw_paths.items()}
    raw_formulas = namespace.get("VML_PRESET_FORMULAS") or {}
    if isinstance(raw_formulas, dict):
        existing_formulas = {
            int(k): (v[0], list(v[1]))
            for k, v in raw_formulas.items()
        }
    raw = namespace.get("VML_PRESET_PATH_ATTRIBUTES") or {}
    if isinstance(raw, dict):
        existing_attrs = {int(k): dict(v) for k, v in raw.items()}
    raw_handles = namespace.get("VML_PRESET_HANDLES") or {}
    if isinstance(raw_handles, dict):
        existing_handles = {
            int(k): [dict(h) for h in v] for k, v in raw_handles.items()
        }

paths: dict[int, str] = {}
formulas: dict[int, tuple[str | None, list[str]]] = {}
for spt in sorted(TARGETS):
    if spt in by_spt:
        data = by_spt[spt][1]
        paths[spt] = data["path"]
        # Include path-only presets (e.g. lightning) with empty formula lists
        # so the writer still emits a Word-style <v:shapetype>.
        formulas[spt] = (data.get("adj"), list(data.get("formulas") or []))
        continue
    if spt not in existing_paths or spt not in existing_formulas:
        raise RuntimeError(
            f"preset {spt} is absent from both evidence and generated module"
        )
    paths[spt] = existing_paths[spt]
    formulas[spt] = existing_formulas[spt]

text = (
    header
    + "VML_PRESET_FORMULA_PATHS: dict[int, str] = "
    + repr(paths)
    + "\n\n"
    + "VML_PRESET_FORMULAS: dict[int, tuple[str | None, list[str]]] = "
    + repr(formulas)
    + "\n\n"
    + "VML_PRESET_PATH_ATTRIBUTES: dict[int, dict[str, str]] = "
    + repr(existing_attrs)
    + "\n\n"
    + "VML_PRESET_HANDLES: dict[int, list[dict[str, str]]] = "
    + repr(existing_handles)
    + "\n"
)
out.write_text(text, encoding="utf-8")
print(
    f"Wrote {out} ({len(paths)} paths, {len(formulas)} formula sets, "
    f"{len(existing_attrs)} path-attr presets, "
    f"{len(existing_handles)} handle presets)"
)
