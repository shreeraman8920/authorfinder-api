"""AuthorFinder GUI — extract author contact info from news article URLs.

Usage:
    python app.py                     # launch the GUI
    pyinstaller build.spec            # build a standalone .exe
"""

import json
import logging
import os
import queue
import sys
import threading
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, ttk

FROZEN = getattr(sys, "frozen", False)

# ── File logging (writes to %LOCALAPPDATA%/AuthorFinder/error.log) ────────
_LOG_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "AuthorFinder")
os.makedirs(_LOG_DIR, exist_ok=True)
logging.basicConfig(
    filename=os.path.join(_LOG_DIR, "error.log"),
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("authorfinder.gui")

try:
    import openpyxl
except ImportError:
    openpyxl = None  # Excel export disabled if openpyxl is not installed

from authorfinder.crawler import AuthorCrawler
from authorfinder.export import write_results_xlsx

# ── Table columns ───────────────────────────────────────────────────────────
COLUMNS = (
    ("status", "Status", 90),
    ("name", "Author Name", 180),
    ("email", "Email", 220),
    ("linkedin", "LinkedIn", 240),
    ("twitter", "Twitter / X", 200),
    ("job_title", "Job Title", 180),
    ("organization", "Organization", 140),
    ("profile_url", "Profile URL", 280),
    ("location", "Location", 120),
)

class AuthorFinderApp:
    """Main application window."""

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("AuthorFinder 0.2 — Extract Author Contact Info")
        self.root.geometry("1300x720")
        self.root.minsize(900, 500)

        self.results: list[dict] = []          # one entry per URL
        self.running = False
        self.stop_flag = False
        self.update_queue: queue.Queue = queue.Queue()

        self._build_menu()
        self._build_toolbar()
        self._build_progress()
        self._build_table()
        self._build_statusbar()
        self._bind_shortcuts()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── UI construction ─────────────────────────────────────────────────────

    def _build_menu(self):
        menubar = tk.Menu(self.root)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Add URL…", accelerator="Ctrl+U", command=self.add_url)
        file_menu.add_command(label="Load Excel…", accelerator="Ctrl+O", command=self.load_excel)
        file_menu.add_separator()
        file_menu.add_command(label="Export Excel…", accelerator="Ctrl+S", command=self.export_excel)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self._on_close)
        menubar.add_cascade(label="File", menu=file_menu)

        edit_menu = tk.Menu(menubar, tearoff=0)
        edit_menu.add_command(label="Remove Selected", accelerator="Del", command=self.remove_selected)
        edit_menu.add_command(label="Clear All", command=self.clear_all)
        menubar.add_cascade(label="Edit", menu=edit_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="About", command=self._show_about)
        menubar.add_cascade(label="Help", menu=help_menu)

        self.root.config(menu=menubar)

    def _build_toolbar(self):
        frame = ttk.Frame(self.root, padding=(8, 6, 8, 2))
        frame.pack(fill=tk.X)

        ttk.Label(frame, text="URL:").pack(side=tk.LEFT)
        self.url_var = tk.StringVar()
        self.url_entry = ttk.Entry(frame, textvariable=self.url_var, width=60)
        self.url_entry.pack(side=tk.LEFT, padx=(4, 4), fill=tk.X, expand=True)
        self.url_entry.bind("<Return>", lambda e: self.add_url())

        ttk.Button(frame, text="Add URL", command=self.add_url).pack(side=tk.LEFT, padx=2)
        ttk.Button(frame, text="Load Excel…", command=self.load_excel).pack(side=tk.LEFT, padx=2)

        sep = ttk.Separator(frame, orient=tk.VERTICAL)
        sep.pack(side=tk.LEFT, fill=tk.Y, padx=6)

        self.run_btn = ttk.Button(frame, text="▶  Run All", command=self.run_all)
        self.run_btn.pack(side=tk.LEFT, padx=2)

        self.stop_btn = ttk.Button(frame, text="■  Stop", command=self.stop_all, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=2)

        sep2 = ttk.Separator(frame, orient=tk.VERTICAL)
        sep2.pack(side=tk.LEFT, fill=tk.Y, padx=6)

        ttk.Button(frame, text="Export Excel…", command=self.export_excel).pack(side=tk.LEFT, padx=2)
        ttk.Button(frame, text="Remove", command=self.remove_selected).pack(side=tk.LEFT, padx=2)
        ttk.Button(frame, text="Clear", command=self.clear_all).pack(side=tk.LEFT, padx=2)

    def _build_progress(self):
        frame = ttk.Frame(self.root, padding=(8, 4, 8, 2))
        frame.pack(fill=tk.X)

        self.progress_var = tk.DoubleVar(value=0)
        self.progress_bar = ttk.Progressbar(frame, variable=self.progress_var, maximum=100)
        self.progress_bar.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))

        self.progress_label = ttk.Label(frame, text="Ready", width=30, anchor=tk.W)
        self.progress_label.pack(side=tk.LEFT)

    def _build_table(self):
        frame = ttk.Frame(self.root)
        frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=(2, 8))

        # Treeview
        cols = [c[0] for c in COLUMNS]
        self.tree = ttk.Treeview(frame, columns=cols, show="headings", selectmode="extended")

        for col_id, heading, width in COLUMNS:
            self.tree.heading(col_id, text=heading, command=lambda c=col_id: self._sort_column(c))
            self.tree.column(col_id, width=width, minwidth=60)

        # URL column (first, not in COLUMNS tuple — shown as #0 alternative)
        # We'll put URL as the text of each item
        self.tree["displaycolumns"] = cols

        # Scrollbars
        vsb = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self.tree.yview)
        hsb = ttk.Scrollbar(frame, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        frame.grid_rowconfigure(0, weight=1)
        frame.grid_columnconfigure(0, weight=1)

        self.tree.bind("<Double-1>", self._on_double_click)
        self.tree.bind("<Delete>", lambda e: self.remove_selected())

        self.tree.tag_configure("success", background="#d4edda")
        self.tree.tag_configure("pending", background="#f8f9fa")
        self.tree.tag_configure("running", background="#fff3cd")
        self.tree.tag_configure("error", background="#f8d7da")
        self.tree.tag_configure("blocked", background="#f8d7da")
        self.tree.tag_configure("paywall", background="#ffeeba")
        self.tree.tag_configure("no_author_found", background="#e2e3e5")
        self.tree.tag_configure("no_author_page", background="#e2e3e5")

        # Right-click context menu
        self.ctx_menu = tk.Menu(self.root, tearoff=0)
        self.ctx_menu.add_command(label="Copy URL", command=self._copy_url)
        self.ctx_menu.add_command(label="Open in Browser", command=self._open_in_browser)
        self.ctx_menu.add_separator()
        self.ctx_menu.add_command(label="Remove", command=self.remove_selected)
        self.tree.bind("<Button-3>", self._on_right_click)

    def _build_statusbar(self):
        frame = ttk.Frame(self.root, padding=(8, 2))
        frame.pack(fill=tk.X, side=tk.BOTTOM)
        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(frame, textvariable=self.status_var, anchor=tk.W).pack(side=tk.LEFT)

    def _bind_shortcuts(self):
        self.root.bind("<Control-u>", lambda e: self.add_url())
        self.root.bind("<Control-o>", lambda e: self.load_excel())
        self.root.bind("<Control-s>", lambda e: self.export_excel())

    # ── URL management ──────────────────────────────────────────────────────

    def add_url(self):
        url = self.url_var.get().strip()
        if not url:
            return
        if any(r["article_url"] == url for r in self.results):
            self.status_var.set(f"URL already added: {url}")
            return
        self._append_row(url, "pending")
        self.url_var.set("")
        self.status_var.set(f"Added: {url}")

    def load_excel(self):
        if openpyxl is None:
            messagebox.showerror("Missing dependency", "openpyxl is required for Excel support.\nInstall it: pip install openpyxl")
            return
        path = filedialog.askopenfilename(
            filetypes=[("Excel files", "*.xlsx *.xls"), ("All files", "*.*")]
        )
        if not path:
            return
        try:
            wb = openpyxl.load_workbook(path, read_only=True)
            ws = wb.active
            rows = list(ws.iter_rows(values_only=True))
            wb.close()
        except Exception as exc:
            messagebox.showerror("Error reading Excel", str(exc))
            return

        if not rows:
            messagebox.showinfo("Empty file", "The Excel file has no rows.")
            return

        # Find URL column: look for header named "url" / "URL" / "article_url", else use first column
        header = [str(c).strip().lower() if c else "" for c in rows[0]]
        url_col = 0
        for i, h in enumerate(header):
            if h in ("url", "urls", "article_url", "article url", "link", "article"):
                url_col = i
                break

        added = 0
        for row in rows[1:]:
            if url_col < len(row):
                url = str(row[url_col] or "").strip()
                if url and url.startswith("http") and not any(r["article_url"] == url for r in self.results):
                    self._append_row(url, "pending")
                    added += 1
        self.status_var.set(f"Loaded {added} URLs from {os.path.basename(path)}")

    def _append_row(self, url: str, status: str):
        vals = {"article_url": url, "status": status}
        item_id = self.tree.insert(
            "", tk.END,
            values=(url, status, "", "", "", "", "", "", "", ""),
            tags=(status,),
        )
        self.results.append({"article_url": url, "status": status, "_item": item_id, "_data": {}})

    def _update_row(self, item_id: str, result: dict):
        author = result.get("author", {})
        authors = result.get("authors", [])
        if len(authors) > 1:
            name = "; ".join(a.get("name", "") for a in authors if a.get("name"))
            email = "; ".join(a.get("email", "") for a in authors if a.get("email"))
            linkedin = "; ".join(a.get("linkedin", "") for a in authors if a.get("linkedin"))
            twitter = "; ".join(a.get("twitter", "") for a in authors if a.get("twitter"))
            job_title = "; ".join(a.get("job_title", "") for a in authors if a.get("job_title"))
            organization = "; ".join(a.get("organization", "") for a in authors if a.get("organization"))
            profile_url = "; ".join(a.get("profile_url", "") for a in authors if a.get("profile_url"))
            location = "; ".join(a.get("location", "") for a in authors if a.get("location"))
        else:
            name = author.get("name") or ""
            email = author.get("email") or ""
            linkedin = author.get("linkedin") or ""
            twitter = author.get("twitter") or ""
            job_title = author.get("job_title") or ""
            organization = author.get("organization") or ""
            profile_url = author.get("profile_url") or ""
            location = author.get("location") or ""
        vals = (
            result.get("status", "error"),
            name,
            email,
            linkedin,
            twitter,
            job_title,
            organization,
            profile_url,
            location,
        )
        status = result.get("status", "error")
        self.tree.item(item_id, values=vals, tags=(status,))

    # ── Crawl logic ─────────────────────────────────────────────────────────

    def run_all(self):
        pending = [r for r in self.results if r["status"] == "pending"]
        if not pending:
            self.status_var.set("Nothing to run — all URLs are processed.")
            return
        self.running = True
        self.stop_flag = False
        self.run_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        total = len(self.results)
        done = sum(1 for r in self.results if r["status"] != "pending")
        self.progress_var.set(done / total * 100 if total else 0)
        self.progress_label.config(text=f"Starting… 0/{len(pending)}")

        thread = threading.Thread(target=self._crawl_worker, daemon=True)
        thread.start()
        self._poll_queue()

    def stop_all(self):
        self.stop_flag = True
        self.status_var.set("Stopping after current URL…")

    def _crawl_worker(self):
        crawler = AuthorCrawler(delay=1.5, timeout=25)
        pending = [r for r in self.results if r["status"] == "pending"]
        done = 0
        total = len(pending)

        for entry in pending:
            if self.stop_flag:
                self.update_queue.put(("stopped", None))
                return
            url = entry["article_url"]
            item_id = entry["_item"]
            self.update_queue.put(("running", (item_id, url, done, total)))

            try:
                result = crawler.crawl(url)
            except Exception as exc:
                log.exception("Crawl failed for %s", url)
                result = {
                    "article_url": url,
                    "status": "error",
                    "error": f"{type(exc).__name__}: {exc}",
                    "author": {},
                }

            entry["_data"] = result
            entry["status"] = result.get("status", "error")
            self.update_queue.put(("result", (item_id, result, done + 1, total)))
            done += 1

        self.update_queue.put(("done", None))

    def _poll_queue(self):
        try:
            while True:
                msg_type, data = self.update_queue.get_nowait()
                if msg_type == "running":
                    item_id, url, done, total = data
                    self.tree.item(item_id, values=(url, "Running…", "", "", "", "", "", "", "", ""))
                    self.progress_label.config(text=f"Running… {done}/{total}")
                elif msg_type == "result":
                    item_id, result, done, total = data
                    self._update_row(item_id, result)
                    self.progress_var.set(done / total * 100 if total else 0)
                    self.progress_label.config(text=f"Done {done}/{total}")
                    self.status_var.set(f"[{done}/{total}] {result.get('status', '?')} — {result.get('article_url', '')[:80]}")
                elif msg_type == "stopped":
                    self.progress_label.config(text="Stopped")
                    self.status_var.set("Stopped by user.")
                elif msg_type == "done":
                    self.running = False
                    self.run_btn.config(state=tk.NORMAL)
                    self.stop_btn.config(state=tk.DISABLED)
                    self.progress_label.config(text="All done!")
                    self.status_var.set("All URLs processed.")
                    return
        except queue.Empty:
            pass
        if self.running or not self.update_queue.empty():
            self.root.after(100, self._poll_queue)
        else:
            self.running = False
            self.run_btn.config(state=tk.NORMAL)
            self.stop_btn.config(state=tk.DISABLED)

    # ── Export ──────────────────────────────────────────────────────────────

    def export_excel(self):
        if openpyxl is None:
            messagebox.showerror("Missing dependency", "openpyxl is required for Excel export.\nInstall it: pip install openpyxl")
            return
        completed = [r for r in self.results if r.get("_data")]
        if not completed:
            messagebox.showinfo("Nothing to export", "Run at least one URL first.")
            return

        path = filedialog.asksaveasfilename(
            defaultextension=".xlsx",
            filetypes=[("Excel files", "*.xlsx"), ("All files", "*.*")],
            initialfile=f"authorfinder_export_{datetime.now():%Y%m%d_%H%M%S}.xlsx",
        )
        if not path:
            return

        try:
            rows = write_results_xlsx([r["_data"] for r in completed], path)
            self.status_var.set(f"Exported {rows} results to {os.path.basename(path)}")
        except Exception as exc:
            messagebox.showerror("Export error", str(exc))

    # ── Table interactions ──────────────────────────────────────────────────

    def remove_selected(self):
        selected = self.tree.selection()
        if not selected:
            return
        for item_id in selected:
            self.tree.delete(item_id)
            self.results = [r for r in self.results if r.get("_item") != item_id]
        self.status_var.set(f"Removed {len(selected)} row(s)")

    def clear_all(self):
        if self.running:
            messagebox.showwarning("Busy", "Stop the crawl first.")
            return
        if self.results and not messagebox.askyesno("Confirm", "Clear all rows?"):
            return
        self.tree.delete(*self.tree.get_children())
        self.results.clear()
        self.progress_var.set(0)
        self.progress_label.config(text="Ready")
        self.status_var.set("Cleared")

    def _on_double_click(self, event):
        sel = self.tree.selection()
        if not sel:
            return
        item_id = sel[0]
        entry = next((r for r in self.results if r.get("_item") == item_id), None)
        if not entry or not entry.get("_data"):
            return
        self._show_details(entry["_data"])

    def _show_details(self, result: dict):
        win = tk.Toplevel(self.root)
        win.title("Author Details")
        win.geometry("640x520")
        win.transient(self.root)

        text = tk.Text(win, wrap=tk.WORD, padx=12, pady=12, font=("Consolas", 10))
        scroll = ttk.Scrollbar(win, orient=tk.VERTICAL, command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        formatted = json.dumps(result, indent=2, ensure_ascii=False, default=str)
        text.insert(tk.END, formatted)
        text.config(state=tk.DISABLED)

    def _on_right_click(self, event):
        iid = self.tree.identify_row(event.y)
        if iid:
            self.tree.selection_set(iid)
            self.ctx_menu.tk_popup(event.x_root, event.y_root)

    def _copy_url(self):
        sel = self.tree.selection()
        if sel:
            vals = self.tree.item(sel[0], "values")
            if vals:
                self.root.clipboard_clear()
                self.root.clipboard_append(vals[0])

    def _open_in_browser(self):
        import webbrowser
        sel = self.tree.selection()
        if sel:
            vals = self.tree.item(sel[0], "values")
            if vals and vals[0].startswith("http"):
                webbrowser.open(vals[0])

    def _sort_column(self, col):
        items = [(self.tree.set(k, col), k) for k in self.tree.get_children("")]
        items.sort()
        for idx, (val, k) in enumerate(items):
            self.tree.move(k, "", idx)

    # ── Misc ────────────────────────────────────────────────────────────────

    def _show_about(self):
        messagebox.showinfo(
            "About AuthorFinder",
            "AuthorFinder 0.2\n\n"
            "Extract journalist/author contact information from news articles.\n\n"
            "Features:\n"
            "  - Multi-author article support\n"
            "  - Paywall and bot-protection detection\n"
            "  - Schema.org microdata parsing\n"
            "  - Expanded social platform coverage\n"
            "  - International name support\n\n"
            "Uses requests/BeautifulSoup for static pages and\n"
            "Playwright (headless Chromium) for JavaScript-rendered pages.\n\n"
            "Respects robots.txt and rate-limits requests.",
        )

    def _on_close(self):
        if self.running:
            if messagebox.askyesno("Quit", "A crawl is in progress. Stop and quit?"):
                self.stop_flag = True
                self.root.after(500, self.root.destroy)
            return
        self.root.destroy()


def main():
    root = tk.Tk()
    AuthorFinderApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
