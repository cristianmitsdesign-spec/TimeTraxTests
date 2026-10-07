from pywinauto import Desktop

desk = Desktop(backend="win32")
matches = desk.windows(title_re=".*(Timetrax|TimeTrax|MAI-CMW).*")
for i, w in enumerate(matches):
    print(i, repr(w.window_text()), w.class_name(),
          "visible" if w.is_visible() else "hidden", w.rectangle())
    spec = desk.window(handle=w.handle)
    spec.print_control_identifiers(depth=8, filename=f"tt_win32_{i}.txt")
    print(f"wrote tt_win32_{i}.txt")