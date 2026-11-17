"""AST-анализатор для сбора метрик качества Python-модулей."""

import ast
from typing import List

from cqi.models import (
    DANGEROUS_CALLS_PY,
    NETWORK_CALLS_PY,
    NETWORK_RECEIVERS_PY,
    SUBPROCESS_CALLS_PY,
)


class PythonASTAnalyzer(ast.NodeVisitor):
    """Анализатор AST для Python-файлов."""

    def __init__(self) -> None:
        """Инициализирует счетчики метрик AST."""
        self.functions_count = 0
        self.classes_count = 0
        self.complexities: List[int] = []
        self.func_lengths: List[int] = []
        self.max_nesting = 0
        self.documented_items = 0
        self.documentable_items = 0
        self.typed_args = 0
        self.total_args = 0
        self.bare_excepts = 0
        self.silent_excepts = 0
        self.network_calls_without_timeout = 0
        self.dangerous_calls = 0
        self.imports_count = 0
        self.asserts_count = 0

    def _calc_complexity(self, node: ast.AST) -> int:
        """Вычисляет цикломатическую сложность узла функции."""
        cc = 1
        branch_types = (
            ast.If, ast.For, ast.AsyncFor, ast.While,
            ast.ExceptHandler, ast.With, ast.AsyncWith, ast.IfExp,
        )
        for child in ast.walk(node):
            if isinstance(child, branch_types):
                cc += 1
            elif isinstance(child, ast.BoolOp):
                cc += max(0, len(child.values) - 1)
            elif isinstance(child, ast.comprehension):
                cc += 1 + len(child.ifs)
        return cc

    def _calc_nesting(self, node: ast.AST, current_depth: int = 0) -> int:
        """Вычисляет максимальную глубину вложенности управляющих конструкций."""
        max_d = current_depth
        nesting_nodes = (
            ast.If, ast.For, ast.AsyncFor, ast.While,
            ast.Try, ast.With, ast.AsyncWith,
        )
        for child in ast.iter_child_nodes(node):
            next_depth = current_depth + 1 if isinstance(child, nesting_nodes) else current_depth
            max_d = max(max_d, self._calc_nesting(child, next_depth))
        return max_d

    def visit_Module(self, node: ast.Module) -> None:
        """Проверяет наличие docstring на уровне модуля."""
        self.documentable_items += 1
        if ast.get_docstring(node):
            self.documented_items += 1
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """Собирает метрики класса и проверяет наличие docstring."""
        self.classes_count += 1
        self.documentable_items += 1
        if ast.get_docstring(node):
            self.documented_items += 1
        self.generic_visit(node)

    def _handle_function(self, node: ast.AST) -> None:
        """Собирает метрики сложности, длины, вложенности, docstring и типов функции."""
        self.functions_count += 1
        self.documentable_items += 1
        if ast.get_docstring(node):
            self.documented_items += 1

        self.complexities.append(self._calc_complexity(node))

        start = getattr(node, "lineno", 0)
        end = getattr(node, "end_lineno", start)
        self.func_lengths.append(max(1, end - start + 1))

        self.max_nesting = max(self.max_nesting, self._calc_nesting(node, 0))

        args_obj = getattr(node, "args", None)
        if args_obj:
            all_args = list(args_obj.args) + list(args_obj.kwonlyargs)
            for arg in all_args:
                if arg.arg in ("self", "cls"):
                    continue
                self.total_args += 1
                if arg.annotation is not None:
                    self.typed_args += 1
            if getattr(node, "returns", None) is not None:
                self.typed_args += 1
            self.total_args += 1

        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Обрабатывает синхронную функцию."""
        self._handle_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """Обрабатывает асинхронную функцию."""
        self._handle_function(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        """Фиксирует голые (bare) и молчаливые (silent) перехваты исключений."""
        if node.type is None:
            self.bare_excepts += 1

        is_broad = isinstance(node.type, ast.Name) and node.type.id in ("Exception", "BaseException")
        is_single_pass = len(node.body) == 1 and isinstance(node.body[0], ast.Pass)
        is_single_continue = len(node.body) == 1 and isinstance(node.body[0], ast.Continue)

        if is_single_pass or (is_broad and is_single_continue):
            self.silent_excepts += 1

        self.generic_visit(node)

    def _is_network_receiver(self, value: ast.AST) -> bool:
        """Проверяет, относится ли объект вызова к известным HTTP/сетевым клиентам."""
        if isinstance(value, ast.Name):
            return value.id.lower() in NETWORK_RECEIVERS_PY
        if isinstance(value, ast.Attribute):
            return value.attr.lower() in NETWORK_RECEIVERS_PY or self._is_network_receiver(value.value)
        return False

    def visit_Call(self, node: ast.Call) -> None:
        """Проверяет вызовы на опасные конструкции и отсутствие timeout у сетевых запросов."""
        if isinstance(node.func, ast.Name) and node.func.id in DANGEROUS_CALLS_PY:
            self.dangerous_calls += 1

        if isinstance(node.func, ast.Attribute):
            attr = node.func.attr
            if attr in NETWORK_CALLS_PY and self._is_network_receiver(node.func.value):
                kw_names = {kw.arg for kw in node.keywords if kw.arg}
                if "timeout" not in kw_names:
                    self.network_calls_without_timeout += 1

            if attr in SUBPROCESS_CALLS_PY:
                for kw in node.keywords:
                    if kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                        self.dangerous_calls += 1
        elif isinstance(node.func, ast.Name) and node.func.id in SUBPROCESS_CALLS_PY:
            for kw in node.keywords:
                if kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                    self.dangerous_calls += 1

        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        """Учитывает количество импортов модуля."""
        self.imports_count += len(node.names)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        """Учитывает количество импортов из модуля."""
        self.imports_count += len(node.names)

    def visit_Assert(self, node: ast.Assert) -> None:
        """Подсчитывает количество assert-проверок."""
        self.asserts_count += 1
