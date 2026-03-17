import os
import sys
import time
import threading
from io import BytesIO
import requests  # type: ignore
from PIL import Image  # type: ignore
from dotenv import load_dotenv  # type: ignore

import tkinter as tk
from tkinter import filedialog, scrolledtext, messagebox, ttk

load_dotenv()

# Google APIs
from googleapiclient.discovery import build  # type: ignore
from googleapiclient.http import MediaIoBaseUpload  # type: ignore
from gsheet_handler import GSheetHandler

def get_base_dir():
    import license_utils  # type: ignore
    return license_utils.get_app_data_path()

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

TIMEOUT = 20
RETRIES = 2
OUT_DIR = "upscaled"

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

class UpscalerApp:
    def __init__(self, root):
        self.root = root
        try:
            self.root.title("Image Upscaler GUI")
            self.root.geometry("650x550")
            
            # Apply custom icon to the application window
            import license_utils
            base_path = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
            icon_path = os.path.join(base_path, 'icon.ico')
            if os.path.exists(icon_path):
                self.root.iconbitmap(icon_path)
        except Exception as e:
            print(f"[WARN] Could not load icon: {e}")
            pass
        
        self.drive_upload_available = True
        
        import typing
        self.log_text: typing.Any = None
        self.input_file_var: typing.Any = None
        self.drive_folder_var: typing.Any = None
        self.sheet_id_var: typing.Any = None
        self.worksheet_var: typing.Any = None
        self.target_res_var: typing.Any = None
        self.start_btn: typing.Any = None
        
        self.json_key_path_var: typing.Any = None
        self.json_dropdown: typing.Any = None
        self.auth_btn: typing.Any = None
        self.gsheet_frame: typing.Any = None
        
        # UI Elements
        self.create_widgets()
        
        # Redirect stdout
        import sys
        if not hasattr(sys.stdout, 'outputs'):
            class MultiplexRedirect:
                outputs = []
                def write(self, string):
                    import tkinter as tk
                    for out in self.outputs:
                        try:
                            out.insert(tk.END, string)
                            out.see(tk.END)
                            out.update_idletasks()
                        except: pass
                def flush(self): pass
            sys.stdout = MultiplexRedirect()
        sys.stdout.outputs.append(self.log_text)  # type: ignore
        
    def create_widgets(self):
        main_frame = tk.Frame(self.root, padx=15, pady=15)
        main_frame.pack(fill=tk.BOTH, expand=True)

        config_frame = tk.LabelFrame(main_frame, text="Configuration", padx=10, pady=10)
        config_frame.pack(fill=tk.X, pady=(0, 10))
        
        # Input File
        tk.Label(config_frame, text="Input File:").grid(row=0, column=0, sticky='e', pady=5)
        self.input_file_var = tk.StringVar(value="inputimage.txt")
        tk.Entry(config_frame, textvariable=self.input_file_var, width=50).grid(row=0, column=1, padx=5, pady=5)
        tk.Button(config_frame, text="Browse", command=self.browse_file).grid(row=0, column=2, padx=5, pady=5)
        
        # Google Sheet Configuration
        self.gsheet_frame = tk.Frame(config_frame)
        self.gsheet_frame.grid(row=1, column=0, columnspan=3, sticky="we", pady=5)
        
        # JSON Key and Account Selector on ONE line
        gs_auth_frame = tk.Frame(self.gsheet_frame)
        gs_auth_frame.pack(fill=tk.X, pady=2)
        
        self.json_key_path_var = tk.StringVar(value="Not installed")
        tk.Label(gs_auth_frame, text="Auth JSON:", width=10).pack(side=tk.LEFT)
        tk.Entry(gs_auth_frame, textvariable=self.json_key_path_var, width=25, state="readonly").pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(gs_auth_frame, text="Install", width=7, command=self._install_json_key).pack(side=tk.LEFT, padx=(2, 10))
        
        self._check_credentials_loaded()
            
        tk.Label(gs_auth_frame, text="Account:", width=8).pack(side=tk.LEFT)
        self.json_dropdown = ttk.Combobox(gs_auth_frame, width=25, state="readonly")
        self.json_dropdown.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.json_dropdown.bind("<<ComboboxSelected>>", self._on_account_selected)
        
        ttk.Button(gs_auth_frame, text="Add Account", width=12, command=self._add_new_account).pack(side=tk.LEFT, padx=(5, 2))
        self.auth_btn = ttk.Button(gs_auth_frame, text="Authenticated ✓", width=15, state=tk.DISABLED)
        self.auth_btn.pack(side=tk.LEFT)
        
        self._refresh_account_list()

        # Sheet ID, Worksheet Name, and Target Res
        gs_sheet_frame = tk.Frame(self.gsheet_frame)
        gs_sheet_frame.pack(fill=tk.X, pady=2)
        
        tk.Label(gs_sheet_frame, text="Sheet ID:").pack(side=tk.LEFT, padx=(0, 5))
        self.sheet_id_var = tk.StringVar(value=os.getenv("GOOGLE_SHEET_ID", ""))
        tk.Entry(gs_sheet_frame, textvariable=self.sheet_id_var, width=25).pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        tk.Label(gs_sheet_frame, text="Worksheet:").pack(side=tk.LEFT, padx=(10, 5))
        self.worksheet_var = tk.StringVar(value="Sheet1.cm")
        tk.Entry(gs_sheet_frame, textvariable=self.worksheet_var, width=15).pack(side=tk.LEFT)
        
        tk.Label(gs_sheet_frame, text="Target Res (px):").pack(side=tk.LEFT, padx=(10, 5))
        self.target_res_var = tk.IntVar(value=1500)
        tk.Entry(gs_sheet_frame, textvariable=self.target_res_var, width=8).pack(side=tk.LEFT)
        
        # Action Frame
        action_frame = tk.Frame(main_frame)
        action_frame.pack(fill=tk.X, pady=5)
        
        self.start_btn = tk.Button(action_frame, text="Start Processing", command=self.start_processing, bg="#4CAF50", fg="white", font=("Arial", 10, "bold"), padx=10, pady=5)
        self.start_btn.pack()
        
        # Logging Text Area
        log_frame = tk.LabelFrame(main_frame, text="Logs", padx=5, pady=5)
        log_frame.pack(fill=tk.BOTH, expand=True)
        
        self.log_text = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD, state='normal')
        self.log_text.pack(fill=tk.BOTH, expand=True)

    def browse_file(self):
        filename = filedialog.askopenfilename(title="Select Input File", filetypes=(("Text files", "*.txt"), ("All files", "*.*")))
        if filename:
            self.input_file_var.set(filename)
            
    def _install_json_key(self):
        filename = filedialog.askopenfilename(
            title="Select Auth JSON (Service or Client)",
            filetypes=(("JSON Files", "*.json"), ("All Files", "*.*"))
        )
        if filename:
            try:
                import shutil
                target_path = os.path.join(get_base_dir(), "credentials.json")
                
                if os.path.exists(target_path):
                    if not messagebox.askyesno("Confirm Overwrite", "credentials.json already exists. Do you want to overwrite it with the new file?"):
                        return
                        
                shutil.copyfile(filename, target_path)
                self._check_credentials_loaded()
                messagebox.showinfo("Success", "Credentials installed successfully.")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to install credentials: {e}")

    def _check_credentials_loaded(self):
        target_path = os.path.join(get_base_dir(), "credentials.json")
        if os.path.exists(target_path):
            self.json_key_path_var.set("Credentials loaded")
        else:
            self.json_key_path_var.set("Not installed")

    def _refresh_account_list(self):
        accounts = []
        token_dir = os.path.join(get_base_dir(), 'tokens')
        if os.path.exists(token_dir):
            for file in os.listdir(token_dir):
                if file.endswith(".json"):
                    accounts.append(file)
        
        self.json_dropdown['values'] = accounts
        if accounts:
            if self.json_dropdown.get() not in accounts:
                self.json_dropdown.current(0)
                self._on_account_selected()
            else:
                self._on_account_selected()
        else:
            self.json_dropdown.set("")
            self.auth_btn.config(text="No Account", state=tk.DISABLED)

    def _on_account_selected(self, event=None):
        selected_file = self.json_dropdown.get()
        if not selected_file:
            return
            
        token_path = os.path.join(get_base_dir(), "tokens", selected_file)
        if os.path.exists(token_path):
            self.auth_btn.config(text="Authenticated ✓", state=tk.DISABLED)
        else:
            self.auth_btn.config(text="Error", state=tk.DISABLED)

    def _add_new_account(self):
        json_key = os.path.join(get_base_dir(), "credentials.json")
        if not os.path.exists(json_key):
             messagebox.showerror("Error", "credentials.json is missing. Please click Install first.")
             return
             
        json_key = os.path.abspath(json_key)
        
        try:
            # Run the OAuth flow to generate the token (name is auto-detected)
            handler = GSheetHandler(json_key, token_name=None)
            new_filename = handler.token_name
            
            self._refresh_account_list()
            self.json_dropdown.set(new_filename)
            self._on_account_selected()
            messagebox.showinfo("Success", f"Account added as {new_filename}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to authenticate account: {e}")

    def download_image(self, url):
        for attempt in range(1, RETRIES + 1):
            try:
                resp = requests.get(url, timeout=TIMEOUT, stream=True)
                resp.raise_for_status()
                return resp.content
            except Exception as e:
                if attempt == RETRIES:
                    raise e
                time.sleep(1)
        raise RuntimeError("unreachable")

    def upscale_image_bytes(self, img_bytes, target):
        with Image.open(BytesIO(img_bytes)) as im:
            im = im.convert("RGB")
            w, h = im.size
            if w >= h:
                new_w = target
                new_h = int(round((target / w) * h))
            else:
                new_h = target
                new_w = int(round((target / h) * w))
            if new_w == w and new_h == h:
                out = im.copy()
            else:
                out = im.resize((new_w, new_h), resample=Image.LANCZOS)
            buf = BytesIO()
            out.save(buf, format="JPEG", quality=92)
            buf.seek(0)
            return buf, (new_w, new_h)

    def process_line(self, line, line_idx, sheet, target_res):
        urls = [u.strip() for u in line.split("|") if u.strip()]
        if not urls:
            return [], 0
        
        out_sub = os.path.join(OUT_DIR, f"line_{line_idx}")
        os.makedirs(out_sub, exist_ok=True)
        
        upscaled_urls = []
        count = 0
        
        for i, url in enumerate(urls, start=1):
            try:
                print(f"[INFO] Line {line_idx} - downloading image {i}: {url}")
                b = self.download_image(url)
                img_buf, size = self.upscale_image_bytes(b, target=target_res)
                
                out_path = os.path.join(out_sub, f"{i}_{target_res}.jpg")
                with open(out_path, "wb") as f:
                    f.write(img_buf.getvalue())
                print(f"  [OK] Saved locally: {out_path} ({size[0]}x{size[1]})")
                
                upscaled_urls.append(out_path)
                count += 1
            except Exception as e:
                print(f"  [ERROR] Failed image {i} ({url}): {e}")
                upscaled_urls.append("")

        if upscaled_urls:
            upscaled_str = "|".join([u for u in upscaled_urls if u])
            try:
                headers = sheet.row_values(5)
                col_idx = None
                for idx, h in enumerate(headers, 1):
                    if h.strip() == "Upscaled Images":
                        col_idx = idx
                        break
                
                if col_idx is None:
                    col_idx = len(headers) + 1
                    headers.append("Upscaled Images")
                    # Fixed BUG: Use update_cell to write the header instead of append_row which goes to EOF
                    sheet.update_cell(5, col_idx, "Upscaled Images")
                
                row_num = 5 + line_idx
                sheet.update_cell(row_num, col_idx, upscaled_str)
                print(f"  [OK] Updated Sheet row {row_num} with upscaled image paths")
            except Exception as e:
                print(f"  [WARN] Failed to update sheet: {e}")
        
        return upscaled_urls, count

    def run_process(self):
        input_file = self.input_file_var.get().strip()
        sheet_id = self.sheet_id_var.get().strip()
        worksheet_name = self.worksheet_var.get().strip()
        try:
            target_res = self.target_res_var.get()
        except tk.TclError:
            print("[ERROR] Target resolution must be an integer.")
            self.root.after(0, lambda: self.start_btn.config(state=tk.NORMAL))
            return

        if not os.path.exists(input_file):
            print(f"[ERROR] Input file not found: {input_file}")
            self.root.after(0, lambda: self.start_btn.config(state=tk.NORMAL))
            return
            
        if not sheet_id:
            print("[ERROR] Google Sheet ID is missing!")
            self.root.after(0, lambda: self.start_btn.config(state=tk.NORMAL))
            return

        os.makedirs(OUT_DIR, exist_ok=True)
        
        # Initialize Google Sheet Handler
        json_key_file = os.path.join(get_base_dir(), "credentials.json")
        token_name = self.json_dropdown.get().strip() if self.json_dropdown else None
        
        if not token_name or token_name == "Not installed":
            print("[ERROR] Please Add and Select a Google Account first.")
            self.root.after(0, lambda: self.start_btn.config(state=tk.NORMAL))
            return
            
        print(f"[INFO] Starting process with target resolution {target_res}px...")
        print("[INFO] Connecting to Google Services...")
        
        try:
            handler = GSheetHandler(json_key_file, token_name=token_name)
        except Exception as e:
            print(f"[ERROR] Authentication Failed: {e}")
            self.root.after(0, lambda: self.start_btn.config(state=tk.NORMAL))
            return
             
        try:
            sheet = handler.get_sheet(sheet_id, worksheet_name)
            print("[OK] Connected to Sheets")
        except Exception as e:
            print(f"[ERROR] Failed to connect to Google Sheets: {e}")
            self.root.after(0, lambda: self.start_btn.config(state=tk.NORMAL))
            return

        total = 0
        try:
            with open(input_file, "r", encoding="utf-8") as f:
                for idx, line in enumerate(f, start=1):
                    line = line.strip()
                    if not line:
                        continue
                    _, got = self.process_line(line, idx, sheet, target_res)
                    total += got
            
            print(f"\nDone. Total images processed: {total}")
            print(f"Upscaled images saved in: {OUT_DIR}")
        except Exception as e:
            print(f"[ERROR] An unexpected error occurred: {e}")
            
        self.root.after(0, lambda: self.start_btn.config(state=tk.NORMAL))

    def start_processing(self):
        self.start_btn.config(state=tk.DISABLED)
        self.log_text.delete(1.0, tk.END)
        t = threading.Thread(target=self.run_process, daemon=True)
        t.start()

def main():
    root = tk.Tk()
    app = UpscalerApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()
