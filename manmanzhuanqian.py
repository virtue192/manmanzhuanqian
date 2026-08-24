"""慢慢赚钱 — a private, local-first desktop value pulse for Windows.

The application intentionally uses only Python's standard library.  Salary
settings never leave the device and the interface is painted from primitives,
so there are no remote fonts, analytics, or bundled personal information.
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
WINDOW_WIDTH = 450
WINDOW_HEIGHT = 492

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
    return WorkSnapshot(
        anchor_day=anchor_day,
        phase=phase,
        progress=progress,
        earned=daily_value * progress,
        daily_value=daily_value,
        active_seconds=elapsed,
        scheduled_seconds=scheduled,
        next_transition=transition,
    )


def get_snapshot(now: datetime, config: dict[str, Any]) -> WorkSnapshot:
    """Return the relevant schedule, including an overnight shift from yesterday."""
    today = _snapshot_for_day(now.date(), now, config)
    yesterday = _snapshot_for_day(now.date() - timedelta(days=1), now, config)

    # An overnight session remains the relevant day while it is live or between
    # two overnight periods.  Otherwise today's schedule takes precedence.
    if yesterday.phase in {"earning", "pause"} and yesterday.next_transition and now < yesterday.next_transition:
        return yesterday
    return today


def format_money(value: float, currency: str) -> str:
    if abs(value) >= 10000:
        return f"{currency}{value:,.0f}"
    return f"{currency}{value:,.2f}"


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
        self.root = tk.Tk()
        self.root.title("慢慢赚钱 · 今日价值弧")
        self.root.configure(bg="#10151D")
        self.root.overrideredirect(True)
        self.root.resizable(False, False)
        self.root.attributes("-topmost", self.config["topmost"])

        position = self.config.get("window_position")
        if position:
            geometry = f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}+{position[0]}+{position[1]}"
        else:
            screen_x = max(20, self.root.winfo_screenwidth() - WINDOW_WIDTH - 46)
            screen_y = max(20, self.root.winfo_screenheight() - WINDOW_HEIGHT - 92)
            geometry = f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}+{screen_x}+{screen_y}"
        self.root.geometry(geometry)

        self.canvas = tk.Canvas(
            self.root,
            width=WINDOW_WIDTH,
            height=WINDOW_HEIGHT,
            bg="#10151D",
            highlightthickness=0,
            bd=0,
        )
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
        box = (101, 93, 349, 341)
        self.canvas.create_arc(*box, start=222, extent=276, style="arc", outline="#27313E", width=15)
        segments = max(1, round(progress * 96))
        for part in range(segments):
            amount = part / max(1, 95)
            color = blend("#FF7A59", "#69E0C5", amount)
            self.canvas.create_arc(
                *box,
                start=222 - part * (276 / 96),
                extent=-(276 / 96 + 0.7),
                style="arc",
                outline=color,
                width=15,
            )

        angle = math.radians(222 - 276 * progress)
        endpoint_x = 225 + 124 * math.cos(angle)
        endpoint_y = 217 - 124 * math.sin(angle)
        if progress > 0:
            self.canvas.create_oval(endpoint_x - 6, endpoint_y - 6, endpoint_x + 6, endpoint_y + 6, fill="#E9FFF9", outline="")

    def draw(self) -> None:
        self.canvas.delete("all")
        now = datetime.now()
        snapshot = get_snapshot(now, self.config)

        # A quiet, hand-drawn feeling background made with native canvas layers.
        self.rounded_box(5, 5, 445, 487, 30, fill="#151C27", outline="#273343", width=1)
        self.canvas.create_oval(302, 17, 470, 185, fill="#1B3440", outline="")
        self.canvas.create_oval(-58, 334, 104, 496, fill="#25223A", outline="")
        self.canvas.create_oval(326, 340, 406, 420, fill="#243A3E", outline="")

        # Header and window controls.
        self.canvas.create_oval(28, 25, 55, 52, fill="#FF7A59", outline="")
        self.canvas.create_arc(33, 30, 50, 47, start=206, extent=220, style="arc", width=2, outline="#FFF6ED")
        self.canvas.create_text(66, 30, anchor="w", text="慢慢赚钱", fill="#F6F7FB", font=("Microsoft YaHei UI", 11, "bold"))
        self.canvas.create_text(66, 47, anchor="w", text="把今天，走成一条温柔的弧", fill="#8E9BAD", font=("Microsoft YaHei UI", 9))

        pin_fill = "#69E0C5" if self.config["topmost"] else "#8996A8"
        self.rounded_box(344, 23, 376, 52, 12, fill="#202A37", outline="")
        self.canvas.create_text(360, 38, text="●", fill=pin_fill, font=("Segoe UI", 11, "bold"))
        self.rounded_box(383, 23, 415, 52, 12, fill="#202A37", outline="")
        self.canvas.create_text(399, 37, text="×", fill="#AEB9C8", font=("Segoe UI", 16))

        self.draw_arc(snapshot.progress)
        phase_label, phrase = self.phase_copy(snapshot, now)
        self.canvas.create_text(225, 147, text=phase_label, fill="#A9B6C8", font=("Microsoft YaHei UI", 10, "bold"))
        self.canvas.create_text(
            225,
            192,
            text=format_money(snapshot.earned, self.config["currency"]),
            fill="#F9FAFD",
            font=("Segoe UI", 30, "bold"),
        )
        self.canvas.create_text(225, 223, text="今日已沉淀的价值", fill="#8290A3", font=("Microsoft YaHei UI", 9))
        self.canvas.create_text(225, 260, text=f"{snapshot.progress * 100:05.1f}%", fill="#75DAC4", font=("Segoe UI", 15, "bold"))
        self.canvas.create_text(225, 284, text=f"日目标  {format_money(snapshot.daily_value, self.config['currency'])}", fill="#AAB5C5", font=("Microsoft YaHei UI", 9))

        self.rounded_box(28, 360, 422, 420, 18, fill="#1D2734", outline="#2C3948")
        self.canvas.create_text(47, 379, anchor="w", text="此刻节奏", fill="#8E9BAD", font=("Microsoft YaHei UI", 9))
        self.canvas.create_text(47, 403, anchor="w", text=phrase, fill="#EFF4FA", font=("Microsoft YaHei UI", 11, "bold"))
        detail = self.detail_copy(snapshot, now)
        self.canvas.create_text(401, 393, anchor="e", text=detail, fill="#70DCC4", font=("Microsoft YaHei UI", 9, "bold"))

        self.rounded_box(28, 435, 210, 468, 14, fill="#22303E", outline="")
        self.canvas.create_text(119, 451, text="拖动顶部即可移动", fill="#9BA8B8", font=("Microsoft YaHei UI", 8))
        self.rounded_box(277, 435, 422, 468, 14, fill="#FF7A59", outline="")
        self.canvas.create_text(349, 451, text="调整今日节奏  ›", fill="#FFF9F5", font=("Microsoft YaHei UI", 9, "bold"))

    def phase_copy(self, snapshot: WorkSnapshot, now: datetime) -> tuple[str, str]:
        if snapshot.phase == "off":
            return "今天留白", "不必追赶，休息也是日程的一部分。"
        if snapshot.phase == "upcoming":
            return "尚未开场", "把开始留给自己准备好的那一刻。"
        if snapshot.phase == "pause":
            return "节奏间歇", "短暂放松，下一段很快接上。"
        if snapshot.phase == "complete":
            return "今天抵达", "这条弧已经完整，去享受你的时间。"
        hour = now.hour
        if hour < 11:
            return "晨间推进中", "先完成最重要的那一小步。"
        if hour < 15:
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
        if 344 <= x <= 376 and 23 <= y <= 52:
            self.config["topmost"] = not self.config["topmost"]
            self.root.attributes("-topmost", self.config["topmost"])
            save_config(self.config)
            self.draw()
        elif 383 <= x <= 415 and 23 <= y <= 52:
            self.close()
        elif 270 <= x <= 428 and 430 <= y <= 475:
            self.open_settings()
        elif y <= 75:
            self.drag_origin = (event.x_root - self.root.winfo_x(), event.y_root - self.root.winfo_y())

    def on_drag(self, event: tk.Event[tk.Misc]) -> None:
        if not self.drag_origin:
            return
        x = event.x_root - self.drag_origin[0]
        y = event.y_root - self.drag_origin[1]
        self.root.geometry(f"+{x}+{y}")

    def on_release(self, _event: tk.Event[tk.Misc]) -> None:
        self.drag_origin = None

    def open_settings(self, welcome: bool = False) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title("欢迎使用慢慢赚钱" if welcome else "调整今日节奏")
        dialog.configure(bg="#151C27")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.attributes("-topmost", True)
        dialog.grab_set()
        dialog.geometry("420x504")

        title = "先画出你的工作节奏" if welcome else "调整你的价值弧"
        subtitle = "信息只会保存在这台电脑，不会联网或上传。"
        tk.Label(dialog, text=title, bg="#151C27", fg="#F7F9FC", font=("Microsoft YaHei UI", 16, "bold")).pack(anchor="w", padx=28, pady=(25, 4))
        tk.Label(dialog, text=subtitle, bg="#151C27", fg="#93A0B2", font=("Microsoft YaHei UI", 9)).pack(anchor="w", padx=28, pady=(0, 18))

        form = tk.Frame(dialog, bg="#151C27")
        form.pack(fill="x", padx=28)
        entries: dict[str, tk.Entry] = {}

        def add_field(key: str, label: str, value: str, hint: str = "") -> None:
            tk.Label(form, text=label, bg="#151C27", fg="#C9D2DF", font=("Microsoft YaHei UI", 9, "bold")).pack(anchor="w", pady=(9, 4))
            entry = tk.Entry(form, bg="#202B39", fg="#F7F9FC", insertbackground="#F7F9FC", relief="flat", font=("Segoe UI", 11))
            entry.insert(0, value)
            entry.pack(fill="x", ipady=8)
            entries[key] = entry
            if hint:
                tk.Label(form, text=hint, bg="#151C27", fg="#758399", font=("Microsoft YaHei UI", 8)).pack(anchor="w", pady=(3, 0))

        add_field("salary", "月薪（税前或你希望追踪的数字）", f"{self.config['monthly_salary']:g}")
        add_field("paid_days", "每月计薪工作日", f"{self.config['paid_days']:g}")
        sessions = self.config["sessions"]
        add_field("session_1", "第一时段", f"{sessions[0]['start']} - {sessions[0]['end']}", "格式：09:30 - 12:00；可把午休自然排除。")
        add_field("session_2", "第二时段（可选）", f"{sessions[1]['start']} - {sessions[1]['end']}" if len(sessions) > 1 else "")
        days_text = "、".join(str(day + 1) for day in self.config["workdays"])
        add_field("workdays", "每周工作日", days_text, "填 1 到 7，例如 1、2、3、4、5（周一至周五）。")

        error = tk.Label(dialog, text="", bg="#151C27", fg="#FF9D87", font=("Microsoft YaHei UI", 9))
        error.pack(anchor="w", padx=28, pady=(12, 0))

        buttons = tk.Frame(dialog, bg="#151C27")
        buttons.pack(fill="x", padx=28, pady=(12, 24))

        def commit() -> None:
            try:
                sessions_raw = [entries["session_1"].get().strip(), entries["session_2"].get().strip()]
                sessions_data = []
                for session in sessions_raw:
                    if not session:
                        continue
                    parts = re.split(r"\s*[-—–]\s*", session)
                    if len(parts) != 2:
                        raise ValueError("工作时段请写成 09:30 - 12:00")
                    sessions_data.append({"start": parts[0], "end": parts[1]})
                workdays = sorted({int(number) - 1 for number in re.findall(r"[1-7]", entries["workdays"].get())})
                if not workdays:
                    raise ValueError("请至少选择一个每周工作日")
                updated = copy.deepcopy(self.config)
                updated["monthly_salary"] = float(entries["salary"].get().replace(",", ""))
                updated["paid_days"] = float(entries["paid_days"].get())
                if updated["monthly_salary"] <= 0 or updated["paid_days"] <= 0:
                    raise ValueError("月薪和计薪工作日必须大于 0")
                updated["sessions"] = normalise_sessions(sessions_data)
                updated["workdays"] = workdays
                updated["seen_welcome"] = True
                self.config = updated
                save_config(self.config)
                self.draw()
                dialog.destroy()
            except ValueError as exc:
                error.configure(text=str(exc))

        tk.Button(buttons, text="稍后再说", command=dialog.destroy, bg="#253141", fg="#B8C3D0", activebackground="#2D3B4D", activeforeground="#FFFFFF", relief="flat", font=("Microsoft YaHei UI", 9, "bold"), padx=16, pady=8).pack(side="left")
        tk.Button(buttons, text="保存并开始", command=commit, bg="#FF7A59", fg="#FFF9F5", activebackground="#FF9A7E", activeforeground="#FFFFFF", relief="flat", font=("Microsoft YaHei UI", 9, "bold"), padx=19, pady=8).pack(side="right")

    def close(self) -> None:
        self.config["window_position"] = [self.root.winfo_x(), self.root.winfo_y()]
        save_config(self.config)
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


if __name__ == "__main__":
    SlowEarnApp().run()
