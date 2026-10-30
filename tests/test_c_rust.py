from __future__ import annotations

from pathlib import Path

import pytest

from symbol_checker.checker import check_project, check_source
from symbol_checker.cli import main
from symbol_checker.extractor import extract_symbols
from symbol_checker.schema import Replacement, SymbolSchema


def _build_schema(source_path: Path = Path("symbols.toml")) -> SymbolSchema:
    return SymbolSchema(
        include=("src/**/*.c", "src/**/*.h", "src/**/*.cpp", "src/**/*.hpp", "src/**/*.rs"),
        forbidden_subwords=("data", "info"),
        replacements=(Replacement(canonical="load", forbidden=("fetch",)),),
        source_path=source_path,
    )


@pytest.mark.parametrize(
    ("filename", "source_code", "expected_names"),
    [
        pytest.param(
            "calc.c",
            "#define MAX_RETRY_COUNT 3\n"
            "typedef struct CalcState {\n"
            "    int current_total;\n"
            "} CalcRecord;\n"
            "int compute_sum(int left_operand, int right_operand) {\n"
            "    int local_acc = left_operand + right_operand;\n"
            "    return local_acc;\n"
            "}\n",
            [
                "calc",
                "MAX_RETRY_COUNT",
                "CalcState",
                "current_total",
                "CalcRecord",
                "compute_sum",
                "left_operand",
                "right_operand",
                "local_acc",
            ],
            id="ansi_c_good_declarations",
        ),
        pytest.param(
            "engine.cpp",
            "namespace core_domain {\n"
            "class PacketRouter {\n"
            "public:\n"
            "    using RouteCount = int;\n"
            "    int route_packet(const std::string& target_host);\n"
            "};\n"
            "}\n",
            [
                "engine",
                "core_domain",
                "PacketRouter",
                "RouteCount",
                "route_packet",
                "target_host",
            ],
            id="cpp_good_declarations",
        ),
        pytest.param(
            "worker.rs",
            "pub mod sub_module;\n"
            "pub trait JobRunner {}\n"
            "pub struct TaskQueue {\n"
            "    pub queue_limit: usize,\n"
            "}\n"
            "pub fn process_batch(batch_size: usize) -> usize {\n"
            "    let mut processed_count = batch_size;\n"
            "    const STEP_DELTA: usize = 1;\n"
            "    processed_count + STEP_DELTA\n"
            "}\n",
            [
                "worker",
                "sub_module",
                "JobRunner",
                "TaskQueue",
                "queue_limit",
                "process_batch",
                "batch_size",
                "processed_count",
                "STEP_DELTA",
            ],
            id="rust_good_declarations",
        ),
    ],
)
def test_extract_c_cpp_rust_symbols_good_cases(
    filename: str, source_code: str, expected_names: list[str]
) -> None:
    symbols, findings = extract_symbols(source_code, file=Path(filename))
    assert not findings
    assert [symbol.name for symbol in symbols] == expected_names


@pytest.mark.parametrize(
    ("filename", "source_code", "expected_names"),
    [
        pytest.param(
            "main.c",
            "/* int bad_data = 1; */\n"
            'const char *msg_text = "int fake_data = 2;";\n'
            "int main(int argc, char **argv) {\n"
            "    return 0;\n"
            "}\n",
            ["msg_text"],
            id="c_skips_intrinsics_comments_and_string_literals_edge",
        ),
        pytest.param(
            "lib.rs",
            "// let fake_data = 1;\n"
            "pub fn new(&self) -> Self {\n"
            "    let repeated_entry = 1;\n"
            "    let repeated_entry = 2;\n"
            "}\n",
            ["repeated_entry"],
            id="rust_skips_lib_stem_self_and_deduplicates_edge",
        ),
    ],
)
def test_extract_c_cpp_rust_symbols_edge_cases(
    filename: str, source_code: str, expected_names: list[str]
) -> None:
    symbols, findings = extract_symbols(source_code, file=Path(filename))
    assert not findings
    assert [symbol.name for symbol in symbols] == expected_names


def test_c_cpp_rust_ignore_directives_and_failure_diagnostics() -> None:
    schema = _build_schema()
    c_source = (
        "int user_data = 1; /* symbol: ignore */\n"
        "int fetch_data = 2; /* symbol: ignore[data] */\n"
        'const char *label = "/* symbol: ignore */"; int raw_info = 3;\n'
        "int clean_count = 4; /* symbol: ignore */\n"
    )
    c_findings = check_source(c_source, schema, file=Path("src/sample.c"))
    assert [(f.line, f.symbol_name, f.message) for f in c_findings] == [
        (2, "fetch_data", "Uses non-canonical 'fetch'."),
        (3, "raw_info", "Contains ambiguous forbidden subword 'info'."),
        (4, None, "Unused 'symbol: ignore' comment matched no findings."),
    ]

    rs_source = (
        "let packet_data = 1; // symbol: ignore\n"
        "let bad_data = 2; // symbol: ignore[]\n"
        "fn fetch_record() {} // symbol: ignore[load, unknown]\n"
    )
    rs_findings = check_source(rs_source, schema, file=Path("src/sample.rs"))
    assert [(f.line, f.symbol_name, f.message) for f in rs_findings] == [
        (2, "bad_data", "Contains ambiguous forbidden subword 'data'."),
        (2, None, "Empty 'symbol: ignore[]' comment specifies no targets."),
        (3, None, "Unused ignore target 'unknown' in 'symbol: ignore' comment."),
    ]


def test_e2e_cli_multi_language_project_check(tmp_path: Path) -> None:
    config_path = tmp_path / "symbols.toml"
    config_path.write_text(
        "[settings]\n"
        'include = ["src/**/*.c", "src/**/*.cpp", "src/**/*.rs"]\n'
        'forbidden_subwords = ["data"]\n'
        "[replacements]\n"
        'load = ["fetch"]\n',
        encoding="utf-8",
    )
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "mod_a.c").write_text("int valid_count = 1;\n", encoding="utf-8")
    (src_dir / "mod_b.cpp").write_text("int valid_total = 2;\n", encoding="utf-8")
    (src_dir / "mod_c.rs").write_text("pub fn load_config() {}\n", encoding="utf-8")
    assert main(["--config", str(config_path)]) == 0

    (src_dir / "mod_c.rs").write_text("pub fn fetch_data() {}\n", encoding="utf-8")
    assert main(["--config", str(config_path)]) == 1
    assert len(check_project(_build_schema(config_path), root=tmp_path)) == 2
