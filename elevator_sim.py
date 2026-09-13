import tkinter as tk
from tkinter import ttk, messagebox
import threading
import time
import math

# ---------------- 全局参数 ----------------
MAX_FLOORS = 20        # 总楼层数
MAX_CAPACITY = 11      # 单部电梯最大载客数
MOVE_INTERVAL = 0.3    # 电梯每移动一层耗时（秒）
DOOR_INTERVAL = 0.8    # 开门载客耗时（秒）


def split_count(total, n):
    """把 total 人分给 n 部电梯，保证每部不超过 MAX_CAPACITY。"""
    if n == 1:
        return [total]
    half = math.ceil(total / 2)
    return [half, total - half]


# ---------------- 电梯类 ----------------
class Elevator:
    def __init__(self, eid):
        self.id = eid
        self.current_floor = 1
        self.passengers = 0          # 当前载客人数
        self.status = "空闲"          # 空闲 / 上行 / 下行 / 开门 / 载客
        self.pickup_floor = None     # 本次接人任务的目标楼层
        self.pickup_count = 0        # 本次要接的人数
        self.lock = threading.Lock()

    def is_idle(self):
        return self.status == "空闲" and self.pickup_floor is None

    def snapshot(self):
        with self.lock:
            return dict(
                id=self.id,
                floor=self.current_floor,
                passengers=self.passengers,
                status=self.status,
                pickup_floor=self.pickup_floor,
                pickup_count=self.pickup_count,
            )


# ---------------- 调度系统 ----------------
class ElevatorSystem:
    def __init__(self):
        self.elevators = [Elevator(1), Elevator(2)]
        self.waiting = {}            # {楼层: 等待人数}
        self.lock = threading.Lock() # 保护 waiting 与调度
        self.log_lock = threading.Lock()
        self.logs = []
        self.running = True
        self._start_threads()

    def log(self, msg):
        ts = time.strftime("%H:%M:%S")
        with self.log_lock:
            self.logs.append(f"[{ts}] {msg}")
            if len(self.logs) > 200:
                self.logs.pop(0)

    def _start_threads(self):
        for e in self.elevators:
            t = threading.Thread(target=self._elevator_loop, args=(e,), daemon=True)
            t.start()

    # ----- 呼叫 / 修改人数 -----
    def call_elevator(self, floor, count):
        """在指定楼层呼叫，count 为人数；再次调用即修改人数。"""
        with self.lock:
            if count <= 0:
                return False, "人数必须大于 0"
            if count > MAX_CAPACITY * 2:
                return False, f"人数超过 {MAX_CAPACITY * 2} 人，请等待下一轮"
            self.waiting[floor] = count
            self.log(f"楼层 {floor} 呼叫，人数 {count}")
            self._reschedule_locked()
            return True, ""

    def _reschedule_locked(self):
        """根据每个楼层等待人数，动态增派 / 撤回电梯并分配人数。"""
        for floor, count in list(self.waiting.items()):
            need = 1 if count <= MAX_CAPACITY else 2

            # 已派往该楼层且尚未载客的电梯
            assigned = [e for e in self.elevators if e.pickup_floor == floor]

            if need > len(assigned):
                # 增派电梯：优先选择离该楼层最近的空闲电梯
                idle = [e for e in self.elevators
                        if e.is_idle() and e.pickup_floor != floor]
                idle.sort(key=lambda e: abs(e.current_floor - floor))
                for e in idle[: need - len(assigned)]:
                    e.pickup_floor = floor
                    e.pickup_count = 0
                    assigned.append(e)
                    self.log(f"电梯 {e.id} 号被派往 {floor} 层接人")
            elif need < len(assigned):
                # 人数减少，撤回多余电梯
                assigned.sort(key=lambda e: abs(e.current_floor - floor))
                keep, cancel = assigned[:need], assigned[need:]
                for e in cancel:
                    e.pickup_floor = None
                    e.pickup_count = 0
                    if e.status in ("上行", "下行"):
                        e.status = "空闲"
                    self.log(f"电梯 {e.id} 号取消前往 {floor} 层的任务")
                assigned = keep

            # 重新按当前人数分配每部电梯要接的人数
            shares = split_count(count, len(assigned))
            for e, s in zip(assigned, shares):
                e.pickup_count = s

    # ----- 电梯移动循环（每部电梯一个线程） -----
    def _elevator_loop(self, e):
        while self.running:
            with e.lock:
                pickup_floor = e.pickup_floor
                cur = e.current_floor
                pax = e.passengers
            time.sleep(0.05)

            if pickup_floor is not None:
                # 有接人任务，向目标楼层移动
                if cur < pickup_floor:
                    with e.lock:
                        if e.pickup_floor == pickup_floor:
                            e.current_floor += 1
                            e.status = "上行"
                    time.sleep(MOVE_INTERVAL)
                elif cur > pickup_floor:
                    with e.lock:
                        if e.pickup_floor == pickup_floor:
                            e.current_floor -= 1
                            e.status = "下行"
                    time.sleep(MOVE_INTERVAL)
                else:
                    # 到达，开门载客
                    with e.lock:
                        got = e.pickup_count
                        fl = e.pickup_floor
                        e.passengers += got
                        e.pickup_count = 0
                        e.pickup_floor = None
                        e.status = "载客"
                    with self.lock:
                        if fl is not None and fl in self.waiting:
                            self.waiting[fl] -= got
                            if self.waiting[fl] <= 0:
                                del self.waiting[fl]
                    self.log(f"电梯 {e.id} 号到达 {fl} 层，载客 {got} 人")
                    time.sleep(DOOR_INTERVAL)
            elif pax > 0:
                # 送乘客到 1 层
                if cur > 1:
                    with e.lock:
                        e.current_floor -= 1
                        e.status = "下行"
                    time.sleep(MOVE_INTERVAL)
                else:
                    with e.lock:
                        e.passengers = 0
                        e.status = "空闲"
                    self.log(f"电梯 {e.id} 号到达 1 层，乘客已下车")
            else:
                with e.lock:
                    e.status = "空闲"
                time.sleep(0.2)


# ---------------- 图形界面 ----------------
class ElevatorApp:
    def __init__(self, root):
        self.root = root
        self.system = ElevatorSystem()
        root.title("双电梯智能调度系统")
        root.geometry("760x760")

        self.floor_var = tk.StringVar(value="1")
        self.count_var = tk.StringVar(value="1")

        self._build_widgets()
        self.refresh()

    def _build_widgets(self):
        # 呼叫面板
        call_frame = tk.LabelFrame(self.root, text="呼叫面板", padx=10, pady=10)
        call_frame.pack(fill="x", padx=10, pady=5)

        tk.Label(call_frame, text="楼层：").grid(row=0, column=0)
        ttk.Spinbox(call_frame, from_=1, to=MAX_FLOORS,
                    textvariable=self.floor_var, width=6).grid(row=0, column=1, padx=5)

        tk.Label(call_frame, text="人数：").grid(row=0, column=2)
        ttk.Spinbox(call_frame, from_=1, to=MAX_CAPACITY * 2,
                    textvariable=self.count_var, width=6).grid(row=0, column=3, padx=5)

        tk.Button(call_frame, text="呼叫 / 更新人数",
                  command=self.on_call, width=18).grid(row=0, column=4, padx=10)

        self.tip_label = tk.Label(call_frame, text="", fg="gray")
        self.tip_label.grid(row=1, column=0, columnspan=5, pady=4)

        # 电梯状态区
        elev_frame = tk.LabelFrame(self.root, text="电梯实时状态", padx=10, pady=10)
        elev_frame.pack(fill="x", padx=10, pady=5)
        self.elev_labels = []
        for i in range(2):
            lbl = tk.Label(elev_frame, text="", font=("Consolas", 12),
                           justify="left", anchor="w", width=38)
            lbl.grid(row=0, column=i, padx=10, pady=5)
            self.elev_labels.append(lbl)

        # 楼层状态显示屏（Canvas）
        disp_frame = tk.LabelFrame(self.root, text="楼层电梯状态显示屏", padx=10, pady=10)
        disp_frame.pack(fill="both", expand=True, padx=10, pady=5)

        self.canvas_w = 520
        self.row_h = 24
        self.canvas_h = 30 + MAX_FLOORS * self.row_h
        self.canvas = tk.Canvas(disp_frame, width=self.canvas_w,
                                height=self.canvas_h, bg="white")
        self.canvas.pack(side="left", fill="both", expand=True)

        # 日志区
        log_frame = tk.LabelFrame(self.root, text="运行日志", padx=10, pady=5)
        log_frame.pack(fill="both", expand=True, padx=10, pady=5)
        self.log_text = tk.Text(log_frame, height=8, state="disabled")
        self.log_text.pack(fill="both", expand=True)

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def on_call(self):
        try:
            floor = int(self.floor_var.get())
            count = int(self.count_var.get())
        except ValueError:
            messagebox.showerror("错误", "请输入有效的数字")
            return
        if not (1 <= floor <= MAX_FLOORS):
            messagebox.showerror("错误", f"楼层必须在 1 ~ {MAX_FLOORS} 之间")
            return
        ok, msg = self.system.call_elevator(floor, count)
        if not ok:
            messagebox.showwarning("提示", msg)
            return
        self.tip_label.config(
            text=f"已呼叫 {floor} 层，共 {count} 人（电梯到达前可再次修改人数）")

    def refresh(self):
        # 更新电梯状态文字
        for i, e in enumerate(self.system.elevators):
            s = e.snapshot()
            color = "red" if i == 0 else "blue"
            self.elev_labels[i].config(
                text=(f"{i+1} 号电梯（{color}）\n"
                      f"  当前楼层：{s['floor']}\n"
                      f"  当前载客：{s['passengers']} 人\n"
                      f"  状态：{s['status']}"),
                fg=color)

        # 重绘楼层显示屏
        self.canvas.delete("all")
        with self.system.lock:
            waiting = dict(self.system.waiting)
        with self.system.lock:
            logs = list(self.system.logs)

        top = 20
        # 每层一行，1 层在底部
        for f in range(1, MAX_FLOORS + 1):
            y = self.canvas_h - top - (f - 1) * self.row_h - self.row_h // 2
            self.canvas.create_text(40, y, text=f"F{f}",
                                    font=("Consolas", 10))
            cnt = waiting.get(f, 0)
            if cnt:
                self.canvas.create_text(460, y, text=f"等待 {cnt} 人",
                                        fill="orange", font=("Consolas", 10))

        # 画电梯位置及载客人数
        for i, e in enumerate(self.system.elevators):
            s = e.snapshot()
            y = self.canvas_h - top - (s['floor'] - 1) * self.row_h - self.row_h // 2
            x = 160 + i * 150
            color = "red" if i == 0 else "blue"
            self.canvas.create_oval(x - 14, y - 10, x + 14, y + 10,
                                    fill=color)
            self.canvas.create_text(x, y + 18,
                                    text=f"{i+1}号·{s['passengers']}人",
                                    fill=color, font=("Consolas", 9))

        # 更新日志
        self.log_text.config(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.insert("end", "\n".join(logs[-12:]))
        self.log_text.see("end")
        self.log_text.config(state="disabled")

        self.root.after(100, self.refresh)

    def on_close(self):
        self.system.running = False
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = ElevatorApp(root)
    root.mainloop()
