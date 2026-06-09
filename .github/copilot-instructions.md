# Quick orientation for AI coding agents

This repository implements a Windows-focused Python Tkinter app that processes employee timeclock data and generates PDF reports.
Keep instructions short and concrete and reference files below when suggesting changes.

Key facts

- Language: Python 3.x (desktop app using Tkinter + pandas + fpdf)
- UI / entrypoint: `main.py` (UI, file selection, orchestration)
- Core processing: `procesador.py` (functions: `procesar_fichadas`, `aplanar_registros_por_tramo`)
- PDF output: `pdf_generator.py` (helpers: `generar_pdf_general`, `generar_pdf_resumen`, class `PDFGeneral`)
- Build / packaging: PyInstaller spec files (`CM_HorasExtras.spec`) and `build_exe.ps1` + installer `.bat` scripts

Where to read for context

- `main.py`: app flow, startup, folder layout (`archivos`, `reportes`, `logo`, `recursos`). Use it to see how inputs are validated and how PDF functions are invoked with optional args detected via `inspect.signature`.
- `procesador.py`: business rules for converting raw clock records into time blocks — any change to logic or outputs should be aligned with its exported functions.
- `pdf_generator.py`: visual/layout rules for generated PDFs and optional parameters (e.g., `feriados`, `grosor_lunes`). When adding args, preserve backward-compatible detection the app currently uses.
- `build_exe.ps1`, `CM_HorasExtras.spec`: how release builds are produced (Windows). Prefer updating `.spec` when changing packaged resources (fonts, logo, recursos).
- `tests/`: unit tests exist (e.g., `test_reglas_comida.py`). Run tests via `pytest`.

Developer workflows (concrete commands)

- Run the app (dev):

```powershell
python .\main.py
```

- Run tests:

```powershell
pytest -q
```

- Build a release (Windows PowerShell):

```powershell
; # from repo root
.\\build_exe.ps1    # project-provided wrapper that uses PyInstaller
# or
pyinstaller .\CM_HorasExtras.spec
```

Project-specific patterns and gotchas

- Paths & packaging: code uses `if getattr(sys,'frozen', False)` to detect PyInstaller runtime and set `BASE_DIR`. When adding files that must be packaged, update the `.spec` and `build_exe.ps1` accordingly.
- Spanish naming & UI: variables, comments and strings are Spanish (e.g., `INICIO_VARIABLE`, `gracia_entrada_min`). Keep translations/context when editing UI text.
- CSV loading: `main.py` implements a two-step CSV parsing fallback (sep=';' then ','), and enforces a required column rename map — changes to input formats must preserve that tolerance or update the mapping logic in the same file.
- Optional PDF args: `main.py` inspects function signatures before passing `feriados` and `grosor_lunes`. If you add those parameters to `pdf_generator` functions, tests and `main.py` won't break because of this guard; follow the same pattern if you add optional args.
- Fonts: the repo includes `dejavu-fonts-ttf-2.37/ttf`. Some test code references absolute Windows paths (see `test_fuente.py`), so prefer using `BASE_DIR`-relative paths for cross-environment edits.

Integration points & external deps

- fpdf / FPDF2: used for PDF rendering. See `pdf_generator.py` and `test_fuente.py` for font registration examples.
- pandas: heavy use for parsing and manipulating time records in `main.py` and `procesador.py`.
- Pillow (PIL) used for UI images (`logo`).
- PyInstaller for packaging (Windows `.spec` files). Installer scripts (`installer.bat`, `installer_admin.bat`) wrap outputs.

Editing guidance for AI assistants

- Keep UI logic in `main.py` and business logic in `procesador.py` (separation is intentionally present). Prefer implementing new logic inside `procesador.py` and exposing a clear function rather than adding complexity into `main.py`.
- When changing PDF layout, edit `pdf_generator.py` and ensure `generar_pdf_general` and `generar_pdf_resumen` remain callable with or without `feriados` and `grosor_lunes` (maintain backward compatibility or update callers accordingly).
- When adding files/resources (fonts, images), update `CM_HorasExtras.spec` and `build_exe.ps1` so packaged builds include them. Use `BASE_DIR` resolution to reference assets at runtime.
- Tests: add focused unit tests under `tests/` (use Spanish test names if matching project style). Run `pytest` locally.

When in doubt

- Read `main.py` and `procesador.py` first — they show the app's orchestrations and rules. Reference `README.md` for UX expectations (input/outputs folders) and don't commit user data under `archivos/` or `reportes/`.

If you have changes ready, paste a short patch (file path + brief intent) and ask for a quick run of tests or a build; this repository is Windows-targeted, so CI or checks should be performed in a Windows-like environment when possible.

---

If you'd like, I can adjust this to explicitly merge content from an existing `.github/copilot-instructions.md` (none was found), or expand it with examples from `procesador.py` and `pdf_generator.py` after reading them.
