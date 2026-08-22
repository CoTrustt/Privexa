from __future__ import annotations

import ast
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = API_ROOT / "src" / "privexa_api"
PROVIDER_ROOT = SOURCE_ROOT / "ai_gateway" / "providers"
PROTECTION_ROOT = SOURCE_ROOT / "ai_protection"
GATEWAY_FACTORY = SOURCE_ROOT / "ai_gateway" / "factory.py"

RESTRICTED_IMPORT_ROOTS = frozenset(
    {
        "anthropic",
        "autogen",
        "crewai",
        "google.generativeai",
        "google.genai",
        "langchain",
        "langgraph",
        "litellm",
        "llama_index",
        "openai",
        "openrouter",
    }
)


def _restricted_import(module: str) -> bool:
    return any(module == root or module.startswith(f"{root}.") for root in RESTRICTED_IMPORT_ROOTS)


def test_provider_sdk_imports_are_confined_to_gateway_provider_adapters() -> None:
    violations: list[str] = []
    for source_file in SOURCE_ROOT.rglob("*.py"):
        if source_file.is_relative_to(PROVIDER_ROOT):
            continue
        tree = ast.parse(source_file.read_text(encoding="utf-8"), filename=str(source_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [node.module or ""]
            else:
                continue
            for module in modules:
                if _restricted_import(module):
                    violations.append(f"{source_file.relative_to(API_ROOT)}:{node.lineno}:{module}")
    assert violations == []


def test_concrete_provider_adapter_import_is_confined_to_gateway_composition() -> None:
    violations: list[str] = []
    for source_file in SOURCE_ROOT.rglob("*.py"):
        if source_file.is_relative_to(PROVIDER_ROOT) or source_file == GATEWAY_FACTORY:
            continue
        tree = ast.parse(source_file.read_text(encoding="utf-8"), filename=str(source_file))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            if node.module == "privexa_api.ai_gateway.providers.openrouter":
                violations.append(f"{source_file.relative_to(API_ROOT)}:{node.lineno}")
    assert violations == []


def test_provider_endpoint_and_authorization_wire_literals_are_adapter_only() -> None:
    violations: list[str] = []
    for source_file in SOURCE_ROOT.rglob("*.py"):
        if source_file.is_relative_to(PROVIDER_ROOT):
            continue
        text = source_file.read_text(encoding="utf-8")
        if "openrouter.ai" in text:
            violations.append(f"{source_file.relative_to(API_ROOT)}:openrouter.ai")
        tree = ast.parse(text, filename=str(source_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and node.value == "Authorization":
                violations.append(
                    f"{source_file.relative_to(API_ROOT)}:{node.lineno}:Authorization"
                )
    assert violations == []


def test_pii_protection_package_has_no_gateway_provider_or_network_dependency() -> None:
    forbidden_roots = {
        "anthropic",
        "httpx",
        "openai",
        "openrouter",
        "privexa_api.ai_gateway",
        "requests",
    }
    violations: list[str] = []
    for source_file in PROTECTION_ROOT.rglob("*.py"):
        tree = ast.parse(source_file.read_text(encoding="utf-8"), filename=str(source_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [node.module or ""]
            else:
                continue
            for module in modules:
                if any(module == root or module.startswith(f"{root}.") for root in forbidden_roots):
                    violations.append(f"{source_file.relative_to(API_ROOT)}:{node.lineno}:{module}")
    assert violations == []
