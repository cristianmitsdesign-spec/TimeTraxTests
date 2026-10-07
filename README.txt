TIMETRAX ENTRY
==============

Timetrax Entry types each employee's approved weekly hours into Timetrax
for you, checks that they went in correctly, and writes a results file
for the timesheet app.

You do not type any hours yourself. You only log in to Timetrax as each
employee and press one button.


WHAT YOU NEED
-------------

- This computer, with Timetrax installed.
- The week's timesheets, downloaded from the Admin screen of the timesheet
  app ("Export PDFs for Timetrax"). This is a zip file, or a folder of
  PDFs named like Kai_Nakamura_Timesheet_WE_2026.09.19.pdf.

Keep the PDFs exactly as downloaded. The hours are stored inside each PDF.
If a PDF is printed to a new PDF or "saved as", that data is lost and the
employee will be skipped.


EACH WEEK, STEP BY STEP
-----------------------

1. Open the program
   Double-click "Timetrax Entry.bat" in this folder.

2. Choose the timesheets
   Click "Choose folder..." and pick the folder of PDFs,
   or click "Choose zip file..." and pick the zip.
   The list shows every employee, their employee number and their hours.

3. For each employee
   The window tells you who is next. For that person:
     a. In Timetrax, log in with their employee number.
     b. Open the time sheet for the week shown in the window.
     c. Click the big "Enter time for ..." button.
     d. Do not touch the mouse or keyboard. The window hides while the
        script types, then comes back with a message.
   When it says "done and checked", log out of Timetrax and repeat for
   the next employee.

4. Upload the results
   When everyone is done, click "Show results file". It is saved next to
   the timesheets, named like results_WE_2026-09-19.json.
   On the Admin screen of the timesheet app, upload that file.

You can stop part way and come back later. Reopen the program, choose the
same timesheets, and employees already finished show as "Done earlier".


WHAT THE STATUSES MEAN
----------------------

  Waiting           Not entered yet.
  Done              Entered and checked. Saved in the results file.
  Done earlier      Finished in an earlier session. Nothing more to do.
  Needs attention   Something did not go in. See "Details" for why.
  Skipped           You chose to skip this employee for now.
  Can't enter       The PDF has a problem the script cannot fix
                    (see "Details"). Enter this one by hand.


PRACTICE RUN
------------

Tick "Practice run (check only, type nothing)" to see what would be
entered without changing anything in Timetrax. Practice runs are never
written to the results file. Untick it to do the real entry.


IF SOMETHING GOES WRONG
-----------------------

"Timetrax is not open on a time sheet"
  Open Timetrax, log in, and open the week's time sheet. Try again.

"Timetrax has the week ending ... open"
  The wrong week is open in Timetrax. Open the right week. Try again.

"Is the right person logged in?"
  The name in Timetrax does not match the timesheet. Choose No, log out,
  and log in with the employee number shown in the window.

"... time did not go in completely" (status: Needs attention)
  Read the Details box. Common causes:
  - "Project Not Found" or a similar Timetrax message: a project, phase
    or activity code Timetrax does not know. Check the code with the
    office, fix it, and press the button again.
  - "already present ... with DIFFERENT hours": that line already has
    other hours in Timetrax. The script never changes existing hours.
    Correct it in Timetrax by hand, then press the button again.
  - "extra line in Timetrax not on the timesheet": Timetrax has hours
    that are not on this timesheet (often because the wrong person was
    logged in). Check who is logged in.
  - "no overhead line ... on this timesheet": overhead lines (projects
    ending in -G) cannot be added by the script, only filled in. Add the
    line in Timetrax by hand, then press the button again.
  Pressing the button again is safe. Lines already entered are checked,
  not typed twice. Employees with problems are not marked done in the
  results file, so the timesheet app is not told anything until they
  are fixed.

"Something went wrong"
  The details are saved in timetrax_entry_error.log in this folder.
  Send that file to whoever looks after this program.


GOOD TO KNOW
------------

- Leave the mouse and keyboard alone while the script is typing. It
  clicks on Timetrax by screen position. One employee takes about a
  minute.
- There is no Stop button while it is typing.
- Uploading the same results file twice is harmless.


FOR WHOEVER MAINTAINS THIS
--------------------------

Requirements: Python at c:\python314 with pywinauto and pypdf installed.

Files:
  Timetrax Entry.bat     Starts the program (pythonw, no console window).
  timetrax_entry.py      The window, plus the per-employee run and check.
  tt_batches.py          Reads the PDFs (mai-timesheet-export.json
                         attachment), checks each batch's checksum,
                         groups entries into Timetrax lines, and writes
                         the results file.
  tt_cell.py             Types into the Timetrax grid. Also works on its
                         own from the command line (see the top of the
                         file).

How a run works:
  - Before typing, the window title must read "Time for <NAME>, week
    ending <DATE>". The week must match; a name mismatch asks first.
  - Lines for projects ending in -G go on the Overhead page; the rest go
    on Direct. OVERHEAD_PROJECT_MAP in tt_batches.py maps the app's
    0000-01-G to Timetrax's 0000-00-G.
  - Several entries on the same day and code are added together.
  - After typing, both pages are read back and compared cell by cell.
    The employee only counts as done if everything matches.

Results file (results_WE_<date>.json, format mai-timesheet-results/1):
  "results"      Verified employees only. This is what the Admin screen
                 applies.
  "not_entered"  Employees with problems, with their log. The app ignores
                 this list. Problems are deliberately not sent as
                 "failed", because in the app a failed import job can
                 only be retried after pressing Requeue.

Known Timetrax details:
  - The Direct page grid has 32 rows; the Overhead page has 18.
  - pywinauto must run with single-threaded COM (sys.coinit_flags = 2,
    set at the top of timetrax_entry.py), or the folder picker hangs.
