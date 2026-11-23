"""Native Windows dashboard for the existing HearthAgent commands."""
import json
import queue
import subprocess
import sys
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, ttk

from .makcu import Makcu


ROOT = Path(__file__).resolve().parents[1]
TASKS = {'接管当前对局': 'play', '循环对局': 'loop'}
MODES = {'练习': 'practice', '狂野': 'wild', '标准': 'standard'}
PACES = {'快速': 'fast', '谨慎': 'careful'}
BG, PANEL, FG, MUTED = '#101722', '#192534', '#eef4fb', '#a9bacd'
ACCENT, LOG_BG = '#70dfc2', '#121c29'
FONT = 'Microsoft YaHei UI'


def cli_command(options, *, status=False):
    python = Path(sys.executable).with_name('python.exe') if sys.platform == 'win32' else Path(sys.executable)
    args = [str(python), '-X', 'utf8', '-u', '-m', 'agent.cli', '--stop-on-stdin']
    if options['config'].strip():
        args += ['--config', options['config'].strip()]
    if status:
        return [*args, 'status']

    task, mode = TASKS[options['task']], MODES[options['mode']]
    args += [task, '--mode', mode, '--pace', PACES[options['pace']]]
    if task == 'play':
        args.append('--execute')
    if task == 'loop':
        try:
            count = int(options['games'])
            if count < 1:
                raise ValueError
        except ValueError:
            raise ValueError('局数请输入大于 0 的整数。') from None
        args += ['--games', str(count)]
        deck, menu = options['deck'].strip(), options['menu'].strip()
        if mode == 'standard' and not (deck and menu):
            raise ValueError('标准循环需要牌组 ID 和已校准的菜单配置。')
        if deck:
            args += ['--deck-id', deck]
        if menu:
            args += ['--menu-profile', menu]
    if options['port'].strip():
        args += ['--makcu-port', options['port'].strip()]
    if options['baud'] != '自动':
        args += ['--makcu-baud', options['baud']]
    return args


class ControlPanel:
    def __init__(self, root):
        self.root = root
        self.process = None
        self.operation = None
        self.stopping = self.closing = False
        self.events = queue.SimpleQueue()
        root.title('HearthAgent 中控')
        root.geometry('1120x730')
        root.minsize(950, 680)
        root.configure(bg=BG)
        root.protocol('WM_DELETE_WINDOW', self.close)

        style = ttk.Style(root)
        style.theme_use('clam')
        style.configure('.', font=(FONT, 10), background=PANEL, foreground=FG, bordercolor='#304256')
        style.configure('TEntry', fieldbackground=LOG_BG, insertcolor=FG)
        style.configure('TCombobox', fieldbackground=LOG_BG, arrowcolor=FG)
        style.map('TCombobox', fieldbackground=[('readonly', LOG_BG)], foreground=[('readonly', FG)])
        style.configure('TButton', padding=(12, 7), background='#26384a')
        style.map('TButton', background=[('active', '#335269')])
        style.configure('Primary.TButton', background=ACCENT, foreground=BG)
        style.map('Primary.TButton', background=[('active', '#a2f2dc'), ('disabled', '#304256')])
        defaults = dict(task='接管当前对局', mode='练习', pace='快速', games='1',
                        config='config/agent.json' if (ROOT / 'config/agent.json').is_file() else '',
                        port='', baud='自动', deck='', menu='')
        self.options = {key: tk.StringVar(root, value) for key, value in defaults.items()}
        self.run_status = tk.StringVar(root, '待机')
        self.device_status = tk.StringVar(root, '待检测')
        self.game_status = tk.StringVar(root, '待查询')

        header = tk.Frame(root, bg=BG)
        header.pack(fill='x', padx=24, pady=(18, 12))
        tk.Label(header, text='HearthAgent 中控', bg=BG, fg=FG, font=(FONT, 22, 'bold')).pack(side='left')
        self.refresh = ttk.Button(header, text='查询对局', command=lambda: self.launch(status=True))
        self.refresh.pack(side='right')

        body = tk.Frame(root, bg=BG)
        body.pack(fill='both', expand=True, padx=24, pady=(0, 20))
        settings = tk.Frame(body, background=PANEL, padx=16, pady=13)
        settings.pack(side='left', fill='y', padx=(0, 14))
        settings.columnconfigure(1, weight=1, minsize=147)
        self.label(settings, '任务设置', 13, bold=True).grid(row=0, columnspan=3, sticky='w', pady=(0, 8))
        self.fields = {}
        self.field(settings, 1, '任务', 'task', TASKS)
        self.field(settings, 2, '对局模式', 'mode', MODES)
        self.field(settings, 3, '操作节奏', 'pace', PACES)
        self.field(settings, 4, '局数', 'games')
        self.field(settings, 5, '牌组 ID', 'deck')
        self.field(settings, 6, '菜单配置', 'menu', browse=True)
        self.field(settings, 7, '本地配置', 'config', browse=True)

        self.label(settings, 'MAKCU', 13, bold=True).grid(row=8, columnspan=3, sticky='w', pady=(12, 4))
        self.field(settings, 9, '串口（可空）', 'port')
        self.field(settings, 10, '波特率', 'baud', ('自动', *map(str, Makcu.BAUD_RATES)))
        self.probe = ttk.Button(settings, text='检测 MAKCU', command=self.check_device)
        self.probe.grid(row=11, columnspan=3, sticky='ew', pady=(8, 7))
        actions = tk.Frame(settings, bg=PANEL)
        actions.grid(row=12, columnspan=3, sticky='ew', pady=(7, 0))
        actions.columnconfigure((0, 1), weight=1)
        self.start = ttk.Button(actions, text='启动实机任务', style='Primary.TButton', command=self.launch)
        self.start.grid(row=0, column=0, sticky='ew', padx=(0, 7))
        self.stop = ttk.Button(actions, text='停止任务', command=self.stop_task)
        self.stop.grid(row=0, column=1, sticky='ew')

        workspace = tk.Frame(body, bg=BG)
        workspace.pack(side='left', fill='both', expand=True)
        cards = tk.Frame(workspace, bg=BG)
        cards.pack(fill='x', pady=(0, 12))
        for column, (title, value) in enumerate((
            ('任务状态', self.run_status), ('MAKCU 握手', self.device_status), ('对局快照', self.game_status),
        )):
            cards.columnconfigure(column, weight=1, uniform='card')
            card = tk.Frame(cards, bg=PANEL, padx=12, pady=9)
            card.grid(row=0, column=column, sticky='nsew', padx=(0, 8 if column < 2 else 0))
            self.label(card, title, color=MUTED).pack(anchor='w')
            tk.Label(card, textvariable=value, bg=PANEL, fg=ACCENT, font=(FONT, 11, 'bold'),
                     wraplength=158, justify='left').pack(anchor='w', pady=(4, 1))

        output = tk.Frame(workspace, bg=PANEL, padx=13, pady=11)
        output.pack(fill='both', expand=True)
        bar = tk.Frame(output, bg=PANEL)
        bar.pack(fill='x', pady=(0, 8))
        self.label(bar, '运行日志', 13, bold=True).pack(side='left')
        ttk.Button(bar, text='清空', command=lambda: self.edit_log(lambda: self.log.delete('1.0', 'end'))).pack(side='right')
        scrollbar = ttk.Scrollbar(output)
        scrollbar.pack(side='right', fill='y')
        self.log = tk.Text(output, bg=LOG_BG, fg=FG, font=(FONT, 10), relief='flat', padx=10, pady=8,
                           wrap='word', state='disabled', yscrollcommand=scrollbar.set)
        self.log.pack(side='left', fill='both', expand=True)
        scrollbar.configure(command=self.log.yview)
        self.log.tag_configure('note', foreground=ACCENT)
        self.log.tag_configure('error', foreground='#ffadac')
        self.options['task'].trace_add('write', self.update_controls)
        for key in ('port', 'baud'):
            self.options[key].trace_add('write', lambda *_: self.device_status.set('待检测'))
        self.update_controls()
        root.after(60, self.poll)

    @staticmethod
    def label(parent, text, size=10, *, bold=False, color=FG):
        return tk.Label(parent, text=text, font=(FONT, size, 'bold' if bold else 'normal'), bg=PANEL, fg=color)

    def field(self, parent, row, label, key, values=None, browse=False):
        self.label(parent, label, color=MUTED).grid(row=row, column=0, sticky='w', padx=(0, 8))
        variable = self.options[key]
        if values is None:
            control = ttk.Entry(parent, textvariable=variable, width=18)
        else:
            control = ttk.Combobox(parent, textvariable=variable, values=tuple(values), width=16, state='readonly')
        control.grid(row=row, column=1, columnspan=1 if browse else 2, sticky='ew', pady=3)
        self.fields[key] = [control]
        if browse:
            button = ttk.Button(parent, text='浏览', command=lambda: self.browse(key))
            button.grid(row=row, column=2, padx=(5, 0))
            self.fields[key].append(button)

    def browse(self, key):
        path = filedialog.askopenfilename(parent=self.root, initialdir=ROOT, filetypes=[('JSON', '*.json')])
        if path:
            self.options[key].set(path)

    def update_controls(self, *_):
        task = TASKS[self.options['task'].get()]
        enabled = self.operation is None and not self.closing
        for key, widgets in self.fields.items():
            field_enabled = enabled and (task == 'loop' or key not in ('games', 'deck', 'menu'))
            for widget in widgets:
                widget.state(['!disabled' if field_enabled else 'disabled'])
        for widget in (self.start, self.refresh, self.probe):
            widget.state(['!disabled' if enabled else 'disabled'])
        self.stop.state(['!disabled' if self.process and not self.stopping else 'disabled'])

    def edit_log(self, operation):
        self.log.configure(state='normal')
        operation()
        self.log.configure(state='disabled')

    def append(self, text, tag=''):
        def insert():
            follow = self.log.yview()[1] >= 0.999
            stamp = datetime.now().strftime('%H:%M:%S')
            self.log.insert('end', f'{stamp}  {text.rstrip()}\n', tag)
            lines = int(self.log.index('end-1c').split('.')[0])
            if lines > 2200:
                self.log.delete('1.0', f'{lines - 2000}.0')
            if follow:
                self.log.see('end')
        self.edit_log(insert)

    def launch(self, *, status=False):
        if self.operation or self.closing:
            return
        try:
            options = {key: value.get() for key, value in self.options.items()}
            args = cli_command(options, status=status)
            self.process = subprocess.Popen(
                args, cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding='utf-8', errors='replace',
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0,
            )
        except (OSError, ValueError) as error:
            self.append(str(error), 'error')
            return
        self.operation = 'status' if status else 'task'
        self.run_status.set('查询中' if status else options['task'] + '中')
        self.append('查询对局日志' if status else f"启动 {options['task']}", 'note')
        if not status:
            self.append('请在提示出现后切回 Hearthstone 窗口。', 'note')
        self.update_controls()
        threading.Thread(target=self.read_process, args=(self.process,), daemon=True).start()

    def read_process(self, process):
        with process.stdout:
            for line in process.stdout:
                self.events.put(('line', line))
        self.events.put(('exit', process.wait()))

    def check_device(self):
        if self.operation or self.closing:
            return
        port = self.options['port'].get().strip() or None
        rate = self.options['baud'].get()
        self.operation = 'probe'
        self.device_status.set('检测中')
        self.update_controls()

        def probe():
            try:
                device = Makcu.connect(port, None if rate == '自动' else int(rate))
                try:
                    result = f'{device.serial.port} · {device.serial.baudrate}'
                finally:
                    device.close()
            except (OSError, RuntimeError) as error:
                self.events.put(('device_error', str(error)))
            else:
                self.events.put(('device', result))
        threading.Thread(target=probe, daemon=True).start()

    def stop_task(self):
        if self.process and not self.stopping:
            self.stopping = True
            self.run_status.set('正在停止')
            self.append('已请求停止，等待任务释放输入并退出。', 'note')
            self.process.stdin.close()
            self.update_controls()

    def poll(self):
        for _ in range(200):
            try:
                kind, value = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == 'line':
                self.append(value)
                if self.operation == 'status':
                    self.display_game(value)
                continue
            elif kind == 'exit':
                self.process.stdin.close()
                self.process = None
                self.run_status.set('已停止' if self.stopping else '已完成' if value == 0 else '运行失败')
                if self.operation == 'status' and value != 0:
                    self.game_status.set('查询失败')
                self.append(f'进程已退出（代码 {value}）', 'note' if not value or self.stopping else 'error')
                self.operation = None
                self.stopping = False
            else:
                self.device_status.set(value if kind == 'device' else '握手失败')
                self.append(f'MAKCU {value}', 'note' if kind == 'device' else 'error')
                self.operation = None
            self.update_controls()
        if self.closing and self.operation is None:
            self.root.destroy()
            return
        self.root.after(60, self.poll)

    def display_game(self, line):
        try:
            game = json.loads(line)
        except ValueError:
            return
        if isinstance(game, dict) and 'game' in game:
            if game['game'] is None:
                self.game_status.set('暂无对局')
                return
            modes = {'FT_STANDARD': '标准', 'FT_WILD': '狂野', 'GT_VS_AI': '练习', 'GT_VS_FRIEND': '好友'}
            mode = modes.get(game.get('format')) or modes.get(game.get('type'), game.get('type') or '对局')
            state = '已结束' if game.get('over') else f"第 {game.get('turn', '—')} 回合"
            self.game_status.set(f'{mode} · {state}')

    def close(self):
        self.closing = True
        if self.operation is None:
            self.root.destroy()
            return
        self.stop_task()
        self.update_controls()


def main():
    root = tk.Tk()
    ControlPanel(root)
    root.mainloop()


if __name__ == '__main__':
    main()
