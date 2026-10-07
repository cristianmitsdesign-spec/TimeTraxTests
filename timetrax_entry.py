"""Timetrax Entry: a window that enters a week of timesheets into Timetrax.

1. Choose the folder (or zip) the timesheet app exported.
2. For each employee: log in to Timetrax with their employee number, open the
   week, then press the big button. The script types the hours and checks them.
3. Each employee that checks out is saved to results_WE_<date>.json next to the
   timesheets. Upload that file on the Admin screen of the timesheet app.

Start it by double-clicking "Timetrax Entry.bat".
"""
import contextlib
import os
import queue
import re
import sys
import threading
import tkinter as tk
import traceback
import warnings
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

# pywinauto defaults COM to multithreaded, which hangs the Windows folder picker.
# Single-threaded is what file dialogs need, and the win32 backend works with it.
# Must be set before pywinauto is imported.
sys.coinit_flags = 2
warnings.filterwarnings("ignore", message="Apply externally defined coinit_flags")

from pywinauto import Desktop  # noqa: E402

import tt_cell  # noqa: E402
import tt_batches  # noqa: E402
from tt_batches import Employee  # noqa: E402

TITLE_RE = re.compile(r"Time for (?P<name>.+?), week ending (?P<week>[A-Za-z]+ \d{1,2}, \d{4})")

STATUS_WAITING = "Waiting"
STATUS_DONE = "Done"
STATUS_DONE_BEFORE = "Done earlier"
STATUS_PROBLEM = "Needs attention"
STATUS_SKIPPED = "Skipped"
STATUS_CANT = "Can't enter"


def week_text(d):
    return f"{d:%B} {d.day}, {d.year}"


# ---------------------------------------------------------------- Timetrax side

class QueueWriter:
    """File-like object: everything tt_cell prints goes to the window and the log."""

    def __init__(self, q, buffer):
        self.q, self.buffer = q, buffer

    def write(self, text):
        if text:
            self.buffer.append(text)
            self.q.put(("log", text))

    def flush(self):
        pass


def timetrax_title():
    """Return the open time entry title, or None if Timetrax is not ready."""
    try:
        frame = Desktop(backend="win32").window(class_name_re=r"^Afx:.*", title_re=r"^Timetrax - MAI-CMW.*")
        return frame.child_window(class_name="tsmdiwind").window_text()
    except Exception:
        return None


def snapshot(frame, child):
    pages = {}
    for page in tt_cell.PAGES:
        tt_cell.switch_page(frame, child, page)
        grids = tt_cell.build_grids(child)
        pages[page] = [
            {"row": row, "project": c[0], "phase": c[1], "activity": c[2], "hours": h[:7]}
            for row, c, h in tt_cell.read_week(grids) if tt_cell.has_hours(h)
        ]
    return pages


def compare(emp, after):
    """List every difference between the timesheet and what Timetrax now shows."""
    problems = []
    for page in tt_cell.PAGES:
        actual = {(r["project"], r["phase"], r["activity"]): r["hours"] for r in after[page]}
        expected = {(l.project, l.phase, l.activity): l.hours for l in emp.lines if l.page == page}
        for key, target in expected.items():
            got = actual.get(key)
            if got is None:
                problems.append(f"missing line {' '.join(key)}")
                continue
            for i, (g, t) in enumerate(zip(got, target)):
                if not tt_cell.same_number(g, t):
                    problems.append(f"{' '.join(key)} {tt_cell.HDR[i]}: Timetrax shows {g or '0'}, "
                                    f"timesheet says {t or '0'}")
        for key, got in actual.items():
            if key not in expected:
                problems.append(f"extra line in Timetrax not on the timesheet: {' '.join(key)} {got}")
    return problems


def enter_employee(emp, practice, out):
    """Type one employee's week. Returns (ok, before, after)."""
    frame, child = tt_cell.open_window()
    before = snapshot(frame, child)
    for n, line in enumerate(emp.lines, 1):
        days = " ".join(f"{d}={h}" for d, h in zip(tt_cell.DAYS, line.hours) if h)
        print(f"\n--- line {n} of {len(emp.lines)}: {line.project} {line.phase} {line.activity}  {days}")
        out.put(("progress", (n, len(emp.lines))))
        tt_cell.switch_page(frame, child, line.page)
        if not tt_cell.write_line(frame, child, line.project, line.phase, line.activity,
                                  line.hours, live=not practice, save=not practice):
            print(f"\nLine {n} did not go in. Nothing after it was typed.")
            return False, before, None
    if practice:
        print("\nPractice run finished. Nothing was typed into Timetrax.")
        return True, before, None
    after = snapshot(frame, child)
    tt_cell.switch_page(frame, child, "direct")
    problems = compare(emp, after)
    print("\nCheck against the timesheet:")
    for p in problems:
        print("  PROBLEM", p)
    print("  all lines match" if not problems else f"  {len(problems)} problem(s)")
    return not problems, before, after


# ---------------------------------------------------------------- window

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Timetrax Entry")
        self.geometry("880x720")
        self.minsize(760, 600)
        self.employees: list[Employee] = []
        self.status: dict[str, str] = {}
        self.folder: Path | None = None
        self.results_file: Path | None = None
        self.q = queue.Queue()
        self.busy = False
        self.practice = tk.BooleanVar(value=False)
        self._build()
        self.after(100, self._poll)

    # ---- layout
    def _build(self):
        style = ttk.Style(self)
        style.configure("Big.TButton", font=("Segoe UI", 12, "bold"), padding=10)
        style.configure("Head.TLabel", font=("Segoe UI", 11, "bold"))
        style.configure("Next.TLabel", font=("Segoe UI", 12))
        style.configure("Treeview", rowheight=26, font=("Segoe UI", 10))

        top = ttk.Frame(self, padding=12)
        top.pack(fill="x")
        ttk.Label(top, text="Step 1. Choose this week's timesheets", style="Head.TLabel").pack(anchor="w")
        row = ttk.Frame(top)
        row.pack(fill="x", pady=4)
        ttk.Button(row, text="Choose folder...", command=self.choose_folder).pack(side="left")
        ttk.Button(row, text="Choose zip file...", command=self.choose_zip).pack(side="left", padx=6)
        self.source_label = ttk.Label(row, text="Nothing chosen yet", foreground="#555")
        self.source_label.pack(side="left", padx=8)
        self.week_label = ttk.Label(top, text="", style="Head.TLabel")
        self.week_label.pack(anchor="w", pady=(4, 0))

        mid = ttk.Frame(self, padding=(12, 0))
        mid.pack(fill="both", expand=True)
        cols = ("name", "number", "hours", "status")
        self.tree = ttk.Treeview(mid, columns=cols, show="headings", height=9, selectmode="browse")
        for col, text, width, anchor in (("name", "Employee", 260, "w"), ("number", "Employee no.", 110, "center"),
                                         ("hours", "Hours", 80, "e"), ("status", "Status", 220, "w")):
            self.tree.heading(col, text=text)
            self.tree.column(col, width=width, anchor=anchor)
        self.tree.tag_configure(STATUS_DONE, background="#d9f2d9")
        self.tree.tag_configure(STATUS_DONE_BEFORE, background="#d9f2d9")
        self.tree.tag_configure(STATUS_PROBLEM, background="#f9d6d5")
        self.tree.tag_configure(STATUS_CANT, background="#f9d6d5")
        self.tree.tag_configure(STATUS_SKIPPED, background="#eeeeee")
        self.tree.pack(fill="x")
        self.tree.bind("<<TreeviewSelect>>", lambda e: self.show_next())

        step2 = ttk.Frame(mid, padding=(0, 10))
        step2.pack(fill="x")
        ttk.Label(step2, text="Step 2. Enter each employee", style="Head.TLabel").pack(anchor="w")
        self.next_label = ttk.Label(step2, text="Choose the timesheets first.", style="Next.TLabel",
                                    wraplength=820, justify="left")
        self.next_label.pack(anchor="w", pady=6)
        buttons = ttk.Frame(step2)
        buttons.pack(fill="x")
        self.go_button = ttk.Button(buttons, text="Enter time", style="Big.TButton",
                                    command=self.start, state="disabled")
        self.go_button.pack(side="left")
        self.skip_button = ttk.Button(buttons, text="Skip this employee", command=self.skip, state="disabled")
        self.skip_button.pack(side="left", padx=8)
        ttk.Checkbutton(buttons, text="Practice run (check only, type nothing)",
                        variable=self.practice, command=self.show_next).pack(side="left", padx=8)
        self.progress = ttk.Progressbar(step2, mode="determinate")
        self.progress.pack(fill="x", pady=(8, 0))

        ttk.Label(mid, text="Details", style="Head.TLabel").pack(anchor="w")
        logframe = ttk.Frame(mid)
        logframe.pack(fill="both", expand=True)
        self.log = tk.Text(logframe, height=10, font=("Consolas", 9), wrap="none", state="disabled")
        scroll = ttk.Scrollbar(logframe, command=self.log.yview)
        self.log.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.log.pack(side="left", fill="both", expand=True)

        bottom = ttk.Frame(self, padding=12)
        bottom.pack(fill="x", side="bottom", before=mid)
        ttk.Label(bottom, text="Step 3.", style="Head.TLabel").pack(side="left")
        self.results_label = ttk.Label(bottom, text="The results file appears here after the first employee.")
        self.results_label.pack(side="left", padx=6)
        self.open_button = ttk.Button(bottom, text="Show results file", command=self.open_results, state="disabled")
        self.open_button.pack(side="right")

    # ---- loading
    def choose_folder(self):
        path = filedialog.askdirectory(title="Choose the folder with this week's timesheet PDFs")
        if path:
            self.load(Path(path), Path(path))

    def choose_zip(self):
        path = filedialog.askopenfilename(title="Choose the timesheets zip file",
                                          filetypes=[("Zip files", "*.zip")])
        if path:
            self.load(Path(path), Path(path).parent)

    def load(self, source, folder):
        if self.busy:
            return
        try:
            employees, notes = tt_batches.load_week(source)
        except Exception as exc:
            messagebox.showerror("Timetrax Entry", f"Could not read the timesheets:\n\n{exc}")
            return
        if not employees:
            messagebox.showerror("Timetrax Entry",
                                 "No timesheets with data were found there.\n\n"
                                 "Choose the folder or zip downloaded from the timesheet app, "
                                 "with the PDFs unchanged.\n\n" + "\n".join(notes))
            return
        weeks = {e.week_ending for e in employees}
        if len(weeks) > 1:
            messagebox.showerror("Timetrax Entry", "These files are from more than one week. "
                                 "Put one week's timesheets in a folder and choose that.")
            return
        self.employees = employees
        self.folder = folder
        week = employees[0].week_ending
        self.results_file = tt_batches.results_path(folder, week)
        done = tt_batches.done_job_ids(self.results_file)
        self.status = {}
        for e in employees:
            if e.problem:
                self.status[e.import_job_id] = STATUS_CANT
            elif e.import_job_id in done:
                self.status[e.import_job_id] = STATUS_DONE_BEFORE
            else:
                self.status[e.import_job_id] = STATUS_WAITING
        total = sum(e.total for e in employees)
        self.source_label.configure(text=str(source))
        self.week_label.configure(text=f"Week ending Saturday, {week_text(week)}:  "
                                       f"{len(employees)} employees, {total:.2f} hours")
        self.clear_log()
        for n in notes:
            self.write_log(f"Skipped {n}\n")
        for e in employees:
            if e.problem:
                self.write_log(f"{e.name} #{e.number} cannot be entered: {e.problem}\n")
        self.refresh_table()
        self.refresh_results_label()
        self.select_next_waiting()

    # ---- table and instructions
    def refresh_table(self):
        selected = self.selected()
        self.tree.delete(*self.tree.get_children())
        for e in self.employees:
            st = self.status[e.import_job_id]
            self.tree.insert("", "end", iid=e.import_job_id, tags=(st,),
                             values=(e.name, e.number, f"{e.total:.2f}", st))
        if selected:
            self.tree.selection_set(selected.import_job_id)

    def selected(self):
        sel = self.tree.selection()
        return next((e for e in self.employees if sel and e.import_job_id == sel[0]), None)

    def select_next_waiting(self):
        for e in self.employees:
            if self.status[e.import_job_id] in (STATUS_WAITING, STATUS_PROBLEM):
                self.tree.selection_set(e.import_job_id)
                self.tree.see(e.import_job_id)
                self.show_next()
                return
        self.tree.selection_set(())
        self.show_next()

    def show_next(self):
        if self.busy:
            return
        emp = self.selected()
        can_go = False
        if not self.employees:
            text = "Choose the timesheets first."
        elif emp is None:
            left = [e for e in self.employees if self.status[e.import_job_id] not in (STATUS_DONE, STATUS_DONE_BEFORE)]
            text = ("All done. Upload the results file on the Admin screen of the timesheet app."
                    if not left else "Click an employee in the list to enter their time.")
        else:
            st = self.status[emp.import_job_id]
            if st == STATUS_CANT:
                text = f"{emp.name} cannot be entered by the script: {emp.problem}."
            else:
                text = (f"Next: {emp.name}  (employee no. {emp.number})\n\n"
                        f"1. In Timetrax, log in with employee number {emp.number}.\n"
                        f"2. Open the time sheet for the week ending {week_text(emp.week_ending)}.\n"
                        f"3. Click \"Enter time for {emp.name}\" below, then leave the mouse and "
                        f"keyboard alone until this window comes back.")
                if st in (STATUS_DONE, STATUS_DONE_BEFORE):
                    text = (f"{emp.name} is already done. Running again is safe: lines already "
                            f"in Timetrax are checked, not typed twice.\n\n") + text
                can_go = True
        self.next_label.configure(text=text)
        label = f"Enter time for {emp.name}" if emp else "Enter time"
        if self.practice.get():
            label = "Practice: " + label
        self.go_button.configure(text=label, state="normal" if can_go else "disabled")
        self.skip_button.configure(state="normal" if can_go else "disabled")

    def skip(self):
        emp = self.selected()
        if emp:
            self.status[emp.import_job_id] = STATUS_SKIPPED
            self.write_log(f"Skipped {emp.name} #{emp.number}\n")
            self.refresh_table()
            self.select_next_waiting()

    # ---- running
    def start(self):
        emp = self.selected()
        if emp is None or self.busy:
            return
        title = timetrax_title()
        if title is None:
            messagebox.showwarning("Timetrax Entry",
                                   "Timetrax is not open on a time sheet.\n\n"
                                   f"Log in with employee number {emp.number}, open the week ending "
                                   f"{week_text(emp.week_ending)}, then try again.")
            return
        m = TITLE_RE.search(title)
        if not m:
            messagebox.showwarning("Timetrax Entry", f"Timetrax shows \"{title}\".\n\n"
                                   f"Open the time sheet for the week ending {week_text(emp.week_ending)}.")
            return
        if m["week"] != week_text(emp.week_ending):
            messagebox.showwarning("Timetrax Entry",
                                   f"Timetrax has the week ending {m['week']} open, but this timesheet "
                                   f"is for the week ending {week_text(emp.week_ending)}.\n\n"
                                   "Open the right week in Timetrax, then try again.")
            return
        shown = set(m["name"].upper().replace(",", " ").split())
        wanted = set(emp.name.upper().replace(",", " ").split())
        if not wanted <= shown:
            if not messagebox.askyesno("Is the right person logged in?",
                                       f"Timetrax is open for {m['name']}.\n"
                                       f"This timesheet is for {emp.name} (employee no. {emp.number}).\n\n"
                                       "Is that the same person?\n\n"
                                       "Choose No, then log in with the right employee number."):
                return
        self.busy = True
        practice = self.practice.get()
        self.go_button.configure(state="disabled")
        self.skip_button.configure(state="disabled")
        self.progress.configure(value=0, maximum=max(len(emp.lines), 1))
        self.next_label.configure(text=f"Working on {emp.name}... leave the mouse and keyboard alone.")
        self.write_log(f"\n===== {emp.name} #{emp.number}, week ending {emp.week_ending}"
                       f"{' (practice run)' if practice else ''} =====\n")
        # The script clicks on Timetrax by screen position; get this window out of the way.
        self.iconify()
        threading.Thread(target=self._worker, args=(emp, practice), daemon=True).start()

    def _worker(self, emp, practice):
        buffer = []
        ok, before, after = False, None, None
        with contextlib.redirect_stdout(QueueWriter(self.q, buffer)):
            try:
                ok, before, after = enter_employee(emp, practice, self.q)
            except Exception as exc:
                print(f"\nSTOPPED: {type(exc).__name__}: {exc}")
        self.q.put(("finished", (emp, practice, ok, "".join(buffer), before, after)))

    def _poll(self):
        try:
            while True:
                kind, data = self.q.get_nowait()
                if kind == "log":
                    self.write_log(data)
                elif kind == "progress":
                    self.progress.configure(value=data[0])
                elif kind == "finished":
                    self._finished(*data)
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def _finished(self, emp, practice, ok, log, before, after):
        self.busy = False
        self.deiconify()
        self.lift()
        self.attributes("-topmost", True)
        self.after(500, lambda: self.attributes("-topmost", False))
        self.progress.configure(value=self.progress["maximum"] if ok else self.progress["value"])
        if practice:
            msg = ("Practice run finished. Nothing was typed. See Details for what would be entered."
                   if ok else "Practice run found a problem. See Details below.")
            messagebox.showinfo("Timetrax Entry", msg)
            self.show_next()
            return
        tt_batches.record_result(self.results_file, emp, ok, log, before, after)
        self.refresh_results_label()
        if ok:
            self.status[emp.import_job_id] = STATUS_DONE
            self.refresh_table()
            self.select_next_waiting()
            nxt = self.selected()
            messagebox.showinfo("Timetrax Entry", f"{emp.name} is done and checked.\n\n"
                                + (f"Next: log out, then log in to Timetrax as {nxt.name} "
                                   f"(employee no. {nxt.number})." if nxt else
                                   "That was the last one. Upload the results file on the Admin screen."))
        else:
            self.status[emp.import_job_id] = STATUS_PROBLEM
            self.refresh_table()
            self.tree.selection_set(emp.import_job_id)
            messagebox.showwarning("Timetrax Entry",
                                   f"{emp.name}'s time did not go in completely.\n\n"
                                   "Check the Details box for the reason (often a project, phase or "
                                   "activity code Timetrax does not know, or a Timetrax message). "
                                   "Fix it in Timetrax, then press the button again; lines already "
                                   "entered are not typed twice.\n\n"
                                   "This employee is not marked done in the results file.")
        self.show_next()

    # ---- log and results
    def write_log(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text)
        self.log.see("end")
        self.log.configure(state="disabled")

    def clear_log(self):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def refresh_results_label(self):
        if self.results_file and self.results_file.exists():
            done = len(tt_batches.done_job_ids(self.results_file))
            self.results_label.configure(
                text=f"Upload {self.results_file.name} on the Admin screen ({done} of "
                     f"{len(self.employees)} employees done).")
            self.open_button.configure(state="normal")
        else:
            self.results_label.configure(text="The results file appears here after the first employee.")
            self.open_button.configure(state="disabled")

    def open_results(self):
        if self.results_file and self.results_file.exists():
            os.system(f'explorer /select,"{self.results_file}"')


ERROR_LOG = Path(__file__).with_name("timetrax_entry_error.log")


def report_error(exc_type, exc, tb):
    """pythonw has no console, so show errors and keep them in a file."""
    text = "".join(traceback.format_exception(exc_type, exc, tb))
    with contextlib.suppress(OSError):
        with ERROR_LOG.open("a", encoding="utf-8") as f:
            f.write(text + "\n")
    messagebox.showerror("Timetrax Entry", f"Something went wrong:\n\n{exc}\n\n"
                         f"Details were saved to {ERROR_LOG.name}.")


def main():
    tt_cell.IGNORE_DIALOGS = False
    app = App()
    app.report_callback_exception = report_error
    app.mainloop()


if __name__ == "__main__":
    main()
