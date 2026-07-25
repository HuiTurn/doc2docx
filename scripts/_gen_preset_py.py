"""Gitignored codegen: turn evidence/presets.json into a committed Python
module of authoritative VML geometry for the nine target AutoShape types.

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

TARGETS = {59, 64, 73, 84, 92, 93, 94, 183, 184}
by_spt = {v["spt"]: (k, v) for k, v in presets.items()}

paths: dict[int, str] = {spt: by_spt[spt][1]["path"] for spt in sorted(TARGETS)}
formulas: dict[int, tuple[str | None, list[str]]] = {}
for spt in sorted(TARGETS):
    data = by_spt[spt][1]
    eqns = data.get("formulas") or []
    if eqns:
        formulas[spt] = (data.get("adj"), list(eqns))

out = ROOT / "src" / "doc2docx" / "ooxml" / "_vml_preset_formulas.py"
header = '''"""Authoritative VML preset geometry for OfficeArt AutoShape types.

Generated from Word's own VML <v:shapetype> definitions (see
evidence/presets.json) for the nine preset types that carry adjustment
formulas. Each entry stores Word's authoritative path (which may reference
formula variables @0..@N), the default adjustment ("adj"), and the ordered
<v:f eqn> formulas so the consuming application evaluates exact geometry
instead of an approximated literal path.

Do not edit by hand; regenerate via scripts/_gen_preset_py.py.
"""

from __future__ import annotations

'''
# repr() (not json) so integer shape-type keys stay integers in the output.
text = (
    header
    + "VML_PRESET_FORMULA_PATHS: dict[int, str] = "
    + repr(paths)
    + "\n\n"
    + "VML_PRESET_FORMULAS: dict[int, tuple[str | None, list[str]]] = "
    + repr(formulas)
    + "\n"
)
out.write_text(text, encoding="utf-8")
print(f"Wrote {out} ({len(paths)} paths, {len(formulas)} formula sets)")
