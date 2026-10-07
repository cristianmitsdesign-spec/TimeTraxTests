"""Print the text of every Edit control in the Timetrax time entry window.

Run it, click a different grid row in Timetrax, run it again, and compare.
"""
from pywinauto import Desktop

desk = Desktop(backend="win32")
frame = desk.window(class_name_re=r"^Afx:.*", title_re=r"^Timetrax - MAI-CMW.*")
print("Frame title:", frame.window_text())

child = frame.child_window(class_name="tsmdiwind")
print("Child title:", child.window_text())

# Group Edit controls by their parent tswind so the layout is visible
groups = {}
for e in child.descendants(class_name="Edit"):
    p = e.parent()
    key = (p.class_name(), p.rectangle().left, p.rectangle().top)
    groups.setdefault(key, []).append(e)

for key, edits in sorted(groups.items(), key=lambda k: (k[0][2], k[0][1])):
    print(f"\n== {key[0]} at ({key[1]},{key[2]})  {len(edits)} edits ==")
    edits.sort(key=lambda e: (e.rectangle().top, e.rectangle().left))
    row_top = None
    line = []
    for e in edits:
        r = e.rectangle()
        if row_top is not None and r.top != row_top:
            if any(t for _, t in line):
                print(f"y={row_top}: " + " | ".join(f"{x}:{t!r}" for x, t in line))
            line = []
        row_top = r.top
        line.append((r.left, e.window_text()))
    if any(t for _, t in line):
        print(f"y={row_top}: " + " | ".join(f"{x}:{t!r}" for x, t in line))

print("\nOnly rows with at least one non-empty edit are shown.")