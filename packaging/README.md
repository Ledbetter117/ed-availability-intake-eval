# Installed-package wrapper source

`run_ed_i.py` is the wrapper used by the separate installed package. Its layout is `<package>/run_ed_i.py`, `<package>/tests/test_release_wrapper.py`, `<package>/INSTALL-MANIFEST.json`, and `<package>/tree/` containing this repository's evaluation tree. The deployment receipt and generated install manifest are local operational artifacts and are not published here.

Run the wrapper's synthetic fixture checks from this repository in PowerShell:

```powershell
python -B -X utf8 .\packaging\tests\test_release_wrapper.py .\packaging\run_ed_i.py
```

The repository's direct test commands are in `docs/VALIDATION.md`. The wrapper source is supplied for inspection and regression testing; copying it alone does not create an installed package or its manifest.
