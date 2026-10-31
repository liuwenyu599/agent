# Draw.io Skill integration

Upstream: https://github.com/Agents365-ai/drawio-skill
Pinned revision: `57270820d3cd71cbdf4fb6b2f7091d4fb37bb019`
License: MIT (included in `LICENSE`).

`validate.py` is unmodified upstream. The PPT pipeline calls its `check_page`
before local page-bound and overlap checks. `autolayout.py` powers bounded
Graphviz placement when the model has provided explicit nodes and edges. Its
`layout()` subprocess was adapted to time out after 5 seconds and raise an
exception instead of exiting the server process. If Graphviz is unavailable,
the existing MCP/model path remains available.

The upstream `drawio2pptx.py` embeds rendered PNG pages in PPTX. This app
requires editable PowerPoint objects, so it keeps its native XML-to-shapes
renderer in `drawio_native.py`. `SKILL.md` describes an agent workflow and is
included as source reference, not executed as application code. The skill is
architecture-diagram focused and does not decide the slide order of a general
presentation.
