import tkinter as tk
from tkinter import ttk, messagebox
import license_utils # type: ignore

class KeygenApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Image Processor Keygen")
        self.geometry("400x250")
        
        # Machine Code Input (Request Code)
        tk.Label(self, text="Paste Machine Code (Request Code):").pack(pady=(10, 0))
        self.machine_code_entry = tk.Entry(self, width=50)
        self.machine_code_entry.pack(pady=5)
        
        # Generate Button
        self.generate_btn = tk.Button(self, text="Generate License", command=self.generate_key)
        self.generate_btn.pack(pady=10)
        
        # License Key Output
        tk.Label(self, text="License Key:").pack(pady=(10, 0))
        self.license_key_entry = tk.Entry(self, width=50)
        self.license_key_entry.pack(pady=5)
        
        # Copy Button
        self.copy_btn = tk.Button(self, text="Copy Key", command=self.copy_key)
        self.copy_btn.pack(pady=10)

    def generate_key(self):
        code = self.machine_code_entry.get().strip()
        if not code:
            messagebox.showwarning("Warning", "Please enter a Machine Code first.")
            return

        key = license_utils.generate_license_key(code)
        self.license_key_entry.delete(0, tk.END)
        self.license_key_entry.insert(0, key)

    def copy_key(self):
        key = self.license_key_entry.get()
        if key:
            self.clipboard_clear()
            self.clipboard_append(key)
            messagebox.showinfo("Copied", "License Key copied to clipboard!")

if __name__ == "__main__":
    app = KeygenApp()
    app.mainloop()
