import socket
import sqlite3
import threading
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, scrolledtext, ttk


HOST = "127.0.0.1"
PORT = 5000
BUFFER_SIZE = 1024
ENCODING = "utf-8"
HISTORY_DB = "chat_history.db"
USERLIST_PREFIX = "::USERLIST::"

THEMES = {
    "Ocean": {
        "bg": "#eef6fb",
        "panel": "#ffffff",
        "text_bg": "#f8fbfd",
        "text_fg": "#16232e",
        "own": "#0077b6",
        "other": "#2f3e46",
        "system": "#6c757d",
        "accent": "#00a6a6",
    },
    "Midnight": {
        "bg": "#111827",
        "panel": "#1f2937",
        "text_bg": "#0f172a",
        "text_fg": "#e5e7eb",
        "own": "#38bdf8",
        "other": "#f8fafc",
        "system": "#9ca3af",
        "accent": "#22c55e",
    },
    "Rose": {
        "bg": "#fff1f2",
        "panel": "#ffffff",
        "text_bg": "#fff7f7",
        "text_fg": "#3f1d2b",
        "own": "#e11d48",
        "other": "#374151",
        "system": "#7c2d12",
        "accent": "#f97316",
    },
}

FONT_SIZES = ("10", "11", "12", "13", "14", "16", "18")


class ChatHistory:
    def __init__(self, db_path=HISTORY_DB):
        self.db_path = db_path
        self.lock = threading.Lock()
        self.setup()

    def setup(self):
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    sender TEXT NOT NULL,
                    target TEXT NOT NULL,
                    message TEXT NOT NULL,
                    is_private INTEGER NOT NULL
                )
                """
            )

    def save_message(self, sender, target, message, is_private=False):
        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self.lock:
            with sqlite3.connect(self.db_path) as connection:
                connection.execute(
                    """
                    INSERT INTO messages (created_at, sender, target, message, is_private)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (created_at, sender, target, message, int(is_private)),
                )

    def recent_messages(self, limit=100):
        with self.lock:
            with sqlite3.connect(self.db_path) as connection:
                rows = connection.execute(
                    """
                    SELECT created_at, sender, target, message, is_private
                    FROM messages
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        return list(reversed(rows))


class ChatServer:
    def __init__(self, on_log, on_users):
        self.on_log = on_log
        self.on_users = on_users
        self.server_socket = None
        self.clients = {}
        self.clients_lock = threading.Lock()
        self.history = ChatHistory()
        self.running = False

    def start(self, host, port):
        if self.running:
            return

        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind((host, port))
        self.server_socket.listen()
        self.running = True

        self.on_log(f"Server aktif di {host}:{port}")
        threading.Thread(target=self.accept_clients, daemon=True).start()

    def stop(self):
        if not self.running:
            return

        self.running = False
        self.on_log("Server dimatikan.")

        with self.clients_lock:
            client_sockets = list(self.clients.keys())

        for client_socket in client_sockets:
            self.send_message(client_socket, "\n[SERVER] Server dimatikan.\n")
            self.remove_client(client_socket)

        if self.server_socket:
            try:
                self.server_socket.close()
            except OSError:
                pass
            self.server_socket = None

        self.on_users([])

    def accept_clients(self):
        while self.running:
            try:
                client_socket, address = self.server_socket.accept()
            except OSError:
                break

            threading.Thread(
                target=self.handle_client,
                args=(client_socket, address),
                daemon=True,
            ).start()

    def handle_client(self, client_socket, address):
        self.on_log(f"Client masuk dari {address[0]}:{address[1]}")
        self.send_message(client_socket, "Selamat datang di server chat!\n")
        self.send_message(client_socket, "Masukkan username: ")

        username = self.receive_line(client_socket)
        if not username:
            client_socket.close()
            return

        with self.clients_lock:
            self.clients[client_socket] = username

        self.refresh_users()
        self.send_message(client_socket, "\nKamu sudah masuk. Ketik /quit untuk keluar.\n")
        self.broadcast(f"\n[SERVER] {username} masuk ke chat.\n", client_socket)
        self.on_log(f"{username} bergabung.")

        try:
            while self.running:
                message = self.receive_line(client_socket)
                if not message or message.lower() == "/quit":
                    break

                if message.startswith("/pm "):
                    self.handle_private_message(client_socket, username, message)
                else:
                    self.history.save_message(username, "All", message)
                    formatted_message = f"{username}: {message}\n"
                    self.on_log(formatted_message.strip())
                    self.broadcast(formatted_message, client_socket)
        except ConnectionResetError:
            pass
        finally:
            self.remove_client(client_socket)

    def receive_line(self, client_socket):
        data = client_socket.recv(BUFFER_SIZE)
        if not data:
            return ""
        return data.decode(ENCODING, errors="replace").strip()

    def send_message(self, client_socket, message):
        try:
            client_socket.sendall(message.encode(ENCODING))
        except OSError:
            self.remove_client(client_socket)

    def broadcast(self, message, sender_socket=None):
        with self.clients_lock:
            client_sockets = list(self.clients.keys())

        for client_socket in client_sockets:
            if client_socket != sender_socket:
                self.send_message(client_socket, message)

    def handle_private_message(self, sender_socket, sender_name, raw_message):
        parts = raw_message.split(" ", 2)
        if len(parts) < 3:
            self.send_message(sender_socket, "[SERVER] Format private chat: /pm username pesan\n")
            return

        target_name = parts[1].strip()
        private_message = parts[2].strip()
        if not target_name or not private_message:
            self.send_message(sender_socket, "[SERVER] Target dan pesan private tidak boleh kosong.\n")
            return

        target_socket = self.find_client_socket(target_name)
        if not target_socket:
            self.send_message(sender_socket, f"[SERVER] User {target_name} tidak online.\n")
            return

        self.history.save_message(sender_name, target_name, private_message, is_private=True)
        self.send_message(target_socket, f"[PRIVATE dari {sender_name}] {private_message}\n")
        self.send_message(sender_socket, f"[PRIVATE ke {target_name}] {private_message}\n")
        self.on_log(f"[PRIVATE] {sender_name} -> {target_name}: {private_message}")

    def find_client_socket(self, username):
        with self.clients_lock:
            for client_socket, client_name in self.clients.items():
                if client_name == username:
                    return client_socket
        return None

    def remove_client(self, client_socket):
        with self.clients_lock:
            username = self.clients.pop(client_socket, None)

        try:
            client_socket.close()
        except OSError:
            pass

        if username:
            self.on_log(f"{username} keluar.")
            self.broadcast(f"\n[SERVER] {username} keluar dari chat.\n")
            self.refresh_users()

    def refresh_users(self):
        with self.clients_lock:
            users = list(self.clients.values())
        self.on_users(users)
        self.broadcast_user_list(users)

    def broadcast_user_list(self, users):
        user_text = "|".join(users)
        self.broadcast(f"{USERLIST_PREFIX}{user_text}\n")


class MasterChatGui:
    def __init__(self):
        self.window = tk.Tk()
        self.window.title("Master GUI TCP Chat")
        self.window.geometry("900x560")
        self.window.minsize(760, 480)

        self.server = ChatServer(self.add_server_log, self.update_user_list)
        self.client_socket = None
        self.client_connected = False
        self.theme_name = tk.StringVar(value="Ocean")
        self.font_size = tk.StringVar(value="12")
        self.target_user = tk.StringVar(value="All")
        self.online_users = []
        self.style = ttk.Style()

        self.build_ui()
        self.apply_theme()
        self.window.protocol("WM_DELETE_WINDOW", self.close_app)

    def build_ui(self):
        root = ttk.Frame(self.window, padding=12)
        root.pack(fill="both", expand=True)

        root.columnconfigure(0, weight=1)
        root.columnconfigure(1, weight=2)
        root.rowconfigure(0, weight=1)

        self.build_server_panel(root)
        self.build_client_panel(root)

    def build_server_panel(self, parent):
        panel = ttk.LabelFrame(parent, text="Server Control", padding=10)
        panel.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        panel.columnconfigure(1, weight=1)
        panel.rowconfigure(4, weight=1)

        ttk.Label(panel, text="Host").grid(row=0, column=0, sticky="w")
        self.server_host = ttk.Entry(panel)
        self.server_host.insert(0, HOST)
        self.server_host.grid(row=0, column=1, sticky="ew", pady=3)

        ttk.Label(panel, text="Port").grid(row=1, column=0, sticky="w")
        self.server_port = ttk.Entry(panel)
        self.server_port.insert(0, str(PORT))
        self.server_port.grid(row=1, column=1, sticky="ew", pady=3)

        buttons = ttk.Frame(panel)
        buttons.grid(row=2, column=0, columnspan=2, sticky="ew", pady=8)
        buttons.columnconfigure(0, weight=1)
        buttons.columnconfigure(1, weight=1)

        self.start_button = ttk.Button(buttons, text="Start Server", command=self.start_server)
        self.start_button.grid(row=0, column=0, sticky="ew", padx=(0, 4))

        self.stop_button = ttk.Button(buttons, text="Stop Server", command=self.stop_server)
        self.stop_button.grid(row=0, column=1, sticky="ew", padx=(4, 0))

        ttk.Label(panel, text="User Online").grid(row=3, column=0, columnspan=2, sticky="w")
        self.user_list = tk.Listbox(panel, height=5)
        self.user_list.grid(row=4, column=0, columnspan=2, sticky="nsew", pady=(3, 8))

        ttk.Label(panel, text="Log Server").grid(row=5, column=0, columnspan=2, sticky="w")
        self.server_log = scrolledtext.ScrolledText(panel, height=8, state="disabled")
        self.server_log.grid(row=6, column=0, columnspan=2, sticky="nsew", pady=(3, 0))

    def build_client_panel(self, parent):
        panel = ttk.LabelFrame(parent, text="Client Chat", padding=10)
        panel.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        panel.columnconfigure(1, weight=1)
        panel.rowconfigure(6, weight=1)

        ttk.Label(panel, text="Host").grid(row=0, column=0, sticky="w")
        self.client_host = ttk.Entry(panel)
        self.client_host.insert(0, HOST)
        self.client_host.grid(row=0, column=1, sticky="ew", padx=(8, 0), pady=3)

        ttk.Label(panel, text="Port").grid(row=1, column=0, sticky="w")
        self.client_port = ttk.Entry(panel)
        self.client_port.insert(0, str(PORT))
        self.client_port.grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=3)

        ttk.Label(panel, text="Username").grid(row=2, column=0, sticky="w")
        self.username = ttk.Entry(panel)
        self.username.insert(0, "Dhika")
        self.username.grid(row=2, column=1, sticky="ew", padx=(8, 0), pady=3)

        ttk.Label(panel, text="Send To").grid(row=3, column=0, sticky="w")
        self.target_box = ttk.Combobox(
            panel,
            textvariable=self.target_user,
            values=["All"],
            state="readonly",
        )
        self.target_box.grid(row=3, column=1, sticky="ew", padx=(8, 0), pady=3)

        buttons = ttk.Frame(panel)
        buttons.grid(row=4, column=0, columnspan=2, sticky="ew", pady=8)
        buttons.columnconfigure(0, weight=1)
        buttons.columnconfigure(1, weight=1)

        self.connect_button = ttk.Button(buttons, text="Connect", command=self.connect_client)
        self.connect_button.grid(row=0, column=0, sticky="ew", padx=(0, 4))

        self.disconnect_button = ttk.Button(buttons, text="Disconnect", command=self.disconnect_client)
        self.disconnect_button.grid(row=0, column=1, sticky="ew", padx=(4, 0))

        self.build_customize_panel(panel)

        self.chat_area = scrolledtext.ScrolledText(panel, state="disabled")
        self.chat_area.grid(row=6, column=0, columnspan=2, sticky="nsew", pady=(0, 8))

        input_row = ttk.Frame(panel)
        input_row.grid(row=7, column=0, columnspan=2, sticky="ew")
        input_row.columnconfigure(0, weight=1)

        self.message_input = ttk.Entry(input_row)
        self.message_input.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.message_input.bind("<Return>", lambda event: self.send_client_message())

        self.send_button = ttk.Button(input_row, text="Send", command=self.send_client_message)
        self.send_button.grid(row=0, column=1)

        self.status_label = ttk.Label(panel, text="Status: belum connect")
        self.status_label.grid(row=8, column=0, columnspan=2, sticky="w", pady=(8, 0))

    def build_customize_panel(self, parent):
        customize = ttk.LabelFrame(parent, text="Customize", padding=8)
        customize.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        customize.columnconfigure(1, weight=1)
        customize.columnconfigure(3, weight=1)

        ttk.Label(customize, text="Theme").grid(row=0, column=0, sticky="w")
        theme_box = ttk.Combobox(
            customize,
            textvariable=self.theme_name,
            values=list(THEMES.keys()),
            state="readonly",
            width=12,
        )
        theme_box.grid(row=0, column=1, sticky="ew", padx=(6, 12))
        theme_box.bind("<<ComboboxSelected>>", lambda event: self.apply_theme())

        ttk.Label(customize, text="Font").grid(row=0, column=2, sticky="w")
        font_box = ttk.Combobox(
            customize,
            textvariable=self.font_size,
            values=FONT_SIZES,
            state="readonly",
            width=6,
        )
        font_box.grid(row=0, column=3, sticky="ew", padx=(6, 12))
        font_box.bind("<<ComboboxSelected>>", lambda event: self.apply_theme())

        clear_button = ttk.Button(customize, text="Clear Chat", command=self.clear_chat)
        clear_button.grid(row=0, column=4, sticky="ew", padx=(0, 6))

        history_button = ttk.Button(customize, text="Load History", command=self.load_history)
        history_button.grid(row=0, column=5, sticky="ew")

    def start_server(self):
        host = self.server_host.get().strip()
        port = self.get_port(self.server_port.get())
        if port is None:
            return

        try:
            self.server.start(host, port)
        except OSError as error:
            messagebox.showerror("Server Error", f"Gagal start server:\n{error}")

    def stop_server(self):
        self.server.stop()

    def connect_client(self):
        if self.client_connected:
            return

        host = self.client_host.get().strip()
        port = self.get_port(self.client_port.get())
        username = self.username.get().strip()

        if port is None:
            return
        if not username:
            messagebox.showwarning("Username kosong", "Isi username dulu.")
            return

        try:
            self.client_socket = socket.create_connection((host, port), timeout=5)
            self.client_socket.settimeout(None)
            self.client_connected = True
            self.status_label.config(text=f"Status: connect sebagai {username}")
            self.add_chat_message("[CLIENT] Terhubung ke server.", "system")

            threading.Thread(target=self.receive_client_messages, daemon=True).start()
            self.client_socket.sendall(f"{username}\n".encode(ENCODING))
        except OSError as error:
            self.client_socket = None
            self.client_connected = False
            messagebox.showerror("Client Error", f"Gagal connect:\n{error}")

    def disconnect_client(self):
        if not self.client_socket:
            return

        try:
            self.client_socket.sendall(b"/quit\n")
        except OSError:
            pass

        try:
            self.client_socket.close()
        except OSError:
            pass

        self.client_socket = None
        self.client_connected = False
        self.status_label.config(text="Status: belum connect")
        self.add_chat_message("[CLIENT] Disconnect.", "system")

    def receive_client_messages(self):
        while self.client_connected and self.client_socket:
            try:
                data = self.client_socket.recv(BUFFER_SIZE)
                if not data:
                    break

                message = data.decode(ENCODING, errors="replace")
                self.handle_incoming_client_text(message)
            except OSError:
                break

        self.window.after(0, self.mark_client_disconnected)

    def send_client_message(self):
        message = self.message_input.get().strip()
        if not message:
            return

        if not self.client_connected or not self.client_socket:
            messagebox.showwarning("Belum connect", "Connect ke server dulu.")
            return

        try:
            target = self.target_user.get()
            if target and target != "All":
                outgoing_message = f"/pm {target} {message}"
                display_message = None
            else:
                outgoing_message = message
                display_message = f"Kamu: {message}"

            self.client_socket.sendall(f"{outgoing_message}\n".encode(ENCODING))
            if display_message:
                self.add_chat_message(display_message, "own")
            self.message_input.delete(0, tk.END)
        except OSError:
            self.mark_client_disconnected()

    def handle_incoming_client_text(self, text):
        for line in text.splitlines():
            if line.startswith(USERLIST_PREFIX):
                user_text = line.removeprefix(USERLIST_PREFIX)
                users = [user for user in user_text.split("|") if user]
                self.window.after(0, self.update_target_users, users)
            elif line:
                tag = "system" if line.startswith("[SERVER]") or line.startswith("[CLIENT]") else "other"
                self.add_chat_message(line, tag)

    def update_target_users(self, users):
        current_username = self.username.get().strip()
        targets = ["All"]
        targets.extend(user for user in users if user != current_username)
        self.online_users = targets
        self.target_box["values"] = targets
        if self.target_user.get() not in targets:
            self.target_user.set("All")

    def mark_client_disconnected(self):
        if self.client_socket:
            try:
                self.client_socket.close()
            except OSError:
                pass

        self.client_socket = None
        self.client_connected = False
        self.status_label.config(text="Status: belum connect")

    def get_port(self, value):
        try:
            port = int(value)
        except ValueError:
            messagebox.showwarning("Port salah", "Port harus berupa angka.")
            return None

        if not 1 <= port <= 65535:
            messagebox.showwarning("Port salah", "Port harus antara 1 sampai 65535.")
            return None

        return port

    def add_server_log(self, message):
        self.window.after(0, self.append_text, self.server_log, message)

    def add_chat_message(self, message, tag="other"):
        self.window.after(0, self.append_text, self.chat_area, message, tag)

    def append_text(self, widget, message, tag=None):
        widget.config(state="normal")
        if tag:
            widget.insert(tk.END, f"{message}\n", tag)
        else:
            widget.insert(tk.END, f"{message}\n")
        widget.see(tk.END)
        widget.config(state="disabled")

    def clear_chat(self):
        self.chat_area.config(state="normal")
        self.chat_area.delete("1.0", tk.END)
        self.chat_area.config(state="disabled")

    def load_history(self):
        history = ChatHistory()
        rows = history.recent_messages()
        self.clear_chat()

        if not rows:
            self.add_chat_message("[HISTORY] Belum ada riwayat chat.", "system")
            return

        self.add_chat_message("[HISTORY] Menampilkan 100 pesan terakhir.", "system")
        for created_at, sender, target, message, is_private in rows:
            if is_private:
                text = f"{created_at} [PRIVATE] {sender} -> {target}: {message}"
            else:
                text = f"{created_at} {sender}: {message}"
            self.add_chat_message(text, "system" if is_private else "other")

    def apply_theme(self):
        theme = THEMES[self.theme_name.get()]
        font = ("Arial", int(self.font_size.get()))
        mono_font = ("Consolas", int(self.font_size.get()))

        self.window.configure(bg=theme["bg"])
        self.style.theme_use("clam")
        self.style.configure("TFrame", background=theme["bg"])
        self.style.configure("TLabelframe", background=theme["bg"])
        self.style.configure("TLabelframe.Label", background=theme["bg"], foreground=theme["text_fg"])
        self.style.configure("TLabel", background=theme["bg"], foreground=theme["text_fg"], font=font)
        self.style.configure("TButton", font=font, padding=6)
        self.style.configure("TEntry", fieldbackground=theme["panel"], foreground=theme["text_fg"], font=font)
        self.style.configure("TCombobox", fieldbackground=theme["panel"], foreground=theme["text_fg"], font=font)

        for text_widget in (self.chat_area, self.server_log):
            text_widget.configure(
                bg=theme["text_bg"],
                fg=theme["text_fg"],
                insertbackground=theme["text_fg"],
                font=mono_font,
                relief="flat",
                padx=10,
                pady=10,
            )

        self.chat_area.tag_configure("own", foreground=theme["own"], spacing1=5, spacing3=5)
        self.chat_area.tag_configure("other", foreground=theme["other"], spacing1=5, spacing3=5)
        self.chat_area.tag_configure("system", foreground=theme["system"], spacing1=5, spacing3=5)
        self.server_log.tag_configure("system", foreground=theme["system"])

        self.user_list.configure(
            bg=theme["text_bg"],
            fg=theme["text_fg"],
            selectbackground=theme["accent"],
            selectforeground="#ffffff",
            font=font,
            relief="flat",
        )

    def update_user_list(self, users):
        self.window.after(0, self.replace_user_list, users)

    def replace_user_list(self, users):
        self.user_list.delete(0, tk.END)
        for username in users:
            self.user_list.insert(tk.END, username)

    def close_app(self):
        self.disconnect_client()
        self.server.stop()
        self.window.destroy()

    def run(self):
        self.window.mainloop()


if __name__ == "__main__":
    MasterChatGui().run()
