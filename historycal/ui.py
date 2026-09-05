"""
ui.py
=====

The Tkinter application itself. This file wires the three engines
together:

    calendar_math.py  -> which dates exist, what grid to draw
    storage.py        -> the user's own birthdays/events
    history_api.py    -> "on this day" historical events (network + cache)
    theme.py           -> turning all of that into a pseudo-3D looking canvas

Two things worth knowing before reading the code:

* The year can be *any* integer, including negative (BCE) and far beyond
  9999. We never use `datetime` for navigation - only `calendar_math`,
  which has no such limit. The year field is a plain text Entry (not a
  numeric spinbox) specifically so you can type something like
  `-12000` or `999999999` and press Enter.

* Fetching historical events from Wikipedia happens on a background
  thread. Tkinter widgets may only be touched from the main thread, so
  the worker thread never updates the UI directly - it drops its result
  into a `queue.Queue`, and the main thread polls that queue every
  100ms via `self.after(...)`. This is the standard, safe way to combine
  threads with Tkinter.
"""

from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox

from . import calendar_math as cm
from . import theme
from .storage import EventStore, CATEGORIES
from . import history_api as hapi


APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_PATH = os.path.join(APP_DIR, "data", "events.json")
CACHE_DIR = os.path.join(APP_DIR, "data", "history_cache")

WEEKDAY_HEADER = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]

CARD_MARGIN = 6


class CalendarApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("HistoryCal - The Infinite Battle Calendar")
        self.geometry("1180x760")
        self.minsize(860, 560)
        self.configure(bg="#0b0b12")

        os.makedirs(os.path.dirname(DATA_PATH), exist_ok=True)
        self.store = EventStore(DATA_PATH)
        if self.store.last_load_warning:
            self.after(300, lambda: messagebox.showwarning(
                "Events file recovered", self.store.last_load_warning))

        today_epoch = cm.to_epoch_day(*_system_today())
        self.today = cm.from_epoch_day(today_epoch)
        self.view_year, self.view_month, _ = self.today
        self.selected_date = self.today

        self.battles_only = tk.BooleanVar(value=False)
        self.year_var = tk.StringVar(value=str(self.view_year))
        self.status_var = tk.StringVar(value="Ready")

        self._history_queue: "queue.Queue" = queue.Queue()
        self._history_request_id = 0
        self._history_cache_memory: dict[tuple[int, int], hapi.HistoryResult] = {}

        self._day_cell_ids: dict[tuple[int, int], int] = {}  # (row,col)->canvas group tag

        self._build_layout()
        self._render_month()
        self._select_date(*self.selected_date)
        self.after(100, self._poll_history_queue)

        self.bind("<Left>", lambda e: self._shift_month(-1))
        self.bind("<Right>", lambda e: self._shift_month(1))
        self.bind("<Prior>", lambda e: self._shift_year(-1))   # Page Up
        self.bind("<Next>", lambda e: self._shift_year(1))     # Page Down
        self.bind("t", lambda e: self._go_to_today())
        self.bind("n", lambda e: self._open_add_event_dialog())

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _build_layout(self):
        toolbar = tk.Frame(self, bg="#15151f", height=52)
        toolbar.pack(side="top", fill="x")
        toolbar.pack_propagate(False)

        def tbtn(parent, text, cmd, width=3):
            b = tk.Button(parent, text=text, command=cmd, width=width,
                          bg="#23233a", fg="#eee", activebackground="#33335a",
                          relief="flat", font=("Segoe UI", 11, "bold"),
                          cursor="hand2")
            return b

        tbtn(toolbar, "«", lambda: self._shift_year(-1)).pack(side="left", padx=(10, 0), pady=8)
        tbtn(toolbar, "‹", lambda: self._shift_month(-1)).pack(side="left", padx=2, pady=8)

        year_entry = tk.Entry(toolbar, textvariable=self.year_var, width=8,
                               justify="center", font=("Segoe UI", 12, "bold"),
                               bg="#0b0b12", fg="#f2d98b", insertbackground="#fff",
                               relief="flat")
        year_entry.pack(side="left", padx=6, pady=8)
        year_entry.bind("<Return>", lambda e: self._jump_to_year_field())

        self.month_label = tk.Label(toolbar, text="", font=("Segoe UI", 13, "bold"),
                                     bg="#15151f", fg="#f2f2f2", width=12)
        self.month_label.pack(side="left", padx=6)

        tbtn(toolbar, "›", lambda: self._shift_month(1)).pack(side="left", padx=2, pady=8)
        tbtn(toolbar, "»", lambda: self._shift_year(1)).pack(side="left", padx=(0, 10), pady=8)

        tbtn(toolbar, "Today", self._go_to_today, width=6).pack(side="left", padx=6)
        tbtn(toolbar, "+ Add Event", self._open_add_event_dialog, width=12).pack(side="left", padx=6)

        battles_chk = tk.Checkbutton(
            toolbar, text="Battles only", variable=self.battles_only,
            command=self._on_battles_toggle, bg="#15151f", fg="#ddd",
            selectcolor="#23233a", activebackground="#15151f",
            font=("Segoe UI", 10))
        battles_chk.pack(side="left", padx=12)

        tbtn(toolbar, "⟳ Refresh", self._force_refresh_history, width=10).pack(side="left", padx=6)

        # a separate, slim full-width strip for status text - keeping it
        # off the crowded button row means a long message can never
        # shove buttons off-screen or get clipped at the window edge.
        status_bar = tk.Frame(self, bg="#0e0e16", height=22)
        status_bar.pack(side="top", fill="x")
        status_bar.pack_propagate(False)
        status_label = tk.Label(status_bar, textvariable=self.status_var,
                                 bg="#0e0e16", fg="#8899aa", font=("Segoe UI", 9),
                                 anchor="w")
        status_label.pack(side="left", padx=14)

        # main split: background canvas (day-specific gradient) with the
        # month grid on top, and a detail panel on the right
        body = tk.Frame(self, bg="#0b0b12")
        body.pack(side="top", fill="both", expand=True)

        self.bg_canvas = tk.Canvas(body, highlightthickness=0, bd=0)
        self.bg_canvas.pack(side="left", fill="both", expand=True)
        self.bg_canvas.bind("<Configure>", lambda e: self._render_month())
        self.bg_canvas.bind("<Button-1>", self._on_grid_click)

        detail_frame = tk.Frame(body, bg="#101018", width=360)
        detail_frame.pack(side="right", fill="y")
        detail_frame.pack_propagate(False)
        self._build_detail_panel(detail_frame)

    def _build_detail_panel(self, parent):
        pad = 14
        self.date_header = tk.Label(parent, text="", font=("Georgia", 18, "bold"),
                                     bg="#101018", fg="#f2d98b", anchor="w",
                                     wraplength=330, justify="left")
        self.date_header.pack(fill="x", padx=pad, pady=(pad, 0))

        self.weekday_label = tk.Label(parent, text="", font=("Segoe UI", 10),
                                       bg="#101018", fg="#9999aa", anchor="w")
        self.weekday_label.pack(fill="x", padx=pad)

        self.flavor_label = tk.Label(parent, text="", font=("Georgia", 11, "italic"),
                                      bg="#101018", fg="#cfd6ff", anchor="w",
                                      wraplength=330, justify="left")
        self.flavor_label.pack(fill="x", padx=pad, pady=(4, 10))

        tk.Frame(parent, bg="#2a2a3a", height=1).pack(fill="x", padx=pad)

        tk.Label(parent, text="YOUR EVENTS", font=("Segoe UI", 9, "bold"),
                 bg="#101018", fg="#777788", anchor="w").pack(fill="x", padx=pad, pady=(10, 2))
        self.user_events_frame = tk.Frame(parent, bg="#101018")
        self.user_events_frame.pack(fill="x", padx=pad)

        tk.Frame(parent, bg="#2a2a3a", height=1).pack(fill="x", padx=pad, pady=(10, 0))

        tk.Label(parent, text="ON THIS DAY IN HISTORY", font=("Segoe UI", 9, "bold"),
                 bg="#101018", fg="#777788", anchor="w").pack(fill="x", padx=pad, pady=(10, 2))

        hist_container = tk.Frame(parent, bg="#101018")
        hist_container.pack(fill="both", expand=True, padx=pad, pady=(0, pad))

        hist_scroll = tk.Scrollbar(hist_container)
        hist_scroll.pack(side="right", fill="y")
        self.history_text = tk.Text(hist_container, wrap="word", bg="#0b0b12",
                                     fg="#e6e6e6", relief="flat", font=("Segoe UI", 10),
                                     yscrollcommand=hist_scroll.set, padx=8, pady=8,
                                     state="disabled", cursor="arrow")
        self.history_text.pack(side="left", fill="both", expand=True)
        hist_scroll.config(command=self.history_text.yview)
        self.history_text.tag_configure("year", foreground="#f2d98b",
                                         font=("Segoe UI", 10, "bold"))
        self.history_text.tag_configure("battle", foreground="#ff8a80")

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def _shift_month(self, delta: int):
        self.view_year, self.view_month, _ = cm.add_months(
            self.view_year, self.view_month, 1, delta)
        self.year_var.set(str(self.view_year))
        self._render_month()

    def _shift_year(self, delta: int):
        self.view_year += delta
        self.year_var.set(str(self.view_year))
        self._render_month()

    def _jump_to_year_field(self):
        text = self.year_var.get().strip()
        try:
            year = int(text)
        except ValueError:
            messagebox.showerror("Invalid year", f"'{text}' is not a whole number.")
            self.year_var.set(str(self.view_year))
            return
        self.view_year = year
        self._render_month()

    def _go_to_today(self):
        self.view_year, self.view_month, _ = self.today
        self.year_var.set(str(self.view_year))
        self._render_month()
        self._select_date(*self.today)

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _render_month(self):
        self.month_label.config(
            text=f"{cm.MONTH_NAMES[self.view_month - 1]}")

        canvas = self.bg_canvas
        canvas.delete("all")
        width = max(canvas.winfo_width(), 400)
        height = max(canvas.winfo_height(), 300)

        sel_year, sel_month, sel_day = self.selected_date
        bg_palette = theme.palette_for_date(sel_year, sel_month, sel_day)
        theme.draw_vertical_gradient(canvas, 0, 0, width, height,
                                      bg_palette["bg_top"], bg_palette["bg_bottom"],
                                      steps=40)

        grid = cm.build_month_grid(self.view_year, self.view_month)
        rows = grid.total_cells // 7

        top_margin = 46
        side_margin = 18
        header_h = 26
        grid_w = width - 2 * side_margin
        grid_h = height - top_margin - side_margin
        cell_w = grid_w / 7
        cell_h = (grid_h - header_h) / max(rows, 1)

        for col, name in enumerate(WEEKDAY_HEADER):
            x = side_margin + col * cell_w + cell_w / 2
            canvas.create_text(x, top_margin - 8, text=name, fill="#cfd6ff",
                                font=("Segoe UI", 10, "bold"))

        neutral = theme.neutral_card_palette()
        self._cell_bboxes: dict[tuple[int, int], tuple[float, float, float, float]] = {}
        self._cell_dates: dict[tuple[int, int], tuple[int, int, int]] = {}

        for i in range(grid.leading_blanks, grid.leading_blanks + grid.num_days):
            row, col = divmod(i, 7)
            day = i - grid.leading_blanks + 1
            x1 = side_margin + col * cell_w + CARD_MARGIN
            y1 = top_margin + header_h + row * cell_h + CARD_MARGIN
            x2 = side_margin + (col + 1) * cell_w - CARD_MARGIN
            y2 = top_margin + header_h + (row + 1) * cell_h - CARD_MARGIN

            is_selected = (self.view_year, self.view_month, day) == self.selected_date
            is_today = (self.view_year, self.view_month, day) == self.today

            palette = dict(neutral)
            if is_selected:
                palette["accent"] = bg_palette["accent"]

            theme.draw_3d_card(canvas, x1, y1, x2, y2, palette,
                                depth=4, selected=is_selected)

            day_color = "#fff5d0" if is_today else "#e8e8f0"
            canvas.create_text(x1 + 10, y1 + 10, text=str(day), anchor="nw",
                                fill=day_color,
                                font=("Segoe UI", 12, "bold" if is_today else "normal"))
            if is_today:
                canvas.create_text(x2 - 8, y1 + 10, text="TODAY", anchor="ne",
                                    fill=bg_palette["accent"], font=("Segoe UI", 7, "bold"))

            has_events = bool(self.store.events_for(self.view_year, self.view_month, day))
            if has_events:
                canvas.create_oval(x1 + 10, y2 - 18, x1 + 18, y2 - 10,
                                    fill=neutral["accent"], outline="")

            cached = self._history_cache_memory.get((self.view_month, day))
            if cached and cached.events:
                canvas.create_text(x2 - 10, y2 - 12, text="⚔", anchor="se",
                                    fill="#ff8a80", font=("Segoe UI", 11))

            self._cell_bboxes[(row, col)] = (x1, y1, x2, y2)
            self._cell_dates[(row, col)] = (self.view_year, self.view_month, day)

    def _on_grid_click(self, event):
        for (row, col), (x1, y1, x2, y2) in self._cell_bboxes.items():
            if x1 <= event.x <= x2 and y1 <= event.y <= y2:
                y, m, d = self._cell_dates[(row, col)]
                self._select_date(y, m, d)
                return

    # ------------------------------------------------------------------
    # Selection + detail panel
    # ------------------------------------------------------------------

    def _select_date(self, year: int, month: int, day: int):
        self.selected_date = (year, month, day)
        self._render_month()

        self.date_header.config(text=cm.format_date(year, month, day))
        weekday = cm.WEEKDAY_NAMES[cm.weekday_index(year, month, day)]
        self.weekday_label.config(text=weekday)
        self.flavor_label.config(text="\u201c" + theme.flavor_text_for_date(year, month, day) + "\u201d")

        self._render_user_events()
        self._request_history(month, day)

    def _render_user_events(self):
        for w in self.user_events_frame.winfo_children():
            w.destroy()

        year, month, day = self.selected_date
        events = self.store.events_for(year, month, day)
        if not events:
            tk.Label(self.user_events_frame, text="No events yet for this day.",
                     bg="#101018", fg="#666677", font=("Segoe UI", 9, "italic"),
                     anchor="w").pack(fill="x", pady=2)
            return

        for ev in events:
            row = tk.Frame(self.user_events_frame, bg="#101018")
            row.pack(fill="x", pady=2)
            tag = "🎂" if ev.category == "birthday" else "📌"
            label_text = f"{tag} {ev.title}"
            if not ev.recurring and ev.year:
                label_text += f" ({ev.year})"
            tk.Label(row, text=label_text, bg="#101018", fg="#e6e6e6",
                     font=("Segoe UI", 10), anchor="w").pack(side="left", fill="x", expand=True)
            tk.Button(row, text="✕", command=lambda eid=ev.id: self._delete_event(eid),
                      bg="#101018", fg="#996666", relief="flat", bd=0,
                      activebackground="#101018", cursor="hand2").pack(side="right")

    def _delete_event(self, event_id: str):
        self.store.remove(event_id)
        self._render_user_events()
        self._render_month()

    # ------------------------------------------------------------------
    # History fetching (threaded)
    # ------------------------------------------------------------------

    def _request_history(self, month: int, day: int, force: bool = False):
        cache_key = (month, day)
        if not force and cache_key in self._history_cache_memory:
            self._display_history(self._history_cache_memory[cache_key])
            return

        self._history_request_id += 1
        req_id = self._history_request_id
        self.status_var.set("Loading history…")
        self._show_history_loading()

        def worker():
            result = hapi.fetch_on_this_day(month, day, CACHE_DIR, force_refresh=force)
            self._history_queue.put((req_id, cache_key, result))

        threading.Thread(target=worker, daemon=True).start()

    def _force_refresh_history(self):
        _, month, day = self.selected_date
        self._request_history(self.selected_date[1], self.selected_date[2], force=True)

    def _poll_history_queue(self):
        try:
            while True:
                req_id, cache_key, result = self._history_queue.get_nowait()
                self._history_cache_memory[cache_key] = result
                if req_id == self._history_request_id:
                    self._display_history(result)
                    self._render_month()   # picks up the ⚔ marker now that data arrived
        except queue.Empty:
            pass
        self.after(100, self._poll_history_queue)

    def _show_history_loading(self):
        self.history_text.config(state="normal")
        self.history_text.delete("1.0", "end")
        self.history_text.insert("end", "Fetching historical events…")
        self.history_text.config(state="disabled")

    def _display_history(self, result: hapi.HistoryResult):
        if result.source == "network":
            self.status_var.set("● Online - live data from Wikipedia")
        elif result.source == "cache" and result.ok:
            self.status_var.set("● Loaded from local cache")
        elif result.error:
            self.status_var.set("● Offline - see details in the history panel")
        else:
            self.status_var.set("Ready")

        events = result.events
        if self.battles_only.get():
            events = hapi.filter_battles(events)

        self.history_text.config(state="normal")
        self.history_text.delete("1.0", "end")

        if result.error and not events:
            self.history_text.insert("end", result.error)
        elif not events:
            msg = ("No battle-related events found for this day."
                   if self.battles_only.get() else
                   "No recorded historical events for this day.")
            self.history_text.insert("end", msg)
        else:
            for ev in events:
                is_battle = ev.is_battle_related()
                self.history_text.insert("end", f"{cm.format_year(ev.year)}\n", "year")
                tag = "battle" if is_battle else ()
                prefix = "⚔ " if is_battle else ""
                self.history_text.insert("end", f"{prefix}{ev.text}\n\n", tag)

        self.history_text.config(state="disabled")

    def _on_battles_toggle(self):
        _, month, day = self.selected_date
        cache_key = (month, day)
        if cache_key in self._history_cache_memory:
            self._display_history(self._history_cache_memory[cache_key])

    # ------------------------------------------------------------------
    # Add event dialog
    # ------------------------------------------------------------------

    def _open_add_event_dialog(self):
        dialog = tk.Toplevel(self)
        dialog.title("Add Event")
        dialog.configure(bg="#15151f")
        px, py = self.winfo_x(), self.winfo_y()
        dialog.geometry(f"340x380+{px + 60}+{py + 60}")
        dialog.grab_set()
        dialog.resizable(False, False)

        year, month, day = self.selected_date

        def field(label_text, row):
            tk.Label(dialog, text=label_text, bg="#15151f", fg="#ccc",
                     font=("Segoe UI", 10), anchor="w").grid(
                row=row, column=0, sticky="w", padx=14, pady=(10, 0))

        field("Title", 0)
        title_var = tk.StringVar()
        tk.Entry(dialog, textvariable=title_var, width=30).grid(
            row=1, column=0, padx=14, sticky="w")

        field("Category", 2)
        category_var = tk.StringVar(value="birthday")
        ttk.Combobox(dialog, textvariable=category_var, values=CATEGORIES,
                     state="readonly", width=27).grid(row=3, column=0, padx=14, sticky="w")

        field("Month / Day", 4)
        md_frame = tk.Frame(dialog, bg="#15151f")
        md_frame.grid(row=5, column=0, padx=14, sticky="w")
        month_var = tk.StringVar(value=str(month))
        day_var = tk.StringVar(value=str(day))
        tk.Entry(md_frame, textvariable=month_var, width=5).pack(side="left")
        tk.Label(md_frame, text=" / ", bg="#15151f", fg="#ccc").pack(side="left")
        tk.Entry(md_frame, textvariable=day_var, width=5).pack(side="left")

        recurring_var = tk.BooleanVar(value=True)
        tk.Checkbutton(dialog, text="Repeats every year (birthdays, etc.)",
                        variable=recurring_var, bg="#15151f", fg="#ccc",
                        selectcolor="#23233a", activebackground="#15151f",
                        command=lambda: year_entry.config(
                            state="disabled" if recurring_var.get() else "normal")
                        ).grid(row=6, column=0, padx=14, pady=(10, 0), sticky="w")

        field("Year (only if it does NOT repeat)", 7)
        year_var = tk.StringVar(value=str(year))
        year_entry = tk.Entry(dialog, textvariable=year_var, width=12, state="disabled")
        year_entry.grid(row=8, column=0, padx=14, sticky="w")

        field("Notes (optional)", 9)
        notes_var = tk.StringVar()
        tk.Entry(dialog, textvariable=notes_var, width=30).grid(
            row=10, column=0, padx=14, sticky="w")

        error_label = tk.Label(dialog, text="", bg="#15151f", fg="#ff8a80",
                                font=("Segoe UI", 9), wraplength=310, justify="left")
        error_label.grid(row=11, column=0, padx=14, pady=(8, 0), sticky="w")

        def on_save():
            title = title_var.get().strip()
            if not title:
                error_label.config(text="Please enter a title.")
                return
            try:
                m = int(month_var.get())
                d = int(day_var.get())
                if not 1 <= m <= 12:
                    raise ValueError("Month must be between 1 and 12.")
                if not 1 <= d <= cm.days_in_month(2024 if m == 2 else 2025, m):
                    # 2024 is a leap year, used here only to allow Feb 29
                    # as a valid *recurring* birthday input
                    raise ValueError(f"Day must be between 1 and {cm.days_in_month(2024, m)} for that month.")
            except ValueError as exc:
                error_label.config(text=str(exc) if str(exc) else "Month/day must be whole numbers.")
                return

            recurring = recurring_var.get()
            ev_year = None
            if not recurring:
                try:
                    ev_year = int(year_var.get())
                except ValueError:
                    error_label.config(text="Year must be a whole number.")
                    return

            self.store.add(title=title, month=m, day=d, year=ev_year,
                            recurring=recurring, category=category_var.get(),
                            notes=notes_var.get().strip())
            dialog.destroy()
            self._render_user_events()
            self._render_month()

        btn_frame = tk.Frame(dialog, bg="#15151f")
        btn_frame.grid(row=12, column=0, padx=14, pady=16, sticky="w")
        tk.Button(btn_frame, text="Save", command=on_save, bg="#2e7d32", fg="white",
                  relief="flat", width=10, cursor="hand2").pack(side="left", padx=(0, 8))
        tk.Button(btn_frame, text="Cancel", command=dialog.destroy, bg="#333",
                  fg="white", relief="flat", width=10, cursor="hand2").pack(side="left")


def _system_today() -> tuple[int, int, int]:
    """The one and only place this whole project touches the real-world
    clock - just to know what 'Today' means when the app opens. Uses
    `time.localtime` (stdlib) rather than `datetime` purely for
    consistency with the rest of the no-datetime design."""
    import time
    t = time.localtime()
    return t.tm_year, t.tm_mon, t.tm_mday


def run():
    app = CalendarApp()
    app.mainloop()
