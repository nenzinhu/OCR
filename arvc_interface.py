import json
import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from arvc import TAB_ORDER, fill_portal
from arvc_ia import read_with_ai

BASE = Path(__file__).resolve().parent
NAVY = "#142D3A"
TEAL = "#076C64"
PAPER = "#EDF3F5"
INK = "#20343E"


class DespachoARVC:
    def __init__(self, window):
        self.window = window
        self.events = queue.Queue()
        self.entries = {}
        self.panels = {}
        self.status = tk.StringVar(value="Aguardando uma imagem.")
        self.filename = tk.StringVar(value="Nenhum arquivo selecionado")
        self.busy = False
        self.api_key = os.environ.get("GROQ_API_KEY", "").strip()
        self.image_ready = False
        self.closed = threading.Event()

        window.title("ARVC | Leitura e cadastro")
        window.geometry("920x680")
        window.minsize(740, 590)
        window.configure(background=PAPER)
        window.protocol("WM_DELETE_WINDOW", self.close)
        style = ttk.Style(window)
        style.theme_use("clam")
        style.configure("TLabel", font=("Segoe UI", 10))
        style.configure("TButton", font=("Segoe UI", 10), padding=(12, 8))
        style.configure("Accent.TButton", background=TEAL, foreground="white")
        style.map("Accent.TButton", background=[("disabled", "#CBD6D9"), ("active", "#07554F")],
                  foreground=[("disabled", "#40525B")])

        header = tk.Frame(window, bg=NAVY, padx=28, pady=24)
        header.pack(fill="x")
        tk.Label(header, text="Leitor de ARVC", bg=NAVY, fg="white", font=("Segoe UI", 26, "bold")).pack(anchor="w")
        tk.Label(header, text="Anexe o documento, revise os dados e preencha o portal", bg=NAVY, fg="#D3E2E8",
                 font=("Segoe UI", 11)).pack(anchor="w")

        body = tk.Frame(window, bg=PAPER, padx=24, pady=16)
        body.pack(fill="both", expand=True)
        upload = tk.Frame(body, bg="white", padx=20, pady=16, highlightthickness=1,
                          highlightbackground="#D1DFE4")
        upload.pack(fill="x", pady=(0, 16))
        self.attach = ttk.Button(upload, text="Anexar imagem", command=self.attach_image,
                                 style="Accent.TButton")
        self.attach.pack(side="right", padx=(12, 0))
        self.configure_key = ttk.Button(upload, text="Chave da API", command=self.request_key)
        self.configure_key.pack(side="right")
        self.import_button = ttk.Button(upload, text="Importar revisão", command=self.import_review)
        self.import_button.pack(side="right", padx=(0, 8))
        file_details = tk.Frame(upload, bg="white")
        file_details.pack(side="left", fill="x", expand=True)
        tk.Label(file_details, textvariable=self.filename, bg="white", fg=INK, anchor="w",
                 font=("Segoe UI", 13, "bold")).pack(fill="x")
        tk.Label(file_details, text="JPG, PNG ou WebP  •  Até 3 MiB", bg="white", fg="#43606E",
                 anchor="w", font=("Segoe UI", 10)).pack(fill="x", pady=(3, 0))
        self.tabs = ttk.Notebook(body)
        self.tabs.pack(fill="both", expand=True)
        short_labels = ("Retenção", "Veículo", "Proprietário", "Condutor", "Guinchamento", "Infrações")
        for tab, title in zip(TAB_ORDER, short_labels):
            panel = ttk.Frame(self.tabs, padding=15)
            self.tabs.add(panel, text=title)
            self.panels[tab] = panel
        source = ttk.Frame(self.tabs, padding=8)
        self.tabs.add(source, text="Texto da leitura")
        self.raw = tk.Text(source, wrap="word", state="disabled", font=("Consolas", 10))
        scroll = ttk.Scrollbar(source, command=self.raw.yview)
        scroll.pack(side="right", fill="y")
        self.raw.configure(yscrollcommand=scroll.set)
        self.raw.pack(fill="both", expand=True)
        for panel in self.panels.values():
            ttk.Label(panel, text="Anexe uma imagem para iniciar.").pack(anchor="w")

        footer = tk.Frame(body, bg=PAPER)
        footer.pack(fill="x", pady=(12, 0))
        self.send = ttk.Button(footer, text="Preencher no portal", style="Accent.TButton",
                               command=self.open_portal, state="disabled")
        self.send.pack(side="right")
        tk.Label(footer, textvariable=self.status, bg=PAPER, fg=INK, wraplength=490,
                 justify="left").pack(side="left")
        window.after(70, self.poll)

    def update_busy(self, busy):
        self.busy = busy
        self.configure_key.configure(state="disabled" if busy else "normal")
        self.import_button.configure(state="disabled" if busy else "normal")
        self.attach.configure(state="disabled" if busy else "normal")
        self.send.configure(state="normal" if self.image_ready and not busy else "disabled")

    def import_review(self):
        path = filedialog.askopenfilename(parent=self.window, filetypes=[("Revisão ARVC", "*.json")])
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            if not isinstance(data, dict) or not data or any(
                tab not in TAB_ORDER or not isinstance(values, dict)
                or any(not isinstance(value, str) for value in values.values())
                for tab, values in data.items()
            ):
                raise ValueError
        except (ValueError, OSError):
            messagebox.showerror("ARVC", "Escolha uma revisão JSON exportada pelo leitor web.", parent=self.window)
            return
        self.filename.set(Path(path).name)
        self.show_result("", data)
        self.image_ready = True
        self.update_busy(False)
        self.status.set("Revisão importada. Confira os campos antes de abrir o portal.")

    def request_key(self):
        key = simpledialog.askstring(
            "Chave da API da Groq",
            "Informe a chave da API. Ela será usada nesta sessão.",
            show="*", parent=self.window,
        )
        if key and key.strip():
            self.api_key = key.strip()
            self.status.set("Chave configurada para esta sessão.")

    def attach_image(self):
        path = filedialog.askopenfilename(parent=self.window, title="Anexar imagem do ARVC",
                                          filetypes=[("Imagens", "*.jpg *.jpeg *.png *.webp")])
        if not path:
            return
        if not self.api_key:
            self.request_key()
        if not self.api_key:
            return
        if not messagebox.askokcancel(
            "Ler imagem com IA", "Enviar a imagem selecionada à API da Groq para extrair os dados?",
            parent=self.window,
        ):
            return
        self.filename.set(Path(path).name)
        self.status.set("Lendo a imagem com IA…")
        self.image_ready = False
        self.show_result("", {})
        self.update_busy(True)
        self.run(lambda: self.events.put(("ocr", read_with_ai(Path(path), self.api_key))))

    def run(self, action):
        def worker():
            try:
                action()
            except Exception as error:
                self.events.put(("error", str(error)))
        threading.Thread(target=worker, daemon=True).start()

    def show_result(self, source, data):
        self.entries.clear()
        self.raw.configure(state="normal")
        self.raw.delete("1.0", "end")
        self.raw.insert("1.0", source)
        self.raw.configure(state="disabled")
        for tab, panel in self.panels.items():
            for widget in panel.winfo_children():
                widget.destroy()
            panel.columnconfigure(1, weight=1)
            fields = data.get(tab, {})
            self.entries[tab] = {}
            if not fields:
                ttk.Label(panel, text="Nenhum campo reconhecido nesta aba.").grid(sticky="w")
            for index, (name, value) in enumerate(fields.items()):
                ttk.Label(panel, text=name).grid(row=index, column=0, padx=(0, 12), pady=2, sticky="w")
                entry = ttk.Entry(panel)
                entry.insert(0, value)
                entry.grid(row=index, column=1, pady=2, sticky="ew")
                self.entries[tab][name] = entry

    def open_portal(self):
        data = {tab: {name: entry.get().strip() for name, entry in fields.items() if entry.get().strip()}
                for tab, fields in self.entries.items()}
        if not any(data.values()):
            self.status.set("Preencha pelo menos um campo para continuar.")
            return
        self.update_busy(True)
        self.status.set("Abrindo o navegador…")

        def ask(prompt):
            reply = queue.Queue(maxsize=1)
            self.events.put(("prompt", (prompt, reply)))
            while not self.closed.is_set():
                try:
                    return reply.get(timeout=0.2)
                except queue.Empty:
                    pass
            raise RuntimeError("Janela fechada.")

        def portal():
            fill_portal(data, BASE / "arvc-mapa.json", ask=ask,
                        report=lambda message: self.events.put(("report", message)))
            self.events.put(("done", None))

        self.run(portal)

    def poll(self):
        try:
            while True:
                action, payload = self.events.get_nowait()
                if action == "ocr":
                    source, data = payload
                    self.show_result(source, data)
                    self.image_ready = bool(data)
                    self.update_busy(False)
                    self.status.set("Confira os campos antes de abrir o portal." if data else
                                    "Nenhum campo reconhecido. Confira a aba Texto da leitura.")
                elif action == "prompt":
                    prompt, reply = payload
                    if "pular:" in prompt:
                        question = prompt.split(" e pressione Enter")[0] + ". Clique em OK aqui para continuar ou em Cancelar para pular."
                        answer = "" if messagebox.askokcancel("Preenchimento", question, parent=self.window) else "p"
                    elif "[s/N]" in prompt:
                        answer = "s" if messagebox.askyesno("Substituir valor?", prompt.split(" [")[0], parent=self.window) else ""
                    else:
                        messagebox.showinfo("Preenchimento", prompt.replace("pressione Enter aqui", "clique em OK aqui").replace("Pressione Enter aqui", "Clique em OK aqui"), parent=self.window)
                        answer = ""
                    reply.put(answer)
                elif action == "report":
                    messagebox.showinfo("Conferência no portal", payload, parent=self.window)
                elif action == "done":
                    self.update_busy(False)
                    self.status.set("Sessão de preenchimento encerrada.")
                elif action == "error":
                    self.update_busy(False)
                    self.status.set("A operação encontrou um erro.")
                    messagebox.showerror("ARVC", payload, parent=self.window)
        except queue.Empty:
            pass
        self.window.after(70, self.poll)

    def close(self):
        if self.busy:
            messagebox.showinfo("ARVC", "Aguarde a operação atual para fechar a janela.", parent=self.window)
            return
        self.closed.set()
        self.window.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    DespachoARVC(root)
    root.mainloop()
