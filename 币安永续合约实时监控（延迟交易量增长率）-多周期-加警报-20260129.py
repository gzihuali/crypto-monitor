import sys, os, time
import requests
from PyQt6.QtWidgets import *
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor
import ccxt, pandas as pd

class NumericTableItem(QTableWidgetItem):
    def __init__(self, text, value):
        super().__init__(text)
        self.setData(Qt.ItemDataRole.UserRole, value)

    def __lt__(self, other):
        a = self.data(Qt.ItemDataRole.UserRole)
        b = other.data(Qt.ItemDataRole.UserRole)
        return float(a if a is not None else float('-inf')) < float(b if b is not None else float('-inf'))

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("币安USDT永续 - 全部")
        self.resize(1800, 900)

        w = QWidget()
        self.setCentralWidget(w)
        layout = QVBoxLayout(w)

        # 控制栏
        ctrl = QHBoxLayout()
        self.auto_cb = QCheckBox("自动刷新")
        self.auto_cb.stateChanged.connect(self.toggle_auto)
        ctrl.addWidget(self.auto_cb)

        self.interval_cb = QComboBox()
        self.interval_cb.addItems(["5分钟","15分钟","30分钟","1小时"])
        self.interval_cb.setCurrentIndex(3)
        self.interval_cb.setEnabled(False)
        ctrl.addWidget(QLabel("间隔：")); ctrl.addWidget(self.interval_cb)

        refresh_btn = QPushButton("手动刷新")
        refresh_btn.clicked.connect(self.manual_refresh)
        ctrl.addWidget(refresh_btn)
        layout.addLayout(ctrl)

        # 币种范围选择
        range_layout = QHBoxLayout()
        range_layout.addWidget(QLabel("币种范围："))
        self.range_cb = QComboBox()
        self.range_cb.addItems([
            "全部永续合约",
            "24小时交易量(USDT) 前100",
            "24小时交易量(USDT) 前200"
        ])
        self.range_cb.setCurrentIndex(0)  # 默认全部
        range_layout.addWidget(self.range_cb)
        layout.addLayout(range_layout)

        # K线周期多选 + 警报多选
        period_layout = QVBoxLayout()
        period_layout.addWidget(QLabel("K线周期（多选，默认1小时）："))

        self.period_checks = {}
        periods = ["5分钟", "15分钟", "1小时", "4小时", "1天", "1周"]
        period_row = QHBoxLayout()
        for p in periods:
            cb = QCheckBox(p)
            if p == "1小时":
                cb.setChecked(True)
            cb.stateChanged.connect(self.on_period_changed)
            self.period_checks[p] = cb
            period_row.addWidget(cb)
        period_layout.addLayout(period_row)

        period_layout.addWidget(QLabel("警报周期（默认选中1小时）："))
        self.alert_checks = {}
        alert_row = QHBoxLayout()
        for p in periods:
            cb = QCheckBox(p)
            if p == "1小时":
                cb.setChecked(True)
            cb.setEnabled(p == "1小时")
            self.alert_checks[p] = cb
            alert_row.addWidget(cb)
        period_layout.addLayout(alert_row)
        layout.addLayout(period_layout)

        # 确定按钮
        confirm_btn = QPushButton("确定加载/刷新数据")
        confirm_btn.clicked.connect(self.load_data)
        layout.addWidget(confirm_btn)

        # 文本筛选
        filter_txt = QHBoxLayout()
        filter_txt.addWidget(QLabel("币种筛选："))
        self.text_filter = QLineEdit()
        self.text_filter.textChanged.connect(self.apply_filters)
        filter_txt.addWidget(self.text_filter)
        layout.addLayout(filter_txt)

        # 数值筛选区域（动态）
        self.filter_layout = QHBoxLayout()
        layout.addLayout(self.filter_layout)

        # 表格
        self.table = QTableWidget()
        self.table.setSortingEnabled(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().sortIndicatorChanged.connect(self.update_sort_label)
        layout.addWidget(self.table)

        self.sort_lbl = QLabel("当前排序: 24h交易量 (降序)")
        layout.addWidget(self.sort_lbl)

        # 导出
        exp = QHBoxLayout()
        exp.addWidget(QPushButton("导出Excel", clicked=self.export_excel))
        exp.addWidget(QPushButton("导出符号.txt", clicked=self.export_txt))
        layout.addLayout(exp)

        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.showMessage("界面初始化完成，请选择周期并点击“确定加载/刷新数据”...")

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.manual_refresh)

        self.alerted_symbols = set()  # 已修复：使用 set()

        # 先显示空窗口
        self.show()

        # 初次初始化筛选框框架
        self.on_period_changed()

    def toggle_auto(self, state):
        if state == Qt.CheckState.Checked.value:
            mins = [5, 15, 30, 60][self.interval_cb.currentIndex()]
            self.timer.start(mins * 60000)
            self.interval_cb.setEnabled(True)
        else:
            self.timer.stop()
            self.interval_cb.setEnabled(False)

    def on_period_changed(self):
        selected_periods = [p for p, cb in self.period_checks.items() if cb.isChecked()]

        for p, cb in self.alert_checks.items():
            cb.setEnabled(p in selected_periods)
            if p not in selected_periods:
                cb.setChecked(False)

        while self.filter_layout.count():
            child = self.filter_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        self.filters = {}
        fixed_cols = ['涨跌幅(%)', '交易量(USDT)']
        for col_idx, name in enumerate(fixed_cols, 3):
            box = self._create_filter_group(name, col_idx, is_distance=False)
            self.filter_layout.addWidget(box)
            self.filters[col_idx] = box.property("filter_data")

        dynamic_start_idx = 3 + len(fixed_cols)
        for offset, p in enumerate(selected_periods):
            col_idx = dynamic_start_idx + offset
            name = f"交易量延迟增长>10 距 ({p})"
            box = self._create_filter_group(name, col_idx, is_distance=True)
            self.filter_layout.addWidget(box)
            self.filters[col_idx] = box.property("filter_data")

        self.status.showMessage("周期已更新，请点击“确定加载/刷新数据”开始加载...")

    def _create_filter_group(self, name, col_idx, is_distance):
        box = QGroupBox(name)
        form = QFormLayout()
        op = QComboBox(); op.addItems(["无", ">", "<", "=", "介于"])
        op.currentIndexChanged.connect(lambda _, c=col_idx: self.update_filter(c))
        form.addRow("操作:", op)

        v1 = QDoubleSpinBox(); v1.setRange(-1e12, 1e12)
        v1.setDecimals(0 if is_distance else 4)
        v1.valueChanged.connect(lambda _, c=col_idx: self.update_filter(c))
        form.addRow("值1:", v1)

        v2 = QDoubleSpinBox(); v2.setRange(-1e12, 1e12)
        v2.setDecimals(v1.decimals()); v2.setEnabled(False)
        v2.valueChanged.connect(lambda _, c=col_idx: self.update_filter(c))
        op.currentIndexChanged.connect(lambda idx, v=v2: v.setEnabled(idx == 4))
        form.addRow("值2:", v2)

        box.setLayout(form)
        box.setProperty("filter_data", {'op': op, 'v1': v1, 'v2': v2})
        return box

    def update_filter(self, col_idx):
        self.apply_filters()

    def apply_filters(self):
        txt = self.text_filter.text().strip().lower()
        vis = 0
        for r in range(self.table.rowCount()):
            item = self.table.item(r, 1)
            hide = bool(txt and (not item or txt not in item.text().lower()))

            if not hide:
                for col, w in self.filters.items():
                    op = w['op'].currentText()
                    if op == "无": continue
                    it = self.table.item(r, col)
                    val = it.data(Qt.ItemDataRole.UserRole) if it else None
                    if val is None:
                        hide = True
                        break
                    v1 = w['v1'].value()
                    v2 = w['v2'].value() if op == "介于" else None

                    if   op == "大于 >"  and not (val > v1): hide = True
                    elif op == "小于 <"  and not (val < v1): hide = True
                    elif op == "等于 ="  and abs(val - v1) >= 1e-6: hide = True
                    elif op == "介于"    and not (min(v1, v2) <= val <= max(v1, v2)): hide = True
                    if hide: break

            self.table.setRowHidden(r, hide)
            if not hide: vis += 1

        self.status.showMessage(f"共 {self.table.rowCount()} 条 | 筛选后可见 {vis} 条")

    def manual_refresh(self):
        self.table.setRowCount(0)
        self.alerted_symbols.clear()
        self.load_data()

    def export_excel(self):
        rows = []
        for r in range(self.table.rowCount()):
            if self.table.isRowHidden(r): continue
            row = [self.table.item(r, c).text() if self.table.item(r, c) else '' for c in range(self.table.columnCount())]
            rows.append(row)

        if not rows:
            return QMessageBox.warning(self, "提示", "无数据可导出")

        path, _ = QFileDialog.getSaveFileName(self, "导出Excel", r"D:\CryptoPython\export.xlsx", "Excel (*.xlsx)")
        if path:
            columns = [self.table.horizontalHeaderItem(i).text() for i in range(self.table.columnCount())]
            pd.DataFrame(rows, columns=columns).to_excel(path, index=False)
            QMessageBox.information(self, "完成", f"已保存至 {path}")

    def export_txt(self):
        syms = []
        for r in range(self.table.rowCount()):
            if not self.table.isRowHidden(r):
                item = self.table.item(r, 1)
                if item:
                    syms.append(f"BINANCE:{item.text()}USDT.P")
        if not syms:
            return QMessageBox.warning(self, "提示", "无符号可导出")
        path, _ = QFileDialog.getSaveFileName(self, "导出符号列表", r"D:\CryptoPython\symbols.txt", "Text (*.txt)")
        if path:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(','.join(syms))
            QMessageBox.information(self, "完成", f"已导出 {len(syms)} 个符号")

    def send_alert(self, symbol, price, chg, vol, period):
        message = (
            f"[警报] 交易量延迟增长 >10 距 = 0\n"
            f"币种: {symbol}\n"
            f"24小时涨跌幅: {chg}\n"
            f"24小时量(USDT): {vol}\n"
            f"最新价: {price}\n"
            f"K线周期: {period}\n"
            f"————————————————————————————————"
        )

        proxies = {
            'http': 'http://127.0.0.1:7980',
            'https': 'http://127.0.0.1:7980'
        }

        TELEGRAM_BOT_TOKEN = "8593268164:AAGUYOqIvTBUkOWrBhOyTjK5dluppIqFziQ"
        TELEGRAM_CHAT_ID   = "2043458735"
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            response = requests.get(url, params={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "parse_mode": "Markdown"
            }, proxies=proxies, timeout=10)
            print(f"Telegram 发送状态码: {response.status_code}")
        except Exception as e:
            print(f"Telegram 发送失败: {e}")

        DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1465414477934755976/3wwnNdHzO1yticmOk0ulUgZA5SNcspBsQnttY5F_8DK4GMis9qCJFSSkLv_Ox8Z_yUc7"
        try:
            payload = {"content": message}
            response = requests.post(DISCORD_WEBHOOK_URL, json=payload, proxies=proxies, timeout=10)
            print(f"Discord 发送状态码: {response.status_code}")
        except Exception as e:
            print(f"Discord 发送失败: {e}")

        print(f"[警报已发送] {symbol} - 交易量延迟增长>10 距 = 0 ({period})")

    def load_data(self):
        start_time = time.time()

        self.status.showMessage("正在加载市场信息...")
        ex = ccxt.binance({
            'proxies': {'http': 'http://127.0.0.1:7980', 'https': 'http://127.0.0.1:7980'},
            'enableRateLimit': True,
            'options': {'defaultType': 'future'}
        })
        markets = ex.load_markets()
        perps = [s for s in markets if markets[s].get('swap') and markets[s].get('active') and markets[s]['quote'] == 'USDT']
        tickers = ex.fetch_tickers(perps)

        # 按24h交易量降序排序所有合约
        sorted_list = sorted(
            [(s, tickers.get(s, {}).get('quoteVolume', 0)) for s in perps],
            key=lambda x: x[1],
            reverse=True
        )

        # 根据范围选择截取符号
        range_choice = self.range_cb.currentText()
        if "前100" in range_choice:
            selected_symbols = [s for s, _ in sorted_list[:100]]
        elif "前200" in range_choice:
            selected_symbols = [s for s, _ in sorted_list[:200]]
        else:
            selected_symbols = [s for s, _ in sorted_list]

        self.status.showMessage(f"已选择范围：{range_choice}，共 {len(selected_symbols)} 个合约，开始加载K线...")

        selected_periods = [p for p, cb in self.period_checks.items() if cb.isChecked()]
        if not selected_periods:
            selected_periods = ["1小时"]

        headers = ['序号', '币种', '最新价', '24h涨跌', '24h量(USDT)']
        period_map = {"5分钟":"5m", "15分钟":"15m", "1小时":"1h", "4小时":"4h", "1天":"1d", "1周":"1w"}
        for p in selected_periods:
            headers.append(f"交易量延迟增长>10 距 ({p})")

        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)

        data = []
        total = len(selected_symbols)

        for i, sym in enumerate(selected_symbols, 1):
            try:
                t = tickers.get(sym, {})
                price = t.get('last')
                chg = t.get('percentage')
                vol24 = t.get('quoteVolume', 0)

                row = {
                    'idx': f"{len(data)+1:03d}",
                    'sym': sym.replace('/USDT:USDT','').replace('/',''),
                    'price_str': ex.price_to_precision(sym, price) if price else 'N/A',
                    'price_val': price or float('-inf'),
                    'chg_str': f"{chg:+.2f}%" if chg is not None else 'N/A',
                    'chg_val': chg or 0.0,
                    'vol24': vol24,
                    'vol_str': f"{vol24:,.0f}" if vol24 else 'N/A',
                    'distances': {}
                }

                ohlcv_cache = {}
                for p in selected_periods:
                    tf = period_map[p]
                    if tf not in ohlcv_cache:
                        try:
                            ohlcv = ex.fetch_ohlcv(sym, tf, limit=300)
                            ohlcv_cache[tf] = pd.DataFrame(ohlcv, columns=['ts','o','h','l','c','v'])
                        except Exception as e:
                            print(f"{sym} ({p}) klines 出错: {e}")
                            ohlcv_cache[tf] = pd.DataFrame()
                    df = ohlcv_cache[tf]

                    late10 = None
                    if len(df) >= 6:
                        for j in range(len(df)-1, 5-1, -1):
                            v = df['v'].iloc[j-5:j+1]
                            if v.iloc[:3].sum() > 0:
                                r = v.iloc[-3:].sum() / v.iloc[:3].sum() - 1
                                if late10 is None and r > 10:
                                    late10 = len(df)-1-j
                                if late10 is not None:
                                    break
                    row['distances'][p] = late10

                data.append(row)

                if len(data) % 10 == 0 or i == total:
                    self.update_table(data, selected_periods)
                    percent = int((i / total) * 100)
                    self.status.showMessage(f"处理中：已完成 {i}/{total} 个合约 ({percent}%)")
                    QApplication.processEvents()

                time.sleep(0.2)

            except Exception as e:
                print(f"{sym} 出错: {e}")

        self.update_table(data, selected_periods)
        self.apply_filters()

        for r in range(self.table.rowCount()):
            sym_item = self.table.item(r, 1)
            if not sym_item: continue
            symbol = sym_item.text()

            for offset, p in enumerate(selected_periods):
                col_idx = 5 + offset
                dist_item = self.table.item(r, col_idx)
                if dist_item:
                    dist_val = dist_item.data(Qt.ItemDataRole.UserRole)
                    if isinstance(dist_val, int) and dist_val == 0:
                        alert_cb = self.alert_checks[p]
                        if alert_cb.isChecked() and alert_cb.isEnabled():
                            key = f"{symbol}_{p}"
                            if key not in self.alerted_symbols:
                                price = self.table.item(r, 2).text() if self.table.item(r, 2) else 'N/A'
                                chg   = self.table.item(r, 3).text() if self.table.item(r, 3) else 'N/A'
                                vol   = self.table.item(r, 4).text() if self.table.item(r, 4) else 'N/A'
                                self.send_alert(symbol, price, chg, vol, p)
                                self.alerted_symbols.add(key)

        elapsed = time.time() - start_time
        visible_count = sum(1 for r in range(self.table.rowCount()) if not self.table.isRowHidden(r))
        self.status.showMessage(f"加载完成 共 {len(data)} 个合约 | 可见 {visible_count} 条 | 用时 {elapsed:.1f} 秒", 12000)

    def update_table(self, rows, selected_periods):
        self.table.setRowCount(len(rows))
        for r, d in enumerate(rows):
            self.table.setItem(r, 0, QTableWidgetItem(d['idx']))
            self.table.setItem(r, 1, QTableWidgetItem(d['sym']))
            self.table.setItem(r, 2, NumericTableItem(d['price_str'], d['price_val']))
            self.table.setItem(r, 3, NumericTableItem(d['chg_str'], d['chg_val']))
            self.table.setItem(r, 4, NumericTableItem(d['vol_str'], d['vol24']))

            for offset, p in enumerate(selected_periods):
                col_idx = 5 + offset
                dist = d['distances'].get(p)
                it = NumericTableItem(str(dist) if dist is not None else 'N/A', dist if isinstance(dist, int) else float('inf'))
                self.set_distance_background(it, dist)
                self.table.setItem(r, col_idx, it)

        self.table.sortItems(4, Qt.SortOrder.DescendingOrder)

    def set_distance_background(self, item, dist):
        if isinstance(dist, int) and dist >= 0:
            if dist == 0:
                item.setBackground(QColor(144, 238, 144))
            elif dist == 1:
                item.setBackground(QColor(173, 216, 230))

    def update_sort_label(self, idx, order):
        names = ['序号', '币种', '最新价', '24h涨跌', '24h量(USDT)']
        selected_periods = [p for p, cb in self.period_checks.items() if cb.isChecked()]
        for p in selected_periods:
            names.append(f"交易量延迟增长>10 距 ({p})")
        if 0 <= idx < len(names):
            dir_str = "升序" if order == Qt.SortOrder.AscendingOrder else "降序"
            self.sort_lbl.setText(f"当前排序: {names[idx]} ({dir_str})")
        else:
            self.sort_lbl.setText("当前排序: 未选择")

if __name__ == "__main__":
    os.makedirs(r"D:\CryptoPython", exist_ok=True)
    app = QApplication(sys.argv)
    win = MainWindow()
    sys.exit(app.exec())
