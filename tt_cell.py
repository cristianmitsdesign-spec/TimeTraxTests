"""Timetrax time entry grid: read, write one cell, write one line, run a CSV batch, verify.

Usage:
  python tt_cell.py read
  python tt_cell.py page [overhead|direct]
  python tt_cell.py write ROW COL VALUE [--live] [--save]
  python tt_cell.py line ROW PROJECT PHASE ACTIVITY mon=0.75 thu=1.25 [--live] [--save] [--page P]
  python tt_cell.py batch FILE.csv [--live] [--save] [--only N]
  python tt_cell.py verify FILE.csv
  python tt_cell.py list ROW COL

Options:
  --week "September 19, 2026"   stop unless the open week's title contains this
  --ignore-dialogs              log and dismiss dialogs, keep going (testing only)
Everything is a dry run unless --live is given. --save presses Alt+S after each line.

CSV columns: page,project,phase,activity,sun,mon,tue,wed,thu,fri,sat  (lines starting # ignored)
"""
import csv
import sys
import time
from pywinauto import Desktop, mouse

# The page toggle button reads "&Overhead" or "&Direct" and names the page it switches TO.
CAPTION_IS_CURRENT_PAGE = False
PAGES = ("overhead", "direct")

KEY_PAUSE = 0.05          # gap between keystrokes; Timetrax needs real keystrokes
IGNORE_DIALOGS = False

DAYS = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"]
HDR = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Total"]


class TimetraxDialog(Exception):
    pass


# ---------------------------------------------------------------- window and grids

def open_window(week=None):
    desk = Desktop(backend="win32")
    frame = desk.window(class_name_re=r"^Afx:.*", title_re=r"^Timetrax - MAI-CMW.*")
    frame.set_focus()
    child = frame.child_window(class_name="tsmdiwind")
    title = child.window_text()
    print("Window:", title)
    if week and week not in title:
        sys.exit(f"STOPPED: expected week ending {week!r} but the open window is {title!r}")
    return frame, child


def page_button(child):
    for b in child.descendants(class_name="Button"):
        t = b.window_text().replace("&", "").strip().lower()
        if t in PAGES:
            return b, t
    raise RuntimeError("page toggle button (Overhead/Direct) not found")


def current_page(child):
    _, caption = page_button(child)
    if CAPTION_IS_CURRENT_PAGE:
        return caption
    return "direct" if caption == "overhead" else "overhead"


def switch_page(frame, child, wanted):
    if current_page(child) == wanted:
        return
    btn, _ = page_button(child)
    btn.click_input()
    time.sleep(0.8)
    frame.set_focus()
    if current_page(child) != wanted:
        raise RuntimeError(f"tried to switch to {wanted} page but it did not change")
    print(f"Switched to {wanted} page")


def build_grids(child):
    by_parent = {}
    for e in child.descendants(class_name="Edit"):
        by_parent.setdefault(e.parent().handle, []).append(e)
    # Codes grid is 3 columns, hours grid 8 (Sun..Sat + Total). Row count differs
    # by page: 32 on Direct, 18 on Overhead.
    found = {3: [], 8: []}
    for edits in by_parent.values():
        xs = sorted({e.rectangle().left for e in edits})
        ys = sorted({e.rectangle().top for e in edits})
        if len(xs) not in found or len(edits) != len(xs) * len(ys) or len(ys) < 2:
            continue
        cells = [[None] * len(xs) for _ in ys]
        for e in edits:
            r = e.rectangle()
            cells[ys.index(r.top)][xs.index(r.left)] = e
        found[len(xs)].append(cells)
    pairs = [(c, h) for c in found[3] for h in found[8] if len(c) == len(h)]
    if not pairs:
        raise RuntimeError("could not find the time entry grid on this page")
    codes, hours = max(pairs, key=lambda p: len(p[0]))
    return {"codes": codes, "hours": hours}


def read_row(grids, i):
    codes = [c.window_text().strip() for c in grids["codes"][i]]
    hours = [c.window_text().strip() for c in grids["hours"][i]]
    return codes, hours


def has_hours(hours):
    return any(h for h in hours[:7])


def read_week(grids):
    lines = []
    for i in range(len(grids["codes"])):
        codes, hours = read_row(grids, i)
        if any(codes) or any(hours):
            lines.append((i + 1, codes, hours))
    return lines


def print_week(lines):
    print(f"{'row':>3}  {'project':<12}{'phase':<6}{'act':<6}" + "".join(f"{d:>7}" for d in HDR))
    for row, codes, hours in lines:
        print(f"{row:>3}  {codes[0]:<12}{codes[1]:<6}{codes[2]:<6}" + "".join(f"{h:>7}" for h in hours))


def same_number(a, b):
    try:
        return abs(float(a or 0) - float(b or 0)) < 0.005
    except ValueError:
        return (a or "") == (b or "")


# ---------------------------------------------------------------- dialogs

def find_popup(frame, wait=0.6):
    time.sleep(wait)
    pid = frame.process_id()
    for w in Desktop(backend="win32").windows(process=pid):
        if w.class_name() == "#32770" and w.is_visible():
            return w
    return None


def describe_popup(w):
    texts = [w.window_text()]
    for c in w.descendants():
        t = c.window_text().strip()
        if t:
            texts.append(f"{c.class_name()}: {t}")
    return " | ".join(texts)


def dismiss_or_raise(frame, context, wait=0.6):
    popup = find_popup(frame, wait=wait)
    if popup is None:
        return
    info = describe_popup(popup)
    popup.type_keys("{ESC}")
    if IGNORE_DIALOGS:
        print(f"    DIALOG (ignored) {context}: {info}")
        time.sleep(0.3)
        frame.set_focus()
        return
    raise TimetraxDialog(f"{context}: {info}")


def click_button(child, title):
    child.child_window(title=title, class_name="Button").click_input()


# ---------------------------------------------------------------- writing

def activate_cell(cell, frame):
    """Make the cell's row the current line so its Edit control becomes visible."""
    if cell.is_visible():
        return
    r = cell.rectangle()
    mouse.click(coords=(r.left + r.width() // 2, r.top + r.height() // 2))
    time.sleep(0.5)
    if not cell.is_visible():
        raise TimetraxDialog(f"cell at row top {r.top} is still hidden after clicking it")
    dismiss_or_raise(frame, "when activating a row", wait=0.2)


def type_into(cell, value, frame):
    activate_cell(cell, frame)
    cell.click_input()
    time.sleep(0.2)
    try:
        cell.set_focus()
    except Exception:
        pass
    before = cell.window_text()
    for key in ("{DELETE}", "{BACKSPACE}"):
        if not cell.window_text().strip():
            break
        cell.select()
        time.sleep(0.1)
        cell.type_keys(key)
        time.sleep(0.25)
    if cell.window_text().strip():
        raise TimetraxDialog(f"could not clear {before!r} from the cell")
    cell.type_keys(value, with_spaces=True, pause=KEY_PAUSE)
    time.sleep(0.3)
    got = cell.window_text()
    print(f"    {before!r} -> {got!r}")
    if got.strip() != value:
        raise TimetraxDialog(f"could not get {value!r} into the cell; it shows {got!r}")
    cell.type_keys("{TAB}")
    dismiss_or_raise(frame, f"after entering {value!r}")


def prepare_row(frame, child, grids, row, target_codes):
    """Return (grids, row, fill_codes) for a row we can write into. Never deletes a line."""
    for _ in range(6):
        cell = grids["codes"][row - 1][0]
        activate_cell(cell, frame)
        time.sleep(0.2)
        grids = build_grids(child)
        codes, hours = read_row(grids, row - 1)
        if has_hours(hours):
            print(f"    row {row} has hours; moving on")
            row += 1
            continue
        if codes == target_codes:
            return grids, row, False
        if not any(codes):
            return grids, row, True
        cell = grids["codes"][row - 1][0]
        cell.click_input()
        cell.select()
        time.sleep(0.1)
        cell.type_keys("{DELETE}")
        time.sleep(0.25)
        if not cell.window_text().strip():
            print(f"    row {row}: cleared carried-forward {codes[0]!r}")
            return build_grids(child), row, True
        print(f"    row {row} is a committed line {codes} with no hours; leaving it, trying next row")
        click_button(child, "Cancel line")
        time.sleep(0.4)
        grids = build_grids(child)
        row += 1
    raise TimetraxDialog("could not find a writable row")


def find_row_by_codes(grids, target_codes):
    for i in range(len(grids["codes"])):
        codes, _ = read_row(grids, i)
        if codes == target_codes:
            return i + 1
    return None


def first_free_row(grids):
    for i in range(len(grids["codes"])):
        _, hours = read_row(grids, i)
        if not has_hours(hours):
            return i + 1
    raise RuntimeError("no free row left")


def fill_hours(frame, grids, row, target):
    """Activate the row through its Sunday hours cell and type the non-empty hours."""
    activate_cell(grids["hours"][row - 1][0], frame)
    for i, value in enumerate(target):
        if value:
            type_into(grids["hours"][row - 1][i], value, frame)


def write_line(frame, child, project, phase, activity, target, live, save):
    """Write one line onto the current page. Returns True on PASS, False otherwise."""
    page = current_page(child)
    grids = build_grids(child)
    codes = [project, phase, activity]
    row = find_row_by_codes(grids, codes)
    new_line = row is None

    if row is not None:
        _, hours = read_row(grids, row - 1)
        if has_hours(hours):
            if all(same_number(g, t) for g, t in zip(hours[:7], target)):
                print(f"    already present on row {row} with matching hours; skipping")
                return True
            print(f"    already present on row {row} with DIFFERENT hours {hours[:7]}; "
                  f"not updating (add-only mode)")
            return False
        print(f"Plan: row {row} (existing {codes}) hours -> {target}" + (", then Alt+S" if save else ""))
    elif page == "overhead":
        print(f"    FAIL: no overhead line {codes} on this timesheet; overhead lines cannot be created")
        return False
    else:
        row = first_free_row(grids)
        print(f"Plan: row {row}: {codes} hours {target}" + (", then Alt+S" if save else ""))

    if not live:
        print("    dry run")
        return True
    try:
        if new_line:
            grids, row, fill_codes = prepare_row(frame, child, grids, row, codes)
            print(f"    writing to row {row}")
            if fill_codes:
                for cell, value in zip(grids["codes"][row - 1], codes):
                    type_into(cell, value, frame)
            for i, value in enumerate(target):
                if value:
                    type_into(grids["hours"][row - 1][i], value, frame)
        else:
            fill_hours(frame, grids, row, target)
    except TimetraxDialog as e:
        print(f"    STOPPED, {e}")
        return False
    if save:
        frame.type_keys("%s")
        dismiss_or_raise(frame, "after Save line")
    frame.set_focus()
    time.sleep(0.3)
    grids = build_grids(child)
    got_codes, got = read_row(grids, row - 1)
    ok = got_codes == codes and all(same_number(g, t) for g, t in zip(got[:7], target))
    print(f"    read back row {row}: {got_codes} {got}")
    print("    PASS" if ok else "    FAIL: read-back differs from target")
    return ok


# ---------------------------------------------------------------- csv

def load_csv(path):
    lines = []
    with open(path, newline="") as f:
        for raw in csv.reader(f):
            if not raw or raw[0].strip().startswith("#") or raw[0].strip() == "page":
                continue
            page, project, phase, activity = [x.strip() for x in raw[:4]]
            hours = [x.strip() for x in raw[4:11]] + [""] * (11 - len(raw))
            if page not in PAGES:
                sys.exit(f"bad page {page!r} in {path}: {raw}")
            lines.append((page, project, phase, activity, hours[:7]))
    return lines


def run_batch(frame, child, path, live, save, only):
    lines = load_csv(path)
    results = []
    for n, (page, project, phase, activity, target) in enumerate(lines, 1):
        if only and only != n:
            continue
        print(f"\n--- line {n} [{page}] {project} {phase} {activity} "
              + " ".join(f"{d}={h}" for d, h in zip(DAYS, target) if h) + " ---")
        switch_page(frame, child, page)
        ok = write_line(frame, child, project, phase, activity, target, live, save)
        results.append((n, project, phase, activity, ok))
        if not ok and not IGNORE_DIALOGS:
            print(f"\nstopped at line {n}")
            break
    print("\nSummary:")
    for n, project, phase, activity, ok in results:
        print(f"  line {n:>2} {project} {phase} {activity}: {'PASS' if ok else 'FAIL'}")


def verify(frame, child, path):
    expected = load_csv(path)
    problems = 0
    for page in PAGES:
        switch_page(frame, child, page)
        grids = build_grids(child)
        actual = {tuple(codes): hours for _, codes, hours in read_week(grids) if has_hours(hours)}
        exp_page = [(p, pr, ph, ac, h) for p, pr, ph, ac, h in expected if p == page]
        print(f"\n== {page} page: {len(actual)} lines with hours in Timetrax, {len(exp_page)} expected ==")
        seen = set()
        for _, pr, ph, ac, target in exp_page:
            key = (pr, ph, ac)
            seen.add(key)
            if key not in actual:
                print(f"  MISSING  {pr} {ph} {ac}")
                problems += 1
                continue
            got = actual[key]
            for i, (g, t) in enumerate(zip(got[:7], target)):
                if not same_number(g, t):
                    print(f"  MISMATCH {pr} {ph} {ac} {HDR[i]}: Timetrax {g!r}, sheet {t!r}")
                    problems += 1
        for key, got in actual.items():
            if key not in seen:
                print(f"  EXTRA    {' '.join(key)} {got[:7]}")
                problems += 1
        # day totals
        for i in range(7):
            tt = sum(float(h[i] or 0) for h in actual.values())
            ex = sum(float(t[i] or 0) for _, _, _, _, t in exp_page)
            flag = "" if abs(tt - ex) < 0.005 else "   <-- differs"
            print(f"  {HDR[i]}: Timetrax {tt:6.2f}  sheet {ex:6.2f}{flag}")
    print(f"\nVERIFY {'PASS' if problems == 0 else 'FAIL'}: {problems} problem(s)")


# ---------------------------------------------------------------- main

def opt_value(name):
    if name in sys.argv:
        return sys.argv[sys.argv.index(name) + 1]
    return None


def main():
    global IGNORE_DIALOGS
    IGNORE_DIALOGS = "--ignore-dialogs" in sys.argv
    live = "--live" in sys.argv
    save = "--save" in sys.argv
    week = opt_value("--week")
    page_opt = opt_value("--page")
    only = int(opt_value("--only") or 0)

    argv = list(sys.argv[1:])
    for name in ("--week", "--page", "--only"):
        if name in argv:
            i = argv.index(name); del argv[i:i + 2]
    args = [a for a in argv if not a.startswith("--")]
    cmd = args[0] if args else "read"

    if IGNORE_DIALOGS:
        print("NOTE: --ignore-dialogs is on; dialogs are logged and dismissed, run continues")

    frame, child = open_window(week)
    _, caption = page_button(child)
    print(f"Page: {current_page(child)}  (toggle button reads '{caption}')")

    if cmd == "read":
        print_week(read_week(build_grids(child)))

    elif cmd == "page":
        if len(args) > 1:
            switch_page(frame, child, args[1])
        print("Now on:", current_page(child))

    elif cmd == "write":
        grids = build_grids(child)
        row, col, value = int(args[1]), int(args[2]), args[3]
        cell = grids["hours"][row - 1][col - 1]
        print(f"Plan: row {row} {HDR[col-1]}: {cell.window_text()!r} -> {value!r}")
        if not live:
            print("dry run"); return
        type_into(cell, value, frame)
        if save:
            frame.type_keys("%s")
        frame.set_focus()
        print_week(read_week(build_grids(child)))

    elif cmd == "line":
        project, phase, activity = args[2], args[3], args[4]
        target = [""] * 7
        for kv in args[5:]:
            k, v = kv.split("=", 1)
            target[DAYS.index(k)] = v
        if page_opt:
            switch_page(frame, child, page_opt)
        ok = write_line(frame, child, project, phase, activity, target, live, save)
        sys.exit(0 if ok else 2)

    elif cmd == "batch":
        run_batch(frame, child, args[1], live, save, only)

    elif cmd == "verify":
        verify(frame, child, args[1])

    elif cmd == "list":
        row, col = int(args[1]), int(args[2])
        grids = build_grids(child)
        cell = grids["codes"][row - 1][col - 1]
        activate_cell(cell, frame)
        cell.click_input()
        frame.type_keys("%l")
        popup = None
        for _ in range(10):
            popup = find_popup(frame, wait=0.5)
            if popup:
                break
        if popup is None:
            pid = frame.process_id()
            others = [w for w in Desktop(backend="win32").windows(process=pid)
                      if w.handle != frame.handle and w.is_visible()]
            popup = others[0] if others else None
        if popup is None:
            print("No dialog appeared after Alt+L."); return
        out = f"tt_list_{col}.txt"
        Desktop(backend="win32").window(handle=popup.handle).print_control_identifiers(depth=6, filename=out)
        print("Dialog:", popup.window_text(), popup.class_name(), "dumped to", out)
        popup.type_keys("{ESC}")

    else:
        sys.exit("unknown command; see docstring")


if __name__ == "__main__":
    main()