# Contributing

- Read `docs/ARCHITECTURE.md`; module boundaries and signatures there are the contract.
- Tests run offline: a new source adapter needs a recorded fixture in
  `tests/fixtures/sources/` (see the naming rule in `src/jobveyra/sources/http.py`).
- Use invented people and companies in examples and tests (Alex Rivera, Example Labs,
  Globex). Never commit real personal data, real applications or real workspaces.
- Keep the deterministic path the source of truth; a model may only assist, within limits
  that are tested.
- `pytest -q` must pass on Python 3.10 to 3.13.
