"""慢慢赚钱 — a private, local-first Windows value overlay.

The application uses only Python's standard library. Salary settings never
leave the device; the historical gold figure is a fixed visual reference, not
a live market quote.
"""

from __future__ import annotations

import copy
import json
import math
import os
import re
import tkinter as tk
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any


APP_NAME = "慢慢赚钱"
WINDOW_WIDTH = 380
WINDOW_HEIGHT = 280
TRANSPARENT_COLOR = "#00ff01"
# A deliberately fixed pre-surge reference. It is not fetched from the web.
HISTORICAL_GOLD_PRICE_PER_GRAM = 280.0

DEFAULT_CONFIG: dict[str, Any] = {
    "monthly_salary": 15000.0,
    "paid_days": 21.75,
    "currency": "¥",
    "sessions": [
        {"start": "09:30", "end": "12:00"},
        {"start": "13:30", "end": "18:30"},
    ],
    "workdays": [0, 1, 2, 3, 4],
    "topmost": True,
    "window_position": None,
    "seen_welcome": False,
}

WEEKDAY_NAMES = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")


def local_data_path() -> Path:
    """Return a user-local settings path without exposing it in the project."""
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / APP_NAME / "settings.json"


def parse_clock(value: str) -> int:
    """Parse HH:MM and return minutes since midnight."""
    match = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", value)
    if not match:
        raise ValueError("时间请使用 HH:MM，例如 09:30")
    hours, minutes = (int(part) for part in match.groups())
    if not 0 <= hours <= 23 or not 0 <= minutes <= 59:
        raise ValueError("时间超出范围")
    return hours * 60 + minutes


def normalise_sessions(sessions: Any) -> list[dict[str, str]]:
    """Validate, sort and normalise up to four work sessions."""
    if not isinstance(sessions, list) or not sessions:
        raise ValueError("请至少保留一个工作时段")
    if len(sessions) > 4:
        raise ValueError("最多支持四个工作时段")

    cleaned: list[dict[str, str]] = []
    for item in sessions:
        if not isinstance(item, dict):
            raise ValueError("工作时段格式无效")
        start, end = str(item.get("start", "")), str(item.get("end", ""))
        parse_clock(start)
        parse_clock(end)
        if start == end:
            raise ValueError("一个工作时段的起止时间不能相同")
        cleaned.append({"start": start.zfill(5), "end": end.zfill(5)})
    return sorted(cleaned, key=lambda item: parse_clock(item["start"]))


def _safe_config(raw: Any) -> dict[str, Any]:
    config = copy.deepcopy(DEFAULT_CONFIG)
    if not isinstance(raw, dict):
        return config
    try:
        salary = float(raw.get("monthly_salary", config["monthly_salary"]))
        paid_days = float(raw.get("paid_days", config["paid_days"]))
        if salary <= 0 or paid_days <= 0:
            raise ValueError
        config["monthly_salary"] = salary
        config["paid_days"] = paid_days
        config["sessions"] = normalise_sessions(raw.get("sessions", config["sessions"]))
        days = raw.get("workdays", config["workdays"])
        if not isinstance(days, list) or not days or any(not isinstance(day, int) or day not in range(7) for day in days):
            raise ValueError
        config["workdays"] = sorted(set(days))
        config["currency"] = str(raw.get("currency", config["currency"]))[:3] or "¥"
        config["topmost"] = bool(raw.get("topmost", config["topmost"]))
        position = raw.get("window_position")
        if isinstance(position, list) and len(position) == 2 and all(isinstance(n, int) for n in position):
            config["window_position"] = position
        config["seen_welcome"] = bool(raw.get("seen_welcome", False))
    except (TypeError, ValueError):
        return copy.deepcopy(DEFAULT_CONFIG)
    return config


def config_from_form(
    existing: dict[str, Any],
    salary_text: str,
    paid_days_text: str,
    first_session_text: str,
    second_session_text: str,
    workdays_text: str,
) -> dict[str, Any]:
    """Convert the compact settings form into a validated, ready-to-save config."""
    sessions_data: list[dict[str, str]] = []
    for session in (first_session_text.strip(), second_session_text.strip()):
        if not session:
            continue
        parts = re.split(r"\s*[-—–]\s*", session)
        if len(parts) != 2:
            raise ValueError("工作时段请写成 09:30 - 12:00")
        sessions_data.append({"start": parts[0], "end": parts[1]})

    workdays = sorted({int(number) - 1 for number in re.findall(r"[1-7]", workdays_text)})
    if not workdays:
        raise ValueError("请至少选择一个每周工作日")

    updated = copy.deepcopy(existing)
    updated["monthly_salary"] = float(salary_text.replace(",", ""))
    updated["paid_days"] = float(paid_days_text)
    if updated["monthly_salary"] <= 0 or updated["paid_days"] <= 0:
        raise ValueError("月薪和计薪工作日必须大于 0")
    updated["sessions"] = normalise_sessions(sessions_data)
    updated["workdays"] = workdays
    updated["seen_welcome"] = True
    return updated


def load_config(path: Path | None = None) -> dict[str, Any]:
    path = path or local_data_path()
    try:
        return _safe_config(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        return copy.deepcopy(DEFAULT_CONFIG)


def save_config(config: dict[str, Any], path: Path | None = None) -> None:
    path = path or local_data_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


@dataclass(frozen=True)
class WorkSnapshot:
    anchor_day: date
    phase: str  # off, upcoming, earning, pause, complete
    progress: float
    earned: float
    daily_value: float
    active_seconds: float
    scheduled_seconds: float
    next_transition: datetime | None

    @property
    def remaining_seconds(self) -> float:
        return max(0.0, self.scheduled_seconds - self.active_seconds)


def _session_bounds(anchor_day: date, session: dict[str, str]) -> tuple[datetime, datetime]:
    start_minutes = parse_clock(session["start"])
    end_minutes = parse_clock(session["end"])
    day_start = datetime.combine(anchor_day, datetime.min.time())
    start = day_start + timedelta(minutes=start_minutes)
    end = day_start + timedelta(minutes=end_minutes)
    if end <= start:
        end += timedelta(days=1)
    return start, end


def _snapshot_for_day(anchor_day: date, now: datetime, config: dict[str, Any]) -> WorkSnapshot:
    daily_value = float(config["monthly_salary"]) / float(config["paid_days"])
    if anchor_day.weekday() not in config["workdays"]:
        return WorkSnapshot(anchor_day, "off", 0.0, 0.0, daily_value, 0.0, 0.0, None)

    bounds = [_session_bounds(anchor_day, session) for session in config["sessions"]]
    scheduled = sum((end - start).total_seconds() for start, end in bounds)
    elapsed = sum(max(0.0, min((now - start).total_seconds(), (end - start).total_seconds())) for start, end in bounds)
    first_start, final_end = bounds[0][0], max(end for _, end in bounds)
    active_bounds = next(((start, end) for start, end in bounds if start <= now < end), None)

    if now < first_start:
        phase, transition = "upcoming", first_start
    elif active_bounds:
        phase, transition = "earning", active_bounds[1]
    elif now >= final_end:
        phase, transition = "complete", None
    else:
        phase = "pause"
        transition = next((start for start, _ in bounds if start > now), final_end)

    progress = min(1.0, elapsed / scheduled) if scheduled else 0.0
    return WorkSnapshot(anchor_day, phase, progress, daily_value * progress, daily_value, elapsed, scheduled, transition)


def get_snapshot(now: datetime, config: dict[str, Any]) -> WorkSnapshot:
    """Return the relevant schedule, including an overnight shift from yesterday."""
    today = _snapshot_for_day(now.date(), now, config)
    yesterday = _snapshot_for_day(now.date() - timedelta(days=1), now, config)
    if yesterday.phase in {"earning", "pause"} and yesterday.next_transition and now < yesterday.next_transition:
        return yesterday
    return today


def format_money(value: float, currency: str) -> str:
    if abs(value) >= 10000:
        return f"{currency}{value:,.0f}"
    return f"{currency}{value:,.2f}"


def format_percent(progress: float) -> str:
    """Format a percentage without an artificial leading zero."""
    return f"{max(0.0, min(1.0, progress)) * 100:.1f}%"


def format_gold_weight(value: float) -> str:
    """Express a value as gold grams using the fixed historical reference."""
    return f"{max(0.0, value) / HISTORICAL_GOLD_PRICE_PER_GRAM:.2f}g"


def format_duration(seconds: float) -> str:
    minutes = max(0, round(seconds / 60))
    hours, minutes = divmod(minutes, 60)
    return f"{hours}小时{minutes:02d}分"


def blend(first: str, second: str, amount: float) -> str:
    amount = max(0.0, min(1.0, amount))
    first_rgb = tuple(int(first[i : i + 2], 16) for i in (1, 3, 5))
    second_rgb = tuple(int(second[i : i + 2], 16) for i in (1, 3, 5))
    rgb = tuple(round(a + (b - a) * amount) for a, b in zip(first_rgb, second_rgb))
    return "#" + "".join(f"{part:02x}" for part in rgb)


class SlowEarnApp:
    def __init__(self) -> None:
        self.config = load_config()
        self.toast_until: datetime | None = None
        self.root = tk.Tk()
        self.root.title("慢慢赚钱 · 日进斗金")
        self.root.overrideredirect(True)
        self.root.resizable(False, False)
        self.root.configure(bg=TRANSPARENT_COLOR)
        self.root.attributes("-topmost", self.config["topmost"])
        self.transparent_background = False
        try:
            self.root.attributes("-transparentcolor", TRANSPARENT_COLOR)
            self.transparent_background = True
        except tk.TclError:
            self.root.configure(bg="#0A1B2E")

        position = self.config.get("window_position")
        if position:
            geometry = f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}+{position[0]}+{position[1]}"
        else:
            x = max(20, self.root.winfo_screenwidth() - WINDOW_WIDTH - 34)
            y = max(20, self.root.winfo_screenheight() - WINDOW_HEIGHT - 78)
            geometry = f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}+{x}+{y}"
        self.root.geometry(geometry)

        canvas_background = TRANSPARENT_COLOR if self.transparent_background else "#0A1B2E"
        self.canvas = tk.Canvas(self.root, width=WINDOW_WIDTH, height=WINDOW_HEIGHT, bg=canvas_background, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self.drag_origin: tuple[int, int] | None = None
        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.root.bind_all("<Control-comma>", lambda _event: self.open_settings())
        self.root.bind_all("<Escape>", lambda _event: self.close())
        self.root.protocol("WM_DELETE_WINDOW", self.close)

        self.draw()
        self.tick()
        if not self.config["seen_welcome"]:
            self.root.after(350, lambda: self.open_settings(welcome=True))

    def rounded_box(self, x1: float, y1: float, x2: float, y2: float, radius: float, **kwargs: Any) -> int:
        points = [
            x1 + radius, y1, x2 - radius, y1, x2, y1, x2, y1 + radius,
            x2, y2 - radius, x2, y2, x2 - radius, y2, x1 + radius, y2,
            x1, y2, x1, y2 - radius, x1, y1 + radius, x1, y1,
        ]
        return self.canvas.create_polygon(points, smooth=True, splinesteps=18, **kwargs)

    def draw_arc(self, progress: float) -> None:
        box = (70, 35, 310, 275)
        self.canvas.create_arc(*box, start=222, extent=276, style="arc", outline="#294F6C", width=6)
        segments = round(progress * 88)
        for part in range(segments):
            color = blend("#36B9E4", "#C6F4FF", part / max(1, 87))
            self.canvas.create_arc(*box, start=222 - part * (276 / 88), extent=-(276 / 88 + 0.55), style="arc", outline=color, width=6)

        if progress > 0:
            angle = math.radians(222 - 276 * progress)
            x = 190 + 120 * math.cos(angle)
            y = 155 - 120 * math.sin(angle)
            self.canvas.create_oval(x - 5, y - 5, x + 5, y + 5, fill="#E8FBFF", outline="")

    def draw(self) -> None:
        self.canvas.delete("all")
        now = datetime.now()
        snapshot = get_snapshot(now, self.config)

        # The base is color-key transparent: only compact working information is drawn.
        self.canvas.create_oval(17, 12, 34, 29, fill="#D8B75A", outline="")
        self.canvas.create_text(25, 20, text="Au", fill="#19283C", font=("Segoe UI", 7, "bold"))
        self.canvas.create_text(43, 20, anchor="w", text="慢慢赚钱", fill="#D8F6FF", font=("Microsoft YaHei UI", 10, "bold"))
        self.canvas.create_text(43, 36, anchor="w", text="今天也在悄悄变富", fill="#7FB4CA", font=("Microsoft YaHei UI", 8))

        self.rounded_box(284, 8, 312, 32, 10, fill="#123855", outline="#2B6080")
        self.canvas.create_text(298, 20, text="⚙", fill="#C9F5FF", font=("Segoe UI Symbol", 11))
        self.rounded_box(318, 8, 346, 32, 10, fill="#123855", outline="#2B6080")
        self.canvas.create_text(332, 20, text="●", fill="#8DE7FF" if self.config["topmost"] else "#7890A0", font=("Segoe UI", 10, "bold"))
        self.rounded_box(352, 8, 378, 32, 10, fill="#123855", outline="#2B6080")
        self.canvas.create_text(365, 19, text="×", fill="#C9F5FF", font=("Segoe UI", 14))

        self.draw_arc(snapshot.progress)
        phase_label, _phrase = self.phase_copy(snapshot, now)
        self.canvas.create_text(190, 112, text=format_money(snapshot.earned, self.config["currency"]), fill="#F2FCFF", font=("Segoe UI", 31, "bold"))
        self.canvas.create_text(190, 143, text=f"日进斗金 · 约 {format_gold_weight(snapshot.earned)} 黄金", fill="#E4C675", font=("Microsoft YaHei UI", 10, "bold"))
        self.canvas.create_text(190, 162, text="按 ¥280/g 历史参考价 · 不联网", fill="#88B8CB", font=("Microsoft YaHei UI", 8))
        self.canvas.create_text(190, 186, text=format_percent(snapshot.progress), fill="#8DEAFF", font=("Segoe UI", 16, "bold"))
        self.canvas.create_text(190, 208, text=f"{phase_label} · {self.detail_copy(snapshot, now)}", fill="#C4EAF6", font=("Microsoft YaHei UI", 9, "bold"))

        if self.toast_until and now < self.toast_until:
            footer, footer_color = "✓ 已按新参数重新计算", "#A4F5DD"
        else:
            footer, footer_color = "拖动空白处移动 · Ctrl+, 设置", "#7CAEC2"
        self.canvas.create_text(190, 230, text=footer, fill=footer_color, font=("Microsoft YaHei UI", 8))
        self.rounded_box(132, 244, 248, 272, 13, fill="#10405F", outline="#3A94B8")
        self.canvas.create_text(190, 258, text="修改参数  ·  保存即刷新", fill="#D5F8FF", font=("Microsoft YaHei UI", 9, "bold"))

    def phase_copy(self, snapshot: WorkSnapshot, now: datetime) -> tuple[str, str]:
        if snapshot.phase == "off":
            return "今天留白", "不必追赶，休息也是日程的一部分。"
        if snapshot.phase == "upcoming":
            return "尚未开场", "把开始留给自己准备好的那一刻。"
        if snapshot.phase == "pause":
            return "节奏间歇", "短暂放松，下一段很快接上。"
        if snapshot.phase == "complete":
            return "今天抵达", "这条弧已经完整，去享受你的时间。"
        if now.hour < 11:
            return "晨间推进中", "先完成最重要的那一小步。"
        if now.hour < 15:
            return "午后续航中", "慢一点也没关系，方向是对的。"
        return "傍晚冲刺中", "把收尾做漂亮，今天就很值得。"

    def detail_copy(self, snapshot: WorkSnapshot, now: datetime) -> str:
        if snapshot.phase == "earning":
            return f"距收工 {format_duration(snapshot.remaining_seconds)}"
        if snapshot.phase in {"upcoming", "pause"} and snapshot.next_transition:
            return f"{snapshot.next_transition:%H:%M} 继续"
        if snapshot.phase == "complete":
            return "已完成"
        next_day = now.date() + timedelta(days=1)
        while next_day.weekday() not in self.config["workdays"]:
            next_day += timedelta(days=1)
        return f"{WEEKDAY_NAMES[next_day.weekday()]} 再见"

    def tick(self) -> None:
        self.draw()
        self.root.after(1000, self.tick)

    def on_press(self, event: tk.Event[tk.Misc]) -> None:
        x, y = event.x, event.y
        if 284 <= x <= 312 and 8 <= y <= 32:
            self.open_settings()
        elif 318 <= x <= 346 and 8 <= y <= 32:
            self.config["topmost"] = not self.config["topmost"]
            self.root.attributes("-topmost", self.config["topmost"])
            save_config(self.config)
            self.draw()
        elif 352 <= x <= 379 and 8 <= y <= 32:
            self.close()
        elif 132 <= x <= 248 and 244 <= y <= 272:
            self.open_settings()
        else:
            self.drag_origin = (event.x_root - self.root.winfo_x(), event.y_root - self.root.winfo_y())

    def on_drag(self, event: tk.Event[tk.Misc]) -> None:
        if self.drag_origin:
            x = event.x_root - self.drag_origin[0]
            y = event.y_root - self.drag_origin[1]
            self.root.geometry(f"+{x}+{y}")

    def on_release(self, _event: tk.Event[tk.Misc]) -> None:
        if self.drag_origin:
            self.config["window_position"] = [self.root.winfo_x(), self.root.winfo_y()]
            save_config(self.config)
        self.drag_origin = None

    def open_settings(self, welcome: bool = False) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title("欢迎使用慢慢赚钱" if welcome else "调整今日节奏")
        dialog.configure(bg="#0B2034")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.attributes("-topmost", True)
        dialog.grab_set()
        dialog.geometry("460x452")

        title = "先画出你的工作节奏" if welcome else "修改后，金额会立刻重算"
        tk.Label(dialog, text=title, bg="#0B2034", fg="#EAFBFF", font=("Microsoft YaHei UI", 15, "bold")).pack(anchor="w", padx=26, pady=(22, 3))
        tk.Label(dialog, text="信息只会保存在这台电脑，不会联网或上传。", bg="#0B2034", fg="#8DB4C6", font=("Microsoft YaHei UI", 9)).pack(anchor="w", padx=26, pady=(0, 14))

        form = tk.Frame(dialog, bg="#0B2034")
        form.pack(fill="x", padx=26)
        form.columnconfigure(1, weight=1)
        entries: dict[str, tk.Entry] = {}

        def add_field(row: int, key: str, label: str, value: str) -> None:
            tk.Label(form, text=label, bg="#0B2034", fg="#CBEAF5", font=("Microsoft YaHei UI", 9, "bold"), width=14, anchor="w").grid(row=row, column=0, sticky="w", pady=5)
            entry = tk.Entry(form, bg="#15334E", fg="#F4FDFF", insertbackground="#F4FDFF", relief="flat", highlightthickness=1, highlightbackground="#2B5A77", highlightcolor="#79DDF5", font=("Segoe UI", 11))
            entry.insert(0, value)
            entry.grid(row=row, column=1, sticky="ew", ipady=6, pady=5)
            entries[key] = entry

        add_field(0, "salary", "月薪", f"{self.config['monthly_salary']:g}")
        add_field(1, "paid_days", "每月计薪工作日", f"{self.config['paid_days']:g}")
        sessions = self.config["sessions"]
        add_field(2, "session_1", "第一时段", f"{sessions[0]['start']} - {sessions[0]['end']}")
        add_field(3, "session_2", "第二时段（可选）", f"{sessions[1]['start']} - {sessions[1]['end']}" if len(sessions) > 1 else "")
        add_field(4, "workdays", "每周工作日", "、".join(str(day + 1) for day in self.config["workdays"]))
        tk.Label(dialog, text="时段格式：09:30 - 12:00；工作日填 1、2、3、4、5。", bg="#0B2034", fg="#789FB2", font=("Microsoft YaHei UI", 8)).pack(anchor="w", padx=26, pady=(7, 0))

        error = tk.Label(dialog, text="", bg="#0B2034", fg="#FFB39D", font=("Microsoft YaHei UI", 9), height=1)
        error.pack(anchor="w", padx=26, pady=(8, 0))
        buttons = tk.Frame(dialog, bg="#0B2034")
        buttons.pack(fill="x", padx=26, pady=(8, 20))

        def commit(_event: tk.Event[tk.Misc] | None = None) -> None:
            try:
                updated = config_from_form(
                    self.config,
                    entries["salary"].get(),
                    entries["paid_days"].get(),
                    entries["session_1"].get(),
                    entries["session_2"].get(),
                    entries["workdays"].get(),
                )
                self.config = updated
                save_config(self.config)
                self.toast_until = datetime.now() + timedelta(seconds=5)
                self.draw()
                dialog.destroy()
            except ValueError as exc:
                error.configure(text=str(exc))

        tk.Button(buttons, text="取消", command=dialog.destroy, bg="#173550", fg="#BFE6F2", activebackground="#244967", activeforeground="#FFFFFF", relief="flat", font=("Microsoft YaHei UI", 9, "bold"), padx=20, pady=8).pack(side="left")
        tk.Button(buttons, text="保存并立即刷新", command=commit, bg="#4FC5E6", fg="#082033", activebackground="#8CEBFF", activeforeground="#061725", relief="flat", font=("Microsoft YaHei UI", 9, "bold"), padx=18, pady=8).pack(side="right")
        dialog.bind("<Control-s>", commit)
        dialog.bind("<Return>", commit)
        entries["salary"].focus_set()

    def close(self) -> None:
        self.config["window_position"] = [self.root.winfo_x(), self.root.winfo_y()]
        save_config(self.config)
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


if __name__ == "__main__":
    SlowEarnApp().run()
