# Running the proxy tests from a source checkout

From a clean checkout, use a fresh virtual environment without an editable install or generated package metadata under `src/`. The health endpoint reports `unknown` in this mode.

```sh
python -m venv .venv
.venv/bin/python -m pip install pytest jsonschema
PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_proxy.py
```

For the installed-package check, install the project and clear the pytest source-path setting so the suite imports the installed package. The health endpoint then reports the version in the distribution metadata.

```sh
.venv/bin/python -m pip install .
.venv/bin/python -m pytest -q -o pythonpath= tests/test_proxy.py
```
