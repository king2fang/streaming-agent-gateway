"""Built-in tools: echo, calculator."""
import json
import ast
import operator


async def execute_tool(name: str, args_json: str) -> tuple[str, bool]:
    """Returns (content, is_error)."""
    try:
        args = json.loads(args_json) if args_json else {}
    except json.JSONDecodeError:
        return "Invalid JSON arguments", True

    if name == "echo":
        return str(args.get("text", "")), False

    if name == "calculator":
        expr = args.get("expr", "")
        try:
            val = _safe_eval(expr)
            return str(val), False
        except Exception as e:
            return f"Calc error: {e}", True

    return f"Unknown tool: {name}", True


def _safe_eval(expr: str) -> float:
    """Minimal safe math evaluator using ast."""
    ops = {ast.Add: operator.add, ast.Sub: operator.sub,
           ast.Mult: operator.mul, ast.Div: operator.truediv}
    def _eval(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in ops:
            return ops[type(node.op)](_eval(node.left), _eval(node.right))
        raise ValueError("unsupported expression")
    return _eval(ast.parse(expr, mode="eval").body)
