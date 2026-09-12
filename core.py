"""
JSON 解析核心模块
提供 JsonParser 类，支持从文件或字符串加载 JSON，
并提供格式化输出、键值访问、递归搜索等功能。
本模块不依赖任何 UI 或命令行逻辑，可被 CLI 与 GUI 共同复用。
"""
import json
from pathlib import Path
from typing import Any, Union


class JsonParser:
    """JSON 解析工具，支持从文件或字符串加载 JSON，并提供格式化输出和键值访问。"""

    def __init__(self, data: Any = None):
        self._data = data if data is not None else {}

    # ─── 加载 ────────────────────────────────────────────────
    @classmethod
    def from_file(cls, filepath: str) -> "JsonParser":
        """从文件加载 JSON"""
        path = Path(filepath)
        if not path.exists():
            raise FileNotFoundError(f"文件不存在: {filepath}")
        with open(path, "r", encoding="utf-8") as f:
            return cls(json.load(f))

    @classmethod
    def from_string(cls, text: str) -> "JsonParser":
        """从字符串解析 JSON"""
        return cls(json.loads(text))

    # ─── 访问 ────────────────────────────────────────────────
    @property
    def data(self) -> Any:
        """返回原始解析数据"""
        return self._data

    def get(self, *keys: Union[str, int]) -> Any:
        """沿嵌套路径获取值。例: parser.get("users", 0, "name")"""
        current = self._data
        for key in keys:
            if isinstance(current, list):
                # 列表索引：兼容 int 与可转换为 int 的字符串
                try:
                    current = current[int(key)]
                except (ValueError, IndexError) as e:
                    raise KeyError(f"无效的列表索引: {key}") from e
            elif isinstance(current, dict):
                try:
                    current = current[key]
                except KeyError:
                    raise KeyError(f"键不存在: {key}")
            else:
                raise TypeError(
                    f"无法索引类型 {type(current).__name__}（位于路径 {key}）"
                )
        return current

    def get_by_path(self, path_parts: list[Union[str, int]]) -> Any:
        """按路径组件列表取值，供 GUI 树节点点击使用"""
        return self.get(*path_parts)

    def search(self, keyword: str) -> list[tuple[str, Any]]:
        """递归搜索所有键名或标量值中包含 keyword 的路径"""
        results: list[tuple[str, Any]] = []
        keyword_lower = keyword.lower()

        def _match_scalar(v: Any) -> bool:
            """仅对标量值做字符串包含匹配，避免对 dict/list 整体字符串化"""
            if isinstance(v, (dict, list)):
                return False
            return keyword_lower in str(v).lower()

        def _walk(obj: Any, path: str = "") -> None:
            if isinstance(obj, dict):
                for k, v in obj.items():
                    cur = f"{path}.{k}" if path else str(k)
                    if keyword_lower in str(k).lower() or _match_scalar(v):
                        results.append((cur, v))
                    _walk(v, cur)
            elif isinstance(obj, list):
                for i, v in enumerate(obj):
                    cur = f"{path}[{i}]"
                    if _match_scalar(v):
                        results.append((cur, v))
                    _walk(v, cur)

        _walk(self._data)
        return results

    # ─── 输出 ────────────────────────────────────────────────
    def pretty(self, indent: int = 2, ensure_ascii: bool = False) -> str:
        """返回格式化 JSON 字符串"""
        return json.dumps(self._data, indent=indent, ensure_ascii=ensure_ascii)

    def summary(self) -> str:
        """返回数据结构概览字符串"""
        def _describe(obj: Any) -> Any:
            if isinstance(obj, dict):
                return {k: _describe(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                if obj:
                    return [f"list[{len(obj)}] {_describe(obj[0])}"]
                return ["list[0]"]
            else:
                return type(obj).__name__
        return json.dumps(_describe(self._data), indent=2, ensure_ascii=False)

    def list_keys(self) -> list[str]:
        """列出所有顶级的键（如果是 dict）"""
        if isinstance(self._data, dict):
            return list(self._data.keys())
        return []
