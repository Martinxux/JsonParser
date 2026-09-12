"""
JSON 解析器 — 命令行入口
核心解析逻辑位于 core.py，本模块仅负责命令行参数解析与输出。
"""
import json
import sys

from core import JsonParser


# ─── 命令行入口 ──────────────────────────────────────────────
def main():
    parser = JsonParser()

    if len(sys.argv) < 2:
        print("用法:")
        print("  python main.py <json文件路径>          # 解析并美化输出")
        print("  python main.py <文件> search <关键词>  # 搜索")
        print("  python main.py <文件> keys             # 列出顶级键")
        print("  python main.py <文件> summary          # 显示结构概览")
        print("  python main.py <文件> get <路径...>    # 按路径取值")
        return

    filepath = sys.argv[1]

    try:
        parser = JsonParser.from_file(filepath)
    except Exception as e:
        print(f"❌ 加载失败: {e}")
        return

    cmd = sys.argv[2] if len(sys.argv) > 2 else "pretty"

    if cmd == "pretty":
        print(parser.pretty())

    elif cmd == "keys":
        keys = parser.list_keys()
        if keys:
            for k in keys:
                print(f"  - {k}")
            print(f"\n共 {len(keys)} 个顶级键")
        else:
            print("根元素不是对象，无顶级键")

    elif cmd == "summary":
        print(parser.summary())

    elif cmd == "search":
        if len(sys.argv) < 4:
            print("请提供搜索关键词")
            return
        keyword = sys.argv[3]
        results = parser.search(keyword)
        if results:
            for path, value in results:
                print(f"  {path}: {value}")
            print(f"\n找到 {len(results)} 条结果")
        else:
            print(f"未找到包含「{keyword}」的内容")

    elif cmd == "get":
        if len(sys.argv) < 4:
            print("请提供访问路径")
            return
        try:
            value = parser.get(*sys.argv[3:])
            if isinstance(value, (dict, list)):
                print(json.dumps(value, indent=2, ensure_ascii=False))
            else:
                print(value)
        except Exception as e:
            print(f"❌ 取值失败: {e}")

    else:
        print(f"未知命令: {cmd}")


if __name__ == "__main__":
    main()
