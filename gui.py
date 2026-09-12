"""
JSON 解析器 — PySide6 GUI 界面
所有 JSON 解析逻辑委托给 core.JsonParser，本模块仅负责界面与交互。
"""
import json
import sys
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QModelIndex
from PySide6.QtGui import QAction, QFont, QColor, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QPushButton, QTextEdit, QTreeView, QLineEdit,
    QLabel, QStatusBar, QFileDialog, QMessageBox, QTabWidget,
    QHeaderView, QMenuBar, QGroupBox, QSizePolicy,
)

from core import JsonParser


class JsonTreeModel(QStandardItemModel):
    """递归将 JSON 数据填充到 QStandardItemModel 中"""

    def __init__(self):
        super().__init__()
        self.setHorizontalHeaderLabels(["Key / Index", "Value", "Type"])

    def load_data(self, data):
        """加载 JSON 数据并构建树"""
        self.clear()
        self.setHorizontalHeaderLabels(["Key / Index", "Value", "Type"])
        root_item = self.invisibleRootItem()
        self._build_tree(data, parent=root_item, key="root")

    def _build_tree(self, data, parent, key):
        if isinstance(data, dict):
            node = QStandardItem(str(key))
            node.setData(key, Qt.UserRole)  # 存储原始键名，供路径取值使用
            node.setEditable(False)
            node.setForeground(QColor("#c678dd"))
            tp = QStandardItem("")
            tp.setEditable(False)
            count_item = QStandardItem(f"object {{{len(data)}}}")
            count_item.setEditable(False)
            count_item.setForeground(QColor("#888"))
            parent.appendRow([node, tp, count_item])
            for k, v in data.items():
                self._build_tree(v, parent=node, key=k)
        elif isinstance(data, list):
            node = QStandardItem(str(key))
            # key 可能是 dict 键名（如 "items"）或列表索引（如 "[0]"）
            # 只有 "[i]" 格式才转为 int，否则保持原始字符串
            if isinstance(key, str) and key.startswith("[") and key.endswith("]"):
                node.setData(int(key[1:-1]), Qt.UserRole)
            else:
                node.setData(key, Qt.UserRole)
            node.setEditable(False)
            node.setForeground(QColor("#e5c07b"))
            tp = QStandardItem("")
            tp.setEditable(False)
            count_item = QStandardItem(f"array [{len(data)}]")
            count_item.setEditable(False)
            count_item.setForeground(QColor("#888"))
            parent.appendRow([node, tp, count_item])
            for i, v in enumerate(data):
                self._build_tree(v, parent=node, key=f"[{i}]")
        else:
            key_item = QStandardItem(str(key))
            key_item.setEditable(False)
            val_item = QStandardItem(str(data))
            val_item.setEditable(False)
            if data is None:
                val_item.setForeground(QColor("#abb2bf"))
                tp_text = "null"
            elif isinstance(data, bool):
                val_item.setForeground(QColor("#d19a66"))
                tp_text = "boolean"
            elif isinstance(data, (int, float)):
                val_item.setForeground(QColor("#d19a66"))
                tp_text = "number"
            else:
                val_item.setForeground(QColor("#98c379"))
                tp_text = "string"
            tp_item = QStandardItem(tp_text)
            tp_item.setEditable(False)
            tp_item.setForeground(QColor("#888"))
            parent.appendRow([key_item, val_item, tp_item])


class JsonViewer(QMainWindow):
    """JSON 解析器主窗口"""

    def __init__(self):
        super().__init__()
        self.parser: Optional[JsonParser] = None
        self.setWindowTitle("JSON 解析器")
        self.resize(1100, 700)
        self._setup_ui()
        self._setup_menu()
        self._setup_statusbar()

    # ─── UI 布局 ────────────────────────────────────────────
    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(8, 8, 8, 8)
        root_layout.setSpacing(6)

        # —— 顶部工具栏 ——
        toolbar_layout = QHBoxLayout()
        self.btn_open = QPushButton("📂 打开文件")
        self.btn_open.clicked.connect(self._on_open_file)
        self.btn_paste = QPushButton("📋 从剪贴板粘贴")
        self.btn_paste.clicked.connect(self._on_paste)
        self.btn_pretty = QPushButton("✨ 美化")
        self.btn_pretty.clicked.connect(self._on_pretty)
        self.btn_clear = QPushButton("🗑 清空")
        self.btn_clear.clicked.connect(self._on_clear)
        toolbar_layout.addWidget(self.btn_open)
        toolbar_layout.addWidget(self.btn_paste)
        toolbar_layout.addWidget(self.btn_pretty)
        toolbar_layout.addWidget(self.btn_clear)
        toolbar_layout.addStretch()
        root_layout.addLayout(toolbar_layout)

        # —— 主体：左右分栏 ——
        splitter = QSplitter(Qt.Horizontal)

        # 左侧：JSON 源文本
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        lbl_src = QLabel("JSON 源文本")
        lbl_src.setStyleSheet("font-weight: bold; margin-bottom: 2px;")
        self.source_edit = QTextEdit()
        self.source_edit.setPlaceholderText("在此粘贴 JSON 文本，或点击「打开文件」加载...")
        font = QFont("Consolas", 11)
        self.source_edit.setFont(font)
        self.source_edit.setStyleSheet("""
            QTextEdit {
                background-color: #1e1e1e;
                color: #d4d4d4;
                border: 1px solid #3c3c3c;
                border-radius: 4px;
                padding: 6px;
            }
        """)
        btn_parse = QPushButton("🔍 解析 JSON")
        btn_parse.clicked.connect(self._on_parse)
        left_layout.addWidget(lbl_src)
        left_layout.addWidget(self.source_edit, stretch=1)
        left_layout.addWidget(btn_parse)
        splitter.addWidget(left_panel)

        # 右侧：树形视图 + 美化输出
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        lbl_tree = QLabel("结构浏览")
        lbl_tree.setStyleSheet("font-weight: bold; margin-bottom: 2px;")
        right_layout.addWidget(lbl_tree)

        self.tree_view = QTreeView()
        self.tree_model = JsonTreeModel()
        self.tree_view.setModel(self.tree_model)
        self.tree_view.setAlternatingRowColors(True)
        self.tree_view.setIndentation(18)
        self.tree_view.setStyleSheet("""
            QTreeView {
                background-color: #252526;
                color: #d4d4d4;
                border: 1px solid #3c3c3c;
                border-radius: 4px;
                alternate-background-color: #2d2d2d;
            }
            QTreeView::item:selected {
                background-color: #264f78;
            }
            QHeaderView::section {
                background-color: #333;
                color: #ccc;
                border: none;
                padding: 4px;
            }
        """)
        self.tree_view.header().setStretchLastSection(True)
        self.tree_view.header().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.tree_view.header().setSectionResizeMode(1, QHeaderView.Stretch)
        self.tree_view.expandAll()
        self.tree_view.clicked.connect(self._on_tree_click)
        right_layout.addWidget(self.tree_view, stretch=2)

        # 美化输出区
        lbl_pretty = QLabel("选中节点的值 / 美化输出")
        lbl_pretty.setStyleSheet("font-weight: bold; margin-bottom: 2px; margin-top: 6px;")
        right_layout.addWidget(lbl_pretty)
        self.pretty_edit = QTextEdit()
        self.pretty_edit.setReadOnly(True)
        self.pretty_edit.setFont(QFont("Consolas", 11))
        self.pretty_edit.setMaximumHeight(180)
        self.pretty_edit.setStyleSheet("""
            QTextEdit {
                background-color: #1e1e1e;
                color: #d4d4d4;
                border: 1px solid #3c3c3c;
                border-radius: 4px;
                padding: 6px;
            }
        """)
        right_layout.addWidget(self.pretty_edit, stretch=1)
        splitter.addWidget(right_panel)

        splitter.setSizes([380, 700])
        root_layout.addWidget(splitter, stretch=1)

        # —— 底部搜索栏 ——
        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel("搜索："))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("输入关键词搜索键名或值...")
        self.search_input.setStyleSheet("""
            QLineEdit {
                background-color: #2d2d2d;
                color: #d4d4d4;
                border: 1px solid #3c3c3c;
                border-radius: 4px;
                padding: 4px 8px;
            }
        """)
        self.search_input.returnPressed.connect(self._on_search)
        btn_search = QPushButton("🔎 搜索")
        btn_search.clicked.connect(self._on_search)
        self.lbl_result = QLabel("")
        self.lbl_result.setStyleSheet("color: #888;")
        search_layout.addWidget(self.search_input)
        search_layout.addWidget(btn_search)
        search_layout.addWidget(self.lbl_result)
        search_layout.addStretch()
        root_layout.addLayout(search_layout)

    # ─── 菜单栏 ──────────────────────────────────────────────
    def _setup_menu(self):
        menubar = self.menuBar()
        menubar.setStyleSheet("""
            QMenuBar { background: #2d2d2d; color: #ccc; border-bottom: 1px solid #3c3c3c; }
            QMenuBar::item:selected { background: #3c3c3c; }
        """)
        file_menu = menubar.addMenu("文件")
        act_open = QAction("打开 JSON 文件...", self)
        act_open.setShortcut("Ctrl+O")
        act_open.triggered.connect(self._on_open_file)
        file_menu.addAction(act_open)
        act_paste = QAction("从剪贴板解析", self)
        act_paste.setShortcut("Ctrl+V")
        act_paste.triggered.connect(self._on_paste)
        file_menu.addAction(act_paste)
        file_menu.addSeparator()
        act_exit = QAction("退出", self)
        act_exit.setShortcut("Ctrl+Q")
        act_exit.triggered.connect(self.close)
        file_menu.addAction(act_exit)

        view_menu = menubar.addMenu("视图")
        act_expand = QAction("展开全部", self)
        act_expand.triggered.connect(self.tree_view.expandAll)
        view_menu.addAction(act_expand)
        act_collapse = QAction("折叠全部", self)
        act_collapse.triggered.connect(self.tree_view.collapseAll)
        view_menu.addAction(act_collapse)

    def _setup_statusbar(self):
        self.status_bar = QStatusBar()
        self.status_bar.setStyleSheet("color: #888;")
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("就绪 — 打开文件或粘贴 JSON 开始解析")

    # ─── 事件处理 ────────────────────────────────────────────
    def _on_open_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "打开 JSON 文件", "",
            "JSON 文件 (*.json);;所有文件 (*)"
        )
        if not path:
            return
        try:
            text = Path(path).read_text(encoding="utf-8")
            self.source_edit.setPlainText(text)
            self._parse_json(text)
            self.status_bar.showMessage(f"已加载: {path}")
        except Exception as e:
            QMessageBox.critical(self, "加载失败", str(e))

    def _on_paste(self):
        from PySide6.QtGui import QGuiApplication
        clipboard = QGuiApplication.clipboard()
        text = clipboard.text()
        if not text.strip():
            QMessageBox.information(self, "提示", "剪贴板为空")
            return
        self.source_edit.setPlainText(text)
        self._parse_json(text)
        self.status_bar.showMessage("已从剪贴板解析")

    def _on_parse(self):
        text = self.source_edit.toPlainText().strip()
        if not text:
            QMessageBox.information(self, "提示", "请先输入或加载 JSON 文本")
            return
        self._parse_json(text)

    def _on_pretty(self):
        if self.parser is None:
            QMessageBox.information(self, "提示", "请先解析 JSON")
            return
        self.source_edit.setPlainText(self.parser.pretty())
        self.status_bar.showMessage("已美化")

    def _on_clear(self):
        self.source_edit.clear()
        self.pretty_edit.clear()
        self.tree_model.clear()
        self.tree_model.setHorizontalHeaderLabels(["Key / Index", "Value", "Type"])
        self.parser = None
        self.lbl_result.setText("")
        self.status_bar.showMessage("已清空")

    def _on_search(self):
        keyword = self.search_input.text().strip()
        if not keyword or self.parser is None:
            self.lbl_result.setText("没有可搜索的数据")
            return

        results = self.parser.search(keyword)
        if results:
            lines = [f"{path}: {val}" for path, val in results[:50]]
            self.pretty_edit.setPlainText("\n".join(lines))
            self.lbl_result.setText(f"找到 {len(results)} 条结果")
        else:
            self.pretty_edit.clear()
            self.lbl_result.setText(f"未找到「{keyword}」")

    def _on_tree_click(self, index: QModelIndex):
        """点击树节点时，在美化区显示该节点的完整 JSON 值"""
        if self.parser is None:
            return

        # 从节点的 UserRole 中收集实际路径组件（键名或整数索引）
        path_parts: list = []
        display_parts: list[str] = []
        current = index
        while current.isValid():
            key_index = self.tree_model.index(current.row(), 0, current.parent())
            item = self.tree_model.itemFromIndex(key_index)
            if item is not None:
                part = item.data(Qt.UserRole)
                if part is not None and part != "root":
                    path_parts.insert(0, part)
                    display_parts.insert(0, item.text())
            current = current.parent()

        if not path_parts:
            return

        try:
            val = self.parser.get_by_path(path_parts)
            if isinstance(val, (dict, list)):
                self.pretty_edit.setPlainText(
                    json.dumps(val, indent=2, ensure_ascii=False))
            else:
                self.pretty_edit.setPlainText(str(val))
            self.status_bar.showMessage(f"路径: {' → '.join(display_parts)}")
        except (KeyError, TypeError, IndexError) as e:
            self.status_bar.showMessage(f"取值失败: {e}")

    # ─── 核心解析逻辑 ────────────────────────────────────────
    def _parse_json(self, text: str):
        try:
            self.parser = JsonParser.from_string(text)
            self.tree_model.load_data(self.parser.data)
            self.tree_view.expandAll()
            self.tree_view.header().setSectionResizeMode(0, QHeaderView.ResizeToContents)
            self.tree_view.header().setSectionResizeMode(1, QHeaderView.Stretch)
            self.status_bar.showMessage("✅ 解析成功")
            # 恢复深色主题样式（load_data 清空了 model 导致 header 样式丢失）
            self.tree_view.header().setStyleSheet("""
                QHeaderView::section {
                    background-color: #333;
                    color: #ccc;
                    border: none;
                    padding: 4px;
                }
            """)
        except json.JSONDecodeError as e:
            QMessageBox.warning(self, "JSON 解析错误", f"第 {e.lineno} 行，第 {e.colno} 列:\n{e.msg}")


# ─── 入口 ────────────────────────────────────────────────────
def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # 全局深色主题
    app.setStyleSheet("""
        QMainWindow, QWidget {
            background-color: #1e1e1e;
            color: #d4d4d4;
        }
        QPushButton {
            background-color: #0e639c;
            color: white;
            border: none;
            border-radius: 4px;
            padding: 6px 14px;
            font-size: 13px;
        }
        QPushButton:hover {
            background-color: #1177bb;
        }
        QPushButton:pressed {
            background-color: #094771;
        }
        QSplitter::handle {
            background-color: #3c3c3c;
            width: 2px;
        }
        QToolTip {
            background-color: #333;
            color: #d4d4d4;
            border: 1px solid #555;
        }
    """)

    window = JsonViewer()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
