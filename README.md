# symbol-checker-cli

A CLI checker that validates a project's `symbols.toml` schema and checks Python AST symbols for forbidden subwords and non-canonical subword replacements, emitting findings with actionable suggestions.

## Configuration (`symbols.toml`)

```toml
[settings]
include = ["src/**/*.py", "tests/**/*.py"]
exclude = []
forbidden_subwords = ["data", "info", "item", "obj", "val", "temp"]
allowed_symbols = []

[replacements]
load = ["fetch", "retrieve", "obtain", "read_config"]
index = ["idx", "pos"]
error = ["err", "exc"]
```

## Usage

```bash
# Check entire configured workspace
uv run symbol

# Filter to specific file(s) or directory(s)
uv run symbol src/symbol_checker/cli.py
uv run symbol src/
uv run symbol tests/

# Override config file path
uv run symbol --config path/to/symbols.toml
```

### Exit Codes

- `0`: No findings.
- `1`: One or more findings reported.
- `2`: Configuration file could not be read or parsed.

## Limitations

- Symbols are split into subwords on case changes, underscores, and digits only. All-lowercase run-together names such as `mydata` are not detected.
- Only definitions are checked (assignments, parameters, functions, classes, `self`/`cls` attributes, `as` aliases); usages and plain imports are not.

## Development

```bash
# Enable local git hooks (pre-commit and commit-msg)
git config core.hooksPath .githooks

uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run glossary
uv run symbol
uv run architecture
```
