"""
JSON 解析器 — PySide6 GUI 界面
所有 JSON 解析逻辑委托给 core.JsonParser，本模块仅负责界面与交互。
"""
import json
import sys
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QModelIndex, QSize, QRect
from PySide6.QtGui import (
    QAction, QFont, QColor, QStandardItem, QStandardItemModel,
    QTextCursor, QTextCharFormat, QPainter,
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QPushButton, QTextEdit, QPlainTextEdit, QTreeView,
    QLineEdit, QLabel, QStatusBar, QFileDialog, QMessageBox,
    QTabWidget, QHeaderView, QMenuBar, QGroupBox, QSizePolicy,
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


class LineNumberArea(QWidget):
    """行号栏画布,绘制工作委托给 CodeEdit 完成"""

    def __init__(self, editor: "CodeEdit"):
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self) -> QSize:
        """行号栏推荐宽度由编辑器决定"""
        return QSize(self._editor.line_number_area_width(), 0)

    def paintEvent(self, event):
        """将绘制事件转发给编辑器"""
        self._editor.line_number_area_paint_event(event)


class CodeEdit(QPlainTextEdit):
    """带行号栏 + 括号配对高亮的源文本编辑器"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._line_number_area = LineNumberArea(self)
        # 两组高亮分开管理,合并应用以共存:
        #   _extra_selections    外部设置的高亮(如错误行)
        #   _bracket_selections  括号配对高亮(光标移动时自动更新)
        self._extra_selections: list = []
        self._bracket_selections: list = []
        # 行数变化时更新行号栏宽度;滚动/内容变化时刷新行号
        self.blockCountChanged.connect(self._update_line_number_width)
        self.updateRequest.connect(self._update_line_number_area)
        # 光标移动时高亮配对括号
        self.cursorPositionChanged.connect(self._highlight_matching_bracket)
        self._update_line_number_width(0)

    def setExtraSelections(self, selections):
        """重写:外部设置的高亮存入 _extra_selections,与括号高亮合并应用"""
        self._extra_selections = list(selections)
        self._apply_all_selections()

    def _apply_all_selections(self):
        """合并错误高亮 + 括号高亮,调用父类 setExtraSelections"""
        super().setExtraSelections(self._extra_selections + self._bracket_selections)

    # ─── 括号配对高亮 ───────────────────────────────────────
    def _highlight_matching_bracket(self):
        """光标停在括号旁时,高亮对应的配对括号"""
        cursor = self.textCursor()
        pos = cursor.position()
        doc = self.document()
        n = doc.characterCount()

        # 候选括号:优先看光标左边字符,再看右边字符
        candidates: list[tuple[int, str]] = []
        if pos > 0:
            ch = str(doc.characterAt(pos - 1))
            if ch in '([{)]}':
                candidates.append((pos - 1, ch))
        if pos < n - 1:
            ch = str(doc.characterAt(pos))
            if ch in '([{)]}':
                candidates.append((pos, ch))

        if not candidates:
            self._bracket_selections = []
            self._apply_all_selections()
            return

        start_pos, start_ch = candidates[0]
        match_pos = self._find_matching_bracket(doc, start_pos, start_ch)

        if match_pos is None:
            self._bracket_selections = []
            self._apply_all_selections()
            return

        # 高亮两个括号字符(暗橄榄绿背景,与错误行的暗红不冲突)
        bg = QColor("#4b6b2f")
        self._bracket_selections = [
            self._make_char_selection(doc, start_pos, bg),
            self._make_char_selection(doc, match_pos, bg),
        ]
        self._apply_all_selections()

    @staticmethod
    def _make_char_selection(doc, pos: int, color: QColor):
        """构造单个字符的高亮(ExtraSelection)"""
        sel = QTextEdit.ExtraSelection()
        sel.cursor = QTextCursor(doc)
        sel.cursor.setPosition(pos)
        sel.cursor.movePosition(
            QTextCursor.MoveOperation.Right,
            QTextCursor.MoveMode.KeepAnchor,
            1,
        )
        sel.format.setBackground(color)
        return sel

    def _find_matching_bracket(self, doc, pos: int, ch: str):
        """从 pos 处的括号 ch 出发,查找配对括号位置,跳过字符串内括号"""
        opens = '([{'
        closes = ')]}'
        pair = dict(zip(opens, closes)) | dict(zip(closes, opens))

        forward = ch in opens          # 开括号向右找,闭括号向左找
        target = pair[ch]
        step = 1 if forward else -1
        n = doc.characterCount()

        depth = 0
        in_string = False
        escape = False
        i = pos + step
        while 0 <= i < n - 1:
            c = str(doc.characterAt(i))
            if in_string:
                if escape:
                    escape = False
                elif c == '\\':
                    escape = True
                elif c == '"':
                    in_string = False
            else:
                if c == '"':
                    in_string = True
                elif c == ch:                 # 同类括号,嵌套+1
                    depth += 1
                elif c == target:             # 配对括号
                    if depth == 0:
                        return i
                    depth -= 1
            i += step
        return None

    def line_number_area_width(self) -> int:
        """根据当前行数计算行号栏所需宽度"""
        digits = max(1, len(str(self.blockCount())))
        return 8 + self.fontMetrics().horizontalAdvance('9') * digits

    def resizeEvent(self, e):
        """窗口尺寸变化时同步调整行号栏几何"""
        super().resizeEvent(e)
        cr = self.contentsRect()
        self._line_number_area.setGeometry(
            cr.left(), cr.top(),
            self.line_number_area_width(), cr.height()
        )

    def line_number_area_paint_event(self, event):
        """绘制行号栏:深色背景 + 灰色行号"""
        painter = QPainter(self._line_number_area)
        painter.fillRect(event.rect(), QColor("#1e1e1e"))
        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        # QPlainTextEdit.blockBoundingGeometry 只接受 1 个参数,
        # 需配合 contentOffset() 转换到视口坐标
        top = round(
            self.blockBoundingGeometry(block).translated(self.contentOffset()).top()
        )
        bottom = top + round(self.blockBoundingRect(block).height())

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                number = str(block_number + 1)
                painter.setPen(QColor("#858585"))
                painter.drawText(
                    0, top,
                    self._line_number_area.width(),
                    self.fontMetrics().height(),
                    Qt.AlignRight,
                    number,
                )
            block = block.next()
            block_number += 1
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            if not block.isValid():
                break

    def _update_line_number_width(self, _):
        """行数变化时调整视口左边界,给行号栏留出空间"""
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def _update_line_number_area(self, rect, dy):
        """响应滚动/内容变化,同步刷新行号栏"""
        if dy:
            self._line_number_area.scroll(0, dy)
        else:
            self._line_number_area.update(
                0, rect.y(),
                self._line_number_area.width(), rect.height()
            )
        # 若变化波及整个视口,重新计算行号栏宽度
        if rect.contains(self.viewport().rect()):
            self._update_line_number_width(0)


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
        self.source_edit = CodeEdit()
        self.source_edit.setPlaceholderText("在此粘贴 JSON 文本，或点击「打开文件」加载...")
        font = QFont("Consolas", 11)
        self.source_edit.setFont(font)
        self.source_edit.setStyleSheet("""
            QPlainTextEdit {
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

    # ─── 出错行高亮与定位 ─────────────────────────────────────
    def _highlight_error_line(self, lineno: int, colno: int = 0):
        """高亮出错行并把光标跳转到出错位置"""
        doc = self.source_edit.document()
        # Qt 的行号从 0 开始,JSONDecodeError.lineno 从 1 开始,需减 1
        block = doc.findBlockByLineNumber(lineno - 1)
        if not block.isValid():
            return
        # 1) 整行暗红高亮(ExtraSelection)
        # 注意:PySide6 中 QPlainTextEdit 未绑定 ExtraSelection 嵌套类,
        # 需用 QTextEdit.ExtraSelection(QPlainTextEdit.setExtraSelections 仍可接受)
        sel = QTextEdit.ExtraSelection()
        sel.cursor = QTextCursor(block)
        sel.cursor.select(QTextCursor.SelectionType.LineUnderCursor)
        sel.format.setBackground(QColor("#8b0000"))
        self.source_edit.setExtraSelections([sel])
        # 2) 光标定位到具体列号(便于用户直接看到出错字符)
        #    JSONDecodeError.colno 从 1 开始,光标 position 从 0 开始,需减 1
        cursor = QTextCursor(block)
        colno_safe = max(0, colno - 1)
        cursor.movePosition(
            QTextCursor.MoveOperation.Right,
            QTextCursor.MoveMode.MoveAnchor,
            colno_safe,
        )
        self.source_edit.setTextCursor(cursor)
        self.source_edit.ensureCursorVisible()

    def _clear_error_highlight(self):
        """清除上次的出错行高亮"""
        self.source_edit.setExtraSelections([])

    # ─── 括号配对预检查 ───────────────────────────────────────
    def _find_bracket_error(self, text: str):
        """
        扫描文本检查括号配对,返回 (lineno, colno, msg) 或 None。

        策略:
        1. 栈配对(基础):找出"多余的闭括号"、"括号类型不匹配"、
           "文件末尾仍未闭合的开括号"。这些是确定性的错误。
        2. 缩进辅助(增强,延迟决策):JSON 缩进良好时,`}` 的缩进应
           等于配对 `{` 的缩进。若遇到 `}` 缩进严格小于栈顶 `{` 的
           缩进,说明栈顶 `{` 可能缺少了对应的 `}`(用户删了某个
           `}` 导致后续 `}` 错位匹配)。但**不立即报错**,只记录候选
           位置。扫描结束时,只有"确实发现括号配对问题"(栈非空或
           类型不匹配)才报候选;若栈空说明只是缩进不规范,不报错,
           交给 json.loads 兜底。避免对缩进不规范的合法 JSON 误报。

        跳过字符串字面量内的括号。
        """
        # 闭括号 → 对应开括号
        pair = {')': '(', ']': '[', '}': '{'}
        # 栈元素:(开括号字符, 行号, 列号, 该行的缩进空白数)
        stack: list[tuple[str, int, int, int]] = []
        in_string = False  # 是否处于字符串字面量内
        escape = False     # 字符串内是否处于转义状态(前一个字符是 \)
        # 缩进辅助候选:(lineno, col, ch) 或 None。只记录最早触发的
        indent_candidate = None

        for lineno, line in enumerate(text.split('\n'), start=1):
            # 计算行首缩进(前导空格/tab 数),用于缩进辅助判断
            # tab 和空格混用时不完全准确,但同一文件风格一致即可比较
            indent = len(line) - len(line.lstrip(' \t'))
            for col, ch in enumerate(line, start=1):
                if in_string:
                    if escape:
                        escape = False
                    elif ch == '\\':
                        escape = True
                    elif ch == '"':
                        in_string = False
                    continue
                # 非字符串内:只识别双引号(JSON 标准字符串定界符)
                if ch == '"':
                    in_string = True
                elif ch in '{[(':
                    stack.append((ch, lineno, col, indent))
                elif ch in ')]}':
                    if not stack:
                        return (lineno, col, f"多余的闭括号 '{ch}'")
                    open_ch, open_lineno, open_col, open_indent = stack[-1]
                    if open_ch != pair[ch]:
                        # 类型不匹配(如 { 配 ]):若之前有缩进候选,
                        # 优先报候选(更早察觉的真实错误位置);否则报当前
                        if indent_candidate is not None:
                            cl_lineno, cl_col, cl_ch = indent_candidate
                            return (
                                cl_lineno, cl_col,
                                f"未闭合的 '{cl_ch}'"
                                f"(第{cl_lineno}行第{cl_col}列)"
                                f"—— 可能在此之后缺少对应的闭括号"
                            )
                        return (lineno, col,
                                f"括号不匹配: '{open_ch}'"
                                f"(第{open_lineno}行第{open_col}列) 与 '{ch}' 不配对")
                    # 类型匹配,检查缩进辅助:
                    # 若当前 } 缩进 < 栈顶 { 缩进,说明栈顶 { 可能缺少
                    # 对应的 }。仅对花括号生效(方括号/圆括号同行居多)。
                    # 只记录第一个候选,不立即报错(延迟决策)。
                    if (ch == '}' and open_ch == '{'
                            and indent < open_indent
                            and indent_candidate is None):
                        indent_candidate = (open_lineno, open_col, open_ch)
                    stack.pop()

        # 扫描结束,综合判断
        if stack:
            # 栈非空:确实有未闭合开括号
            # 优先报缩进候选(更早察觉的位置),否则报栈顶
            if indent_candidate is not None:
                cl_lineno, cl_col, cl_ch = indent_candidate
                return (
                    cl_lineno, cl_col,
                    f"未闭合的 '{cl_ch}'"
                    f"(第{cl_lineno}行第{cl_col}列)"
                    f"—— 可能在此之后缺少对应的闭括号"
                )
            open_ch, lineno, col, _ = stack[-1]
            return (lineno, col,
                    f"未闭合的 '{open_ch}'(可能缺少对应的闭括号)")
        # 栈空:括号配对完整。即使有缩进候选,也说明只是缩进不规范,
        # 不报错,交给 json.loads 兜底(避免对合法 JSON 误报)
        return None

    # ─── 核心解析逻辑 ────────────────────────────────────────
    def _parse_json(self, text: str):
        self._clear_error_highlight()
        # BOM 兜底:剪贴板或部分编辑器可能插入 BOM,需剥除
        text = text.lstrip("\ufeff")

        # 括号预检查:对"删括号"类错误给出更准确的位置
        bracket_err = self._find_bracket_error(text)
        if bracket_err is not None:
            lineno, colno, msg = bracket_err
            self._highlight_error_line(lineno, colno)
            QMessageBox.warning(self, "JSON 括号错误",
                f"第 {lineno} 行，第 {colno} 列:\n{msg}")
            return

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
            self._highlight_error_line(e.lineno, e.colno)
            QMessageBox.warning(self, "JSON 解析错误", f"第 {e.lineno} 行，第 {e.colno} 列:\n{e.msg}")
        except TypeError as e:
            QMessageBox.warning(self, "类型错误", f"输入类型无效(可能传入了非字符串):\n{e}")
        except ValueError as e:
            QMessageBox.warning(self, "数值/格式错误", str(e))
        except Exception as e:
            QMessageBox.critical(self, "未预期的错误", f"{type(e).__name__}: {e}")


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
