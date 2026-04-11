import os
import sys
import time
import base64
import threading
import concurrent.futures
import requests # type: ignore
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
import re
from io import BytesIO
from PIL import Image # type: ignore


import tkinter as tk
from tkinter import filedialog, scrolledtext, messagebox, ttk

# High DPI awareness for Windows
try:
    from ctypes import windll
    windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass

# Optional rembg block
import importlib.util
# rembg is local-imported when needed


# Licensing block
import license_utils # type: ignore




class RedirectText(object):
    def __init__(self, text_ctrl):
        self.output = text_ctrl
        self.output.configure(state='normal')

    def write(self, string):
        self.output.insert(tk.END, string)
        self.output.see(tk.END)
        self.output.update_idletasks()

    def flush(self):
        pass


from image_processor_core import ImageProcessorCore, _get_sheet # type: ignore

class ImageProcessorApp(ImageProcessorCore):
    mode_var: tk.StringVar
    log_text: tk.Text | scrolledtext.ScrolledText
    out_dir_var: tk.StringVar
    platform_var: tk.StringVar
    product_id_var: tk.StringVar
    bulk_text: tk.Text | scrolledtext.ScrolledText
    use_threads_var: tk.BooleanVar
    thread_count_var: tk.IntVar
    pid_label: tk.Label
    platform_label: tk.Label
    platform_combo: ttk.Combobox
    input_container: tk.Frame
    product_id_entry: tk.Entry
    thread_frame: tk.Frame
    thread_spinbox: ttk.Spinbox
    api_key_var: tk.StringVar
    target_width_var: tk.IntVar
    target_height_var: tk.IntVar
    white_bg_var: tk.BooleanVar
    watermark_enabled_var: tk.BooleanVar
    templates: list[str]
    watermark_template_var: tk.StringVar
    watermark_combo: ttk.Combobox
    watermark_path_var: tk.StringVar
    watermark_entry: tk.Entry
    watermark_btn: tk.Button
    watermark_mode_var: tk.StringVar
    watermark_mode_combo: ttk.Combobox
    product_scale_var: tk.IntVar
    start_btn: tk.Button
    pause_btn: tk.Button
    stop_btn: tk.Button
    # Upload / Sheet vars
    vps_host_var: tk.StringVar
    sheet_id_var: tk.StringVar
    worksheet_var: tk.StringVar

    def __init__(self, root):
        self.root = root
        try:
            self.root.title("E-commerce Image Fetcher & Processor")
            # Increased base width for a more spacious feel, height is more flexible now
            self.root.geometry("850x900")
            self.root.minsize(700, 600)
            
            # Apply custom icon to the application window
            base_path = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
            icon_path = os.path.join(base_path, 'icon.ico')
            if os.path.exists(icon_path):
                self.root.iconbitmap(icon_path)
        except AttributeError:
            pass
        
        self.create_widgets()
        
        # Output redirect multiplexing
        if not hasattr(sys.stdout, 'outputs'):
            class MultiplexRedirect:
                outputs = []
                def write(self, string):
                    for out in self.outputs:
                        try:
                            out.insert(tk.END, string)
                            out.see(tk.END)
                            out.update_idletasks()
                        except: pass
                def flush(self): pass
            sys.stdout = MultiplexRedirect()
        sys.stdout.outputs.append(self.log_text) # type: ignore
        
        # Threading Flow Control Flags
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()
        
    def create_widgets(self):
        # --- Scrollable Container for Settings ---
        self.canvas = tk.Canvas(self.root, highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(self.root, orient="vertical", command=self.canvas.yview)
        
        # main_frame becomes the inner frame inside the canvas
        self.main_frame = tk.Frame(self.canvas, padx=15, pady=5)
        
        self.main_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )

        # Create a window inside the canvas to hold main_frame
        self.canvas.create_window((0, 0), window=self.main_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        # Enable mouse wheel scrolling
        self.canvas.bind_all("<MouseWheel>", lambda e: self.canvas.yview_scroll(int(-1*(e.delta/120)), "units"))

        # Pack canvas and scrollbar (they take upper part)
        # Note: We use grid or pack carefully here to allow the log area at bottom.
        # --- Layout setup ---
        # Upper part (Settings): Scrollable
        # Lower part (Console): Fixed at bottom or filling remaining space
        
        # To handle window resize and keeping main_frame width matched to canvas
        def _on_canvas_configure(event):
            self.canvas.itemconfig(self.canvas.find_withtag("all")[0], width=event.width)
        self.canvas.bind("<Configure>", _on_canvas_configure)

        main_frame = self.main_frame

        # Output Directory Configuration
        out_frame = tk.LabelFrame(main_frame, text="Output Folder", padx=10, pady=5)
        out_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.out_dir_var = tk.StringVar(value=os.path.join(os.getcwd(), "processed_images"))
        tk.Entry(out_frame, textvariable=self.out_dir_var, width=55).grid(row=0, column=0, padx=5, pady=5)
        tk.Button(out_frame, text="Browse", command=self.browse_out_dir).grid(row=0, column=1, padx=5, pady=5)

        # Fetch Configuration
        fetch_frame = tk.LabelFrame(main_frame, text="Fetch Settings", padx=10, pady=10)
        fetch_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.platform_label = tk.Label(fetch_frame, text="Platform:")
        self.platform_label.grid(row=0, column=0, sticky='ne', pady=5)
        self.platform_var = tk.StringVar(value="Amazon")
        self.platform_combo = ttk.Combobox(fetch_frame, textvariable=self.platform_var, values=["Amazon", "Walmart"], state="readonly", width=15)
        self.platform_combo.grid(row=0, column=1, sticky='nw', padx=5, pady=5)

        tk.Label(fetch_frame, text="Mode:").grid(row=1, column=0, sticky='e', pady=5)
        mode_frame = tk.Frame(fetch_frame)
        mode_frame.grid(row=1, column=1, sticky='w', padx=5, pady=5)
        self.mode_var = tk.StringVar(value="Single")
        tk.Radiobutton(mode_frame, text="Single ASIN", variable=self.mode_var, value="Single", command=self.toggle_mode).pack(side=tk.LEFT)
        tk.Radiobutton(mode_frame, text="Bulk ASINs", variable=self.mode_var, value="Bulk", command=self.toggle_mode).pack(side=tk.LEFT)

        self.pid_label = tk.Label(fetch_frame, text="Product ID (ASIN / ID):")
        self.pid_label.grid(row=2, column=0, sticky='ne', pady=5)
        
        # Container for changing input types
        self.input_container = tk.Frame(fetch_frame)
        self.input_container.grid(row=2, column=1, sticky='nw', padx=5, pady=5)

        self.product_id_var = tk.StringVar()
        self.product_id_entry = tk.Entry(self.input_container, textvariable=self.product_id_var, width=25)
        self.product_id_entry.pack(anchor='w')

        self.bulk_text = scrolledtext.ScrolledText(self.input_container, width=40, height=5)
        # Hidden by default since Single is default
        
        # Thread settings (hidden by default)
        self.thread_frame = tk.Frame(fetch_frame)
        self.thread_frame.grid(row=3, column=1, sticky='nw', padx=5, pady=0)
        self.use_threads_var = tk.BooleanVar(value=False)
        tk.Checkbutton(self.thread_frame, text="Enable Multi-threading", variable=self.use_threads_var, command=self.toggle_threads).pack(side=tk.LEFT)
        
        tk.Label(self.thread_frame, text="Threads:").pack(side=tk.LEFT, padx=(10, 2))
        self.thread_count_var = tk.IntVar(value=4)
        self.thread_spinbox = ttk.Spinbox(self.thread_frame, from_=2, to=20, textvariable=self.thread_count_var, width=5, state=tk.DISABLED)
        self.thread_spinbox.pack(side=tk.LEFT)
        self.thread_frame.grid_remove() # Hide initially

        tk.Label(fetch_frame, text="ScraperAPI Key:").grid(row=4, column=0, sticky='e', pady=5)
        self.api_key_var = tk.StringVar()
        tk.Entry(fetch_frame, textvariable=self.api_key_var, width=50).grid(row=4, column=1, sticky='w', padx=5, pady=5)

        # Load from Sheet Button (Bulk Mode Only)
        self.load_sheet_btn = tk.Button(fetch_frame, text="📥 Load IDs from Sheet", command=self.load_from_sheet, bg="#4CAF50", fg="white", font=("Arial", 9, "bold"), padx=5)
        self.load_sheet_btn.grid(row=2, column=2, sticky='w', padx=5, pady=5)
        self.load_sheet_btn.grid_remove() # Hide initially

        # Processing Configuration
        proc_frame = tk.LabelFrame(main_frame, text="Processing Settings", padx=10, pady=10)
        proc_frame.pack(fill=tk.X, pady=(0, 10))
        
        tk.Label(proc_frame, text="Target Width (px):").grid(row=0, column=0, sticky='e', pady=5)
        self.target_width_var = tk.IntVar(value=1000)
        self.width_entry = tk.Entry(proc_frame, textvariable=self.target_width_var, width=10)
        self.width_entry.grid(row=0, column=1, sticky='w', padx=5, pady=5)

        tk.Label(proc_frame, text="Target Height (px):").grid(row=0, column=2, sticky='e', pady=5, padx=(10, 0))
        self.target_height_var = tk.IntVar(value=1000)
        self.height_entry = tk.Entry(proc_frame, textvariable=self.target_height_var, width=10)
        self.height_entry.grid(row=0, column=3, sticky='w', padx=5, pady=5)

        # Aspect ratio linking — when lock is on, editing one dimension auto-adjusts the other
        self._aspect_ratio = 1.0  # width / height ratio, updated on each valid edit
        self._updating_ratio = False  # guard flag to prevent infinite recursion
        self._last_edited = 'width'  # track which field was last manually edited

        self.width_entry.bind('<KeyRelease>', self._on_width_changed)
        self.height_entry.bind('<KeyRelease>', self._on_height_changed)

        # White background handling
        self.white_bg_var = tk.BooleanVar(value=True)
        tk.Checkbutton(proc_frame, text="Make First Image White Background (Requires rembg)", variable=self.white_bg_var).grid(row=1, column=0, columnspan=3, sticky='w', pady=2)
        
        self.lock_aspect_ratio_var = tk.BooleanVar(value=True)
        tk.Checkbutton(proc_frame, text="Lock Aspect Ratio (Auto-adjust other dimension)", variable=self.lock_aspect_ratio_var).grid(row=1, column=3, sticky='w', pady=2)

        tk.Label(proc_frame, text="(Note: The background removal engine loads on the first use)", fg="gray", font=("Arial", 8)).grid(row=2, column=0, columnspan=3, sticky='w', pady=0)

        # Watermark
        self.watermark_enabled_var = tk.BooleanVar(value=False)
        tk.Checkbutton(proc_frame, text="Add Watermark", variable=self.watermark_enabled_var, command=self.toggle_watermark).grid(row=3, column=0, sticky='w', pady=5)
        
        # Determine available templates
        self.templates = ["Custom File..."]
        if os.path.exists("templates"):
            for f in os.listdir("templates"):
                if f.lower().endswith(".png"):
                    self.templates.append(f)
                    
        self.watermark_template_var = tk.StringVar(value=self.templates[1] if len(self.templates) > 1 else self.templates[0])
        self.watermark_combo = ttk.Combobox(proc_frame, textvariable=self.watermark_template_var, values=self.templates, state="disabled", width=25)
        self.watermark_combo.grid(row=3, column=1, padx=5, pady=5)
        self.watermark_combo.bind("<<ComboboxSelected>>", self.on_template_selected)
        
        self.watermark_path_var = tk.StringVar(value="")
        # Seed path immediately if a template is pre-selected
        if len(self.templates) > 1:
            self.watermark_path_var.set(os.path.join("templates", self.templates[1]))
        self.watermark_entry = tk.Entry(proc_frame, textvariable=self.watermark_path_var, width=20, state=tk.DISABLED)
        self.watermark_entry.grid(row=3, column=2, padx=5, pady=5)
        
        self.watermark_btn = tk.Button(proc_frame, text="Browse PNG", command=self.browse_watermark, state=tk.DISABLED)
        self.watermark_btn.grid(row=3, column=3, padx=5, pady=5)

        tk.Label(proc_frame, text="Watermark Mode:").grid(row=4, column=0, sticky='e', pady=5)
        self.watermark_mode_var = tk.StringVar(value="Full Image Frame")
        self.watermark_mode_combo = ttk.Combobox(proc_frame, textvariable=self.watermark_mode_var, values=["Center Logo (20%)", "Full Image Frame"], state="disabled", width=20)
        self.watermark_mode_combo.grid(row=4, column=1, padx=5, pady=5, sticky='w')

        tk.Label(proc_frame, text="Product Scale (%):").grid(row=4, column=2, sticky='e', pady=5, padx=(10, 0))
        self.product_scale_var = tk.IntVar(value=70)
        ttk.Spinbox(proc_frame, from_=30, to=95, textvariable=self.product_scale_var, width=6).grid(row=4, column=3, sticky='w', padx=5, pady=5)

        # Template Tools
        tk.Button(
            proc_frame,
            text="🪄 Make Template Transparent",
            command=self.make_template_transparent,
            bg="#673AB7", fg="white",
            font=("Arial", 9, "bold"),
            padx=6, pady=3
        ).grid(row=5, column=0, columnspan=4, sticky='w', padx=5, pady=(6, 2))
        tk.Label(
            proc_frame,
            text="Opens any template PNG and removes its white center area → saves a transparent-center copy to templates/",
            fg="gray", font=("Arial", 8)
        ).grid(row=6, column=0, columnspan=4, sticky='w', padx=5)

        # Upload Settings
        upload_frame = tk.LabelFrame(main_frame, text="Upload Settings (Optional)", padx=10, pady=10)
        upload_frame.pack(fill=tk.X, pady=(0, 10))

        tk.Label(upload_frame, text="VPS Host URL:").grid(row=0, column=0, sticky='e', pady=4)
        self.vps_host_var = tk.StringVar(value="https://images.thedailytraveller.online")
        vps_combo = ttk.Combobox(upload_frame, textvariable=self.vps_host_var, width=45)
        vps_combo['values'] = ("https://images.thedailytraveller.online", "")
        vps_combo.grid(row=0, column=1, columnspan=3, sticky='w', padx=5, pady=4)
        tk.Label(upload_frame, text="(leave blank to skip VPS upload)",
                 fg="gray", font=("Arial", 8)).grid(row=0, column=4, sticky='w', padx=2)

        tk.Label(upload_frame, text="Google Sheet ID:").grid(row=1, column=0, sticky='e', pady=4)
        self.sheet_id_var = tk.StringVar(value="")
        tk.Entry(upload_frame, textvariable=self.sheet_id_var, width=48).grid(row=1, column=1, columnspan=3, sticky='w', padx=5, pady=4)
        tk.Label(upload_frame, text="(leave blank to skip sheet update)",
                 fg="gray", font=("Arial", 8)).grid(row=1, column=4, sticky='w', padx=2)

        tk.Label(upload_frame, text="Worksheet Name:").grid(row=2, column=0, sticky='e', pady=4)
        self.worksheet_var = tk.StringVar(value="Sheet1")
        tk.Entry(upload_frame, textvariable=self.worksheet_var, width=20).grid(row=2, column=1, sticky='w', padx=5, pady=4)

        action_frame = tk.Frame(main_frame)
        action_frame.pack(fill=tk.X, pady=10)
        
        self.start_btn = tk.Button(action_frame, text="Fetch & Process", command=self.start_processing, bg="#2196F3", fg="white", font=("Arial", 10, "bold"), padx=10, pady=5)
        self.start_btn.pack(side=tk.LEFT, padx=5)
        
        self.pause_btn = tk.Button(action_frame, text="Pause", command=self.toggle_pause, bg="#FFC107", fg="black", font=("Arial", 10, "bold"), padx=10, pady=5, state=tk.DISABLED)
        self.pause_btn.pack(side=tk.LEFT, padx=5)
        
        self.stop_btn = tk.Button(action_frame, text="Stop", command=self.stop_processing, bg="#F44336", fg="white", font=("Arial", 10, "bold"), padx=10, pady=5, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=5)
        
        # --- Final Layout Packing ---
        # We pack from the edges inward
        
        # 1. Console at the very bottom (Fixed height mostly)
        console_frame = tk.Frame(self.root, padx=15)
        console_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(5, 15))

        log_label_frame = tk.LabelFrame(console_frame, text="Console Output", padx=5, pady=5)
        log_label_frame.pack(fill=tk.BOTH, expand=True)
        
        self.log_text = scrolledtext.ScrolledText(log_label_frame, wrap=tk.WORD, state='normal', height=15)
        self.log_text.pack(fill=tk.BOTH, expand=True)

        # 2. Scrollbar on the right
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # 3. Canvas fills the remaining top/middle space
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    def toggle_pause(self):
        if self.pause_event.is_set():
            # Currently paused, so resume
            self.pause_event.clear()
            self.pause_btn.config(text="Pause")
            print("\n[INFO] --- RESUMED ---")
        else:
            # Currently running, so pause
            self.pause_event.set()
            self.pause_btn.config(text="Resume")
            print("\n[INFO] --- PAUSED ---")

    def stop_processing(self):
        self.stop_event.set()
        print("\n[INFO] --- STOPPING SIGNAL SENT ---")

    def browse_out_dir(self):
        folder = filedialog.askdirectory(title="Select Output Directory")
        if folder:
            self.out_dir_var.set(folder)

    def browse_watermark(self):
        filename = filedialog.askopenfilename(title="Select Watermark (PNG)", filetypes=[("PNG Files", "*.png"), ("All Files", "*.*")])
        if filename:
            self.watermark_path_var.set(filename)

    def toggle_watermark(self):
        if self.watermark_enabled_var.get():
            self.watermark_combo.config(state="readonly")
            self.watermark_mode_combo.config(state="readonly")
            self.on_template_selected()
        else:
            self.watermark_combo.config(state="disabled")
            self.watermark_entry.config(state=tk.DISABLED)
            self.watermark_btn.config(state=tk.DISABLED)
            self.watermark_mode_combo.config(state="disabled")
            
    def on_template_selected(self, event=None):
        if not self.watermark_enabled_var.get():
            return
            
        selection = self.watermark_template_var.get()
        if selection == "Custom File...":
            self.watermark_entry.config(state=tk.NORMAL)
            self.watermark_btn.config(state=tk.NORMAL)
        else:
            self.watermark_entry.config(state=tk.DISABLED)
            self.watermark_btn.config(state=tk.DISABLED)
            # Set hidden path variable to the template path
            self.watermark_path_var.set(os.path.join("templates", selection))

    def toggle_mode(self):
        if self.mode_var.get() == "Single":
            self.platform_label.grid()
            self.platform_combo.grid()
            self.pid_label.config(text="Product ID (ASIN / ID):")
            self.bulk_text.pack_forget()
            self.product_id_entry.pack(anchor='w')
            self.thread_frame.grid_remove()
            self.load_sheet_btn.grid_remove()
        else:
            self.platform_label.grid_remove()
            self.platform_combo.grid_remove()
            self.pid_label.config(text="Product IDs\n(One per line):")
            self.product_id_entry.pack_forget()
            self.bulk_text.pack(anchor='w')
            self.thread_frame.grid()
            self.load_sheet_btn.grid()
            
    def toggle_threads(self):
        if self.use_threads_var.get():
            self.thread_spinbox.config(state=tk.NORMAL)
        else:
            self.thread_spinbox.config(state=tk.DISABLED)

    def _on_width_changed(self, event=None):
        """When user edits width and aspect ratio is locked, auto-adjust height."""
        if self._updating_ratio:
            return
        if not self.lock_aspect_ratio_var.get():
            return
        try:
            w = int(self.width_entry.get())
            if w <= 0:
                return
        except (ValueError, tk.TclError):
            return
        
        self._last_edited = 'width'
        
        # Calculate new height based on the locked ratio
        if self._aspect_ratio > 0:
            new_h = max(1, int(round(w / self._aspect_ratio)))
            self._updating_ratio = True
            self.target_height_var.set(new_h)
            self._updating_ratio = False

    def _on_height_changed(self, event=None):
        """When user edits height and aspect ratio is locked, auto-adjust width."""
        if self._updating_ratio:
            return
        if not self.lock_aspect_ratio_var.get():
            return
        try:
            h = int(self.height_entry.get())
            if h <= 0:
                return
        except (ValueError, tk.TclError):
            return
        
        self._last_edited = 'height'
        
        # Calculate new width based on the locked ratio
        if self._aspect_ratio > 0:
            new_w = max(1, int(round(h * self._aspect_ratio)))
            self._updating_ratio = True
            self.target_width_var.set(new_w)
            self._updating_ratio = False

    def make_template_transparent(self):
        """Open a template PNG and flood-fill the center white area with transparency.
        Saves a new file with '_transparent.png' suffix into the templates folder.
        """
        path = filedialog.askopenfilename(
            title="Select Template PNG to Convert",
            filetypes=[("PNG Files", "*.png"), ("All Files", "*.*")]
        )
        if not path:
            return

        try:
            img = Image.open(path).convert("RGBA")
            pixels = img.load() # type: ignore
            w, h = img.size
            cx, cy = w // 2, h // 2

            # --- BFS flood fill from the center ---
            # Replaces white-ish connected pixels with fully transparent
            WHITE_THRESHOLD = 30  # tolerance: 255-30=225, anything above is "white enough"

            def is_white(px):
                r, g, b, a = px
                return r >= (255 - WHITE_THRESHOLD) and g >= (255 - WHITE_THRESHOLD) and b >= (255 - WHITE_THRESHOLD) and a > 10

            from collections import deque
            visited = set()
            queue = deque([(cx, cy)])

            while queue:
                x, y = queue.popleft()
                if (x, y) in visited:
                    continue
                if x < 0 or x >= w or y < 0 or y >= h:
                    continue
                if pixels is None:
                    continue
                px = pixels[x, y]
                if not is_white(px):
                    continue
                pixels[x, y] = (0, 0, 0, 0)  # make transparent
                visited.add((x, y))
                queue.extend([(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)])

            # Save to templates folder with _transparent suffix
            os.makedirs("templates", exist_ok=True)
            base_name = os.path.splitext(os.path.basename(path))[0]
            out_name = f"{base_name}_transparent.png"
            out_path = os.path.join("templates", out_name)
            img.save(out_path, format="PNG")

            # Refresh template combobox
            self.templates = ["Custom File..."]
            for f in os.listdir("templates"):
                if f.lower().endswith(".png"):
                    self.templates.append(f)
            self.watermark_combo.config(values=self.templates)
            if out_name in self.templates:
                self.watermark_template_var.set(out_name)
                self.watermark_path_var.set(out_path)

            messagebox.showinfo(
                "Done",
                f"Transparent template saved:\n{out_path}\n\nYou can now select it from the watermark dropdown."
            )
            print(f"[TEMPLATE] White center removed → {out_path} ({len(visited)} pixels made transparent)")

        except Exception as e:
            messagebox.showerror("Error", f"Failed to process template:\n{e}")
            print(f"[ERROR] make_template_transparent: {e}")

    def load_from_sheet(self):
        """Fetch product IDs from Google Sheet and populate bulk text area.
        Follows 'image upscaler v2' logic: column B, starting row 6.
        """
        sheet_id = self.sheet_id_var.get().strip()
        worksheet_name = self.worksheet_var.get().strip()
        
        if not sheet_id:
            messagebox.showwarning("Missing Config", "Please enter a Google Sheet ID in the Upload Settings section first.")
            return

        def _worker():
            print(f"\n[SHEET] Connecting to fetch IDs: {sheet_id} [{worksheet_name}]")
            try:
                sheet = _get_sheet(sheet_id, worksheet_name)
                # pull column B (index 2) starting from row 6
                header_row = 5
                headers = sheet.row_values(header_row)
                asin_col = 2  # Default fallback
                for col_i, h in enumerate(headers, 1):
                    if h.strip().lower() == "custom label (sku)":
                        asin_col = col_i
                        break
                
                print(f"  [INFO] Loading IDs from column {asin_col} ('Custom label (SKU)')")
                values = sheet.col_values(asin_col)[header_row:]  # Row 6 is index 5
                
                # Strip trailing empty strings to avoid loading 1000 blank bottom rows
                while values and not str(values[-1]).strip():
                    values.pop()
                
                if not values:
                    self.root.after(0, lambda: messagebox.showinfo("No Data", "No IDs found in the specified column."))
                    return

                def update_ui():
                    self.bulk_text.delete("1.0", tk.END)
                    self.bulk_text.insert(tk.END, "\n".join(str(v) for v in values))
                    messagebox.showinfo("Success", f"Successfully loaded {len(values)} line(s) from sheet.")
                    print(f"[SHEET] Loaded {len(values)} lines into input area (preserving row spacing).")

                self.root.after(0, update_ui)

            except Exception as e:
                error_msg = str(e)
                self.root.after(0, lambda: messagebox.showerror("Sheet Error", f"Failed to load from sheet:\n{error_msg}"))
                print(f"[ERROR] load_from_sheet: {error_msg}")

        threading.Thread(target=_worker, daemon=True).start()

    # --- Scraping Methods ---


    def remove_asin_from_ui(self, pid: str):
        """Remove a successfully processed ASIN from the bulk text box."""
        current_text = self.bulk_text.get("1.0", tk.END)
        lines = current_text.split('\n')
        # Filter out the matching ASIN (exact match ignoring whitespace)
        new_lines = [line for line in lines if line.strip() != pid.strip()]
        self.bulk_text.delete("1.0", tk.END)
        self.bulk_text.insert(tk.END, "\n".join(new_lines))

    def run_process(self):
        platform = self.platform_var.get()
        out_base = self.out_dir_var.get().strip()
        api_key = self.api_key_var.get().strip()

        # Upload / Sheet config
        vps_base_url = self.vps_host_var.get().strip()
        sheet_id = self.sheet_id_var.get().strip()
        worksheet_name = self.worksheet_var.get().strip()

        mode = self.mode_var.get()
        product_ids = []

        if mode == "Single":
            pid = self.product_id_var.get().strip()
            if pid:
                product_ids.append(pid)
        else:
            raw_text = self.bulk_text.get("1.0", "end-1c")
            # Preserve empty lines so line_idx perfectly matches sheet row idx
            product_ids = raw_text.split('\n')

        # We will filter out empty strings during processing, but we need the exact indices
        has_items = any(pid.strip() for pid in product_ids)
        if not has_items:
            print("[ERROR] Product ID list cannot be empty.")
            self.root.after(0, lambda: self.start_btn.config(state=tk.NORMAL))
            return

        try:
            target_width = self.target_width_var.get()
            target_height = self.target_height_var.get()
        except tk.TclError:
            print("[ERROR] Target width and height must be integers.")
            self.root.after(0, lambda: self.start_btn.config(state=tk.NORMAL))
            return

        do_white_bg = self.white_bg_var.get()
        watermark_enabled = self.watermark_enabled_var.get()
        watermark_path = self.watermark_path_var.get() if watermark_enabled else None
        product_scale = self.product_scale_var.get()

        watermark_mode = self.watermark_mode_var.get()
        is_template = watermark_enabled and (watermark_mode == "Full Image Frame")
        lock_aspect_ratio = self.lock_aspect_ratio_var.get()

        max_workers = 1
        if mode == "Bulk" and self.use_threads_var.get():
            try:
                max_workers = self.thread_count_var.get()
                if max_workers < 1:
                    max_workers = 1
            except tk.TclError:
                max_workers = 4

        print(f"\n==============================================")
        print(f"[START] Initializing process for {len(product_ids)} Product(s). Mode: {mode}, Threads: {max_workers}")

        # Connect to Google Sheet (once, shared across threads)
        sheet = None
        if sheet_id:
            print("[INFO] Connecting to Google Sheet...")
            try:
                sheet = _get_sheet(sheet_id, worksheet_name or 'Sheet1')
                print("[OK] Connected to Google Sheet")
            except Exception as e:
                print(f"[WARN] Could not connect to Google Sheet: {e} — sheet update will be skipped.")
        else:
            print("[INFO] No Google Sheet ID provided — sheet update skipped.")

        if vps_base_url:
            print(f"[INFO] VPS upload enabled: {vps_base_url}")
        else:
            print("[INFO] No VPS Host URL provided — VPS upload skipped.")

        # Execute processing
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_pid = {}
            for row_idx, raw_pid in enumerate(product_ids, start=1):
                if self.stop_event.is_set():
                    break
                    
                pid = raw_pid.strip()
                if not pid:
                    continue  # Skip empty lines but maintain the row_idx progression

                # Platform Auto-detection
                if mode == "Bulk":
                    # In Bulk mode, the Platform dropdown is hidden. We primary auto-detect.
                    if pid.isdigit():
                        current_platform = "Walmart"
                    else:
                        # Logic: If it starts with 'B' or contains non-digits, assume Amazon
                        current_platform = "Amazon"
                else:
                    # Single mode: Use dropdown select, but allow auto-fix if clearly wrong
                    current_platform = platform
                    if current_platform == "Amazon" and pid.isdigit() and len(pid) >= 8:
                        print(f"  [INFO] Auto-switching to Walmart for numeric ID: {pid}")
                        current_platform = "Walmart"
                    elif current_platform == "Walmart" and (pid.startswith("B0") or not pid.isdigit()):
                        print(f"  [INFO] Auto-switching to Amazon for ID: {pid}")
                        current_platform = "Amazon"

                future = executor.submit(
                    self.process_single_product, # type: ignore
                    pid, current_platform, out_base, api_key,
                    target_width, target_height,
                    do_white_bg, watermark_path, is_template,
                    vps_base_url, sheet, row_idx, product_scale, lock_aspect_ratio
                )
                future_to_pid[future] = pid

            # Wait for all to complete
            for future in concurrent.futures.as_completed(future_to_pid):
                if self.stop_event.is_set():
                    for f in future_to_pid:
                        f.cancel()
                    break
                pid = future_to_pid[future]
                try:
                    success = future.result()
                    if success and mode == "Bulk":
                        # Success! Schedule UI update to remove it from the box.
                        self.root.after(0, self.remove_asin_from_ui, pid)
                except Exception as e:
                    print(f"[FATAL] Thread error for {pid}: {e}")

        print("\n[FINISH] Process complete.\n")
        self.reset_ui_state()

    def reset_ui_state(self):
        self.start_btn.config(state=tk.NORMAL)
        self.pause_btn.config(state=tk.DISABLED, text="Pause")
        self.stop_btn.config(state=tk.DISABLED)

    def start_processing(self):
        self.start_btn.config(state=tk.DISABLED)
        self.pause_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.NORMAL)
        
        self.stop_event.clear()
        self.pause_event.clear()
        
        # We don't clear the log text so users can see previous runs
        t = threading.Thread(target=self.run_process, daemon=True)
        t.start()


def perform_license_check():
    machine_code = license_utils.get_machine_code()
    app_data = license_utils.get_app_data_path()
    license_file = os.path.join(app_data, "license.txt")
    
    saved_key = ""
    if os.path.exists(license_file):
        try:
            with open(license_file, "r") as f:
                saved_key = f.read().strip()
        except Exception:
            pass

    if saved_key and license_utils.validate_license(machine_code, saved_key):
        return True

    # If no valid license is found, prompt the user
    root = tk.Tk()
    root.withdraw() # Hide main window for the dialog
    
    dialog = tk.Toplevel(root)
    dialog.title("License Required")
    dialog.geometry("450x300")
    dialog.grab_set()
    
    tk.Label(dialog, text="This software requires a valid license.", font=("Arial", 12, "bold")).pack(pady=10)
    
    tk.Label(dialog, text="Your Machine Code:").pack()
    mc_entry = tk.Entry(dialog, width=50)
    mc_entry.insert(0, machine_code)
    mc_entry.config(state="readonly")
    mc_entry.pack(pady=5)
    
    tk.Label(dialog, text="Enter License Key:").pack(pady=(10, 0))
    key_entry = tk.Entry(dialog, width=50)
    key_entry.pack(pady=5)
    
    result = {"success": False}
    
    def verify_and_save():
        key = key_entry.get().strip()
        if license_utils.validate_license(machine_code, key):
            try:
                with open(license_file, "w") as f:
                    f.write(key)
                messagebox.showinfo("Success", "License activated successfully!", parent=dialog)
                result["success"] = True
                dialog.destroy()
            except Exception as e:
                messagebox.showerror("Error", f"Failed to save license: {e}", parent=dialog)
        else:
            messagebox.showerror("Error", "Invalid License Key.", parent=dialog)
            
    def copy_mc():
        dialog.clipboard_clear()
        dialog.clipboard_append(machine_code)
        
    tk.Button(dialog, text="Copy Machine Code", command=copy_mc).pack(pady=5)
    tk.Button(dialog, text="Activate", command=verify_and_save, bg="green", fg="white").pack(pady=10)
    
    def on_close():
        dialog.destroy()
        
    dialog.protocol("WM_DELETE_WINDOW", on_close)
    root.wait_window(dialog)
    root.destroy()
    return result["success"]


def main():
    if not perform_license_check():
        sys.exit(0)
        
    root = tk.Tk()
    app = ImageProcessorApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()
