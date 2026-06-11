# v0.10.8 patch applied

This build is an additive diagnostics/observability patch on top of v0.10.7.

Added:

- `src/dupe_engine/calibration_diagnostics_v0108.py`
- `tools/v0108_calibration_diagnostics.py`
- `tests/run_v0108_selftest.py`
- `tests/test_calibration_diagnostics_v0108.py`
- `docs/V0108_RELEASE_NOTES.md`
- `docs/V0108_NEXT_EXPERIMENT.md`

Primary command:

```bash
python tools/v0108_calibration_diagnostics.py /path/to/calibration_run
```

Docker form:

```bash
docker compose run --rm dupe-worker python tools/v0108_calibration_diagnostics.py /data/runs/loop_v0107_server_p4_rerun1
```
