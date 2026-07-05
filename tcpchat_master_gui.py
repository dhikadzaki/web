import hashlib
import re
import secrets
import socket
import sqlite3
import threading
import time
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, scrolledtext, ttk


SERVER_HOST = "0.0.0.0"
CLIENT_HOST = "127.0.0.1"
PORT = 5000
BUFFER_SIZE = 1024
ENCODING = "utf-8"
HISTORY_DB = "chat_history.db"

USERLIST_PREFIX = "::USERLIST::"
TYPING_PREFIX = "::TYPING::"
LAG_PREFIX = "::LAG::"

TYPING_STOP_DELAY_MS = 1500
LAG_UPDATE_INTERVAL_SECONDS = 3
MAX_MESSAGE_LENGTH = 1000
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{2,24}$")
COMMAND_WHITELIST = {"/help", "/lag", "/msg", "/pm", "/quit", "/typing"}

THEMES = {
    "Midnight": {
        "bg": "#0b1120",
        "panel": "#111827",
        "text_bg": "#0f172a",
        "text_fg": "#f8fafc",
        "own": "#2dd4bf",
        "other": "#e5e7eb",
        "system": "#94a3b8",
        "accent": "#38bdf8",
    },
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


class SocketLineReader:
    def __init__(self, client_socket):
        self.client_socket = client_socket
        self.buffer = ""

    def read_line(self):
        while "\n" not in self.buffer:
            data = self.client_socket.recv(BUFFER_SIZE)
            if not data:
                line = self.buffer.strip()
                self.buffer = ""
                return line
            self.buffer += data.decode(ENCODING, errors="replace")

        line, self.buffer = self.buffer.split("\n", 1)
        return line.strip()


class ChatStore:
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
            self.ensure_column(connection, "messages", "lag_ms", "INTEGER")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    username TEXT PRIMARY KEY,
                    password_hash TEXT NOT NULL,
                    salt TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    username TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    detail TEXT NOT NULL
                )
                """
            )

    def ensure_column(self, connection, table, column, column_type):
        columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")

    def hash_password(self, password, salt):
        return hashlib.pbkdf2_hmac(
            "sha256",
            password.encode(ENCODING),
            bytes.fromhex(salt),
            120000,
        ).hex()

    def authenticate_or_register(self, username, password):
        with self.lock:
            with sqlite3.connect(self.db_path) as connection:
                row = connection.execute(
                    "SELECT password_hash, salt FROM users WHERE username = ?",
                    (username,),
                ).fetchone()

                if row:
                    expected_hash, salt = row
                    return secrets.compare_digest(expected_hash, self.hash_password(password, salt))

                salt = secrets.token_hex(16)
                password_hash = self.hash_password(password, salt)
                connection.execute(
                    """
                    INSERT INTO users (username, password_hash, salt, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (username, password_hash, salt, self.now()),
                )
                return True

    def save_message(self, sender, target, message, is_private=False, lag_ms=None):
        with self.lock:
            with sqlite3.connect(self.db_path) as connection:
                connection.execute(
                    """
                    INSERT INTO messages (created_at, sender, target, message, is_private, lag_ms)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (self.now(), sender, target, message, int(is_private), lag_ms),
                )

    def save_event(self, username, event_type, detail=""):
        with self.lock:
            with sqlite3.connect(self.db_path) as connection:
                connection.execute(
                    """
                    INSERT INTO events (created_at, username, event_type, detail)
                    VALUES (?, ?, ?, ?)
                    """,
                    (self.now(), username, event_type, detail),
                )

    def recent_messages(self, limit=100):
        with self.lock:
            with sqlite3.connect(self.db_path) as connection:
                rows = connection.execute(
                    """
                    SELECT created_at, sender, target, message, is_private, lag_ms
                    FROM messages
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        return list(reversed(rows))

    def now(self):
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class ChatServer:
    def __init__(self, on_log, on_users):
        self.on_log = on_log
        self.on_users = on_users
        self.server_socket = None
        self.clients = {}
        self.last_active = {}
        self.clients_lock = threading.Lock()
        self.store = ChatStore()
        self.running = False

    def start(self, host, port):
        if self.running:
            return

        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind((host, port))
        self.server_socket.listen()
        self.running = True

        self.on_log(f"Server active on {host}:{port}")
        threading.Thread(target=self.accept_clients, daemon=True).start()
        threading.Thread(target=self.monitor_client_lag, daemon=True).start()

    def stop(self):
        if not self.running:
            return

        self.running = False
        self.on_log("Server stopped.")

        with self.clients_lock:
            client_sockets = list(self.clients.keys())

        for client_socket in client_sockets:
            self.send_message(client_socket, "\n[SERVER] Server is shutting down.\n")
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
        reader = SocketLineReader(client_socket)

        self.on_log(f"Client connected from {address[0]}:{address[1]}")
        self.send_message(client_socket, "Welcome to the chat server!\n")
        self.send_message(client_socket, "Enter username:\n")

        username = self.sanitize_username(reader.read_line())
        if not username:
            self.send_message(client_socket, "[SERVER] Invalid username.\n")
            client_socket.close()
            return

        self.send_message(client_socket, "Enter password:\n")
        password = reader.read_line()
        if not password or not self.store.authenticate_or_register(username, password):
            self.send_message(client_socket, "[SERVER] Authentication failed.\n")
            self.on_log(f"[AUTH] Failed login for {username} from {address[0]}:{address[1]}")
            client_socket.close()
            return

        with self.clients_lock:
            if username in self.clients.values():
                self.send_message(client_socket, "[SERVER] This username is already online.\n")
                client_socket.close()
                return
            self.clients[client_socket] = username
            self.last_active[client_socket] = time.monotonic()

        self.store.save_event(username, "login", f"{address[0]}:{address[1]}")
        self.refresh_users()
        self.send_message(client_socket, "\nYou are connected. Type /help to see commands.\n")
        self.broadcast(f"\n[SERVER] {username} joined the chat.\n", client_socket)
        self.on_log(f"{username} joined.")

        try:
            while self.running:
                message = reader.read_line()
                if not message or message.lower() == "/quit":
                    break

                self.update_activity(client_socket)
                if message.startswith("/"):
                    self.handle_command(client_socket, username, message)
                else:
                    self.handle_plain_group_message(client_socket, username, message)
        except ConnectionResetError:
            pass
        finally:
            self.remove_client(client_socket)

    def handle_command(self, client_socket, username, raw_message):
        command = raw_message.split(" ", 1)[0].lower()
        if command not in COMMAND_WHITELIST:
            self.send_message(client_socket, f"[SECURITY] Command '{command}' is not allowed. Type /help.\n")
            self.on_log(f"[SECURITY] Blocked command from {username}: {command}")
            return

        if command == "/help":
            self.send_help(client_socket)
        elif command == "/lag":
            self.send_lag_update(client_socket)
        elif command == "/msg":
            self.handle_group_message(client_socket, username, raw_message)
        elif command == "/pm":
            self.handle_private_message(client_socket, username, raw_message)
        elif command == "/typing":
            self.handle_typing_message(client_socket, username, raw_message)

    def send_help(self, client_socket):
        commands = ", ".join(sorted(COMMAND_WHITELIST))
        self.send_message(client_socket, f"[SERVER] Allowed commands: {commands}\n")

    def handle_plain_group_message(self, sender_socket, sender_name, raw_message):
        message = self.sanitize_message(raw_message)
        if not message:
            return
        self.store.save_message(sender_name, "All", message)
        formatted_message = self.format_chat_message(sender_name, message)
        self.on_log(formatted_message.strip())
        self.broadcast(formatted_message, sender_socket)

    def handle_group_message(self, sender_socket, sender_name, raw_message):
        parts = raw_message.split(" ", 2)
        if len(parts) < 3:
            self.send_message(sender_socket, "[SERVER] Message format: /msg sent_at message\n")
            return

        lag_ms = self.calculate_lag_ms(parts[1])
        message = self.sanitize_message(parts[2])
        if not message:
            self.send_message(sender_socket, "[SERVER] Message cannot be empty.\n")
            return

        self.store.save_message(sender_name, "All", message, lag_ms=lag_ms)
        formatted_message = self.format_chat_message(sender_name, message, lag_ms)
        self.on_log(formatted_message.strip())
        self.broadcast(formatted_message, sender_socket)

    def handle_private_message(self, sender_socket, sender_name, raw_message):
        parts = raw_message.split(" ", 3)
        if len(parts) < 4:
            self.send_message(sender_socket, "[SERVER] Private format: /pm username sent_at message\n")
            return

        target_name = self.sanitize_username(parts[1])
        lag_ms = self.calculate_lag_ms(parts[2])
        private_message = self.sanitize_message(parts[3])
        if not target_name or not private_message:
            self.send_message(sender_socket, "[SERVER] Private target and message cannot be empty.\n")
            return

        target_socket = self.find_client_socket(target_name)
        if not target_socket:
            self.send_message(sender_socket, f"[SERVER] User {target_name} is not online.\n")
            return

        timestamp = datetime.now().strftime("%H:%M")
        lag_text = f" | {lag_ms}ms" if lag_ms is not None else ""
        self.store.save_message(sender_name, target_name, private_message, is_private=True, lag_ms=lag_ms)
        self.send_message(target_socket, f"[{timestamp}] [PRIVATE from {sender_name}] {private_message}{lag_text}\n")
        self.send_message(sender_socket, f"[{timestamp}] [PRIVATE to {target_name}] {private_message}{lag_text}\n")
        self.on_log(f"[PRIVATE] {sender_name} -> {target_name}: {private_message}{lag_text}")

    def handle_typing_message(self, sender_socket, sender_name, raw_message):
        parts = raw_message.split(" ", 2)
        if len(parts) < 3:
            return

        target_name = parts[1].strip()
        state = "1" if parts[2].strip() == "1" else "0"
        typing_event = f"{TYPING_PREFIX}{sender_name}|{target_name}|{state}\n"

        if target_name == "All":
            self.broadcast(typing_event, sender_socket)
            return

        target_socket = self.find_client_socket(target_name)
        if target_socket:
            self.send_message(target_socket, typing_event)

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

    def refresh_users(self):
        with self.clients_lock:
            users = list(self.clients.values())
        self.on_users(users)
        self.broadcast(f"{USERLIST_PREFIX}{'|'.join(users)}\n")

    def find_client_socket(self, username):
        with self.clients_lock:
            for client_socket, client_name in self.clients.items():
                if client_name == username:
                    return client_socket
        return None

    def remove_client(self, client_socket):
        with self.clients_lock:
            username = self.clients.pop(client_socket, None)
            self.last_active.pop(client_socket, None)

        try:
            client_socket.close()
        except OSError:
            pass

        if username:
            self.store.save_event(username, "logout")
            self.on_log(f"{username} left.")
            self.broadcast(f"\n[SERVER] {username} left the chat.\n")
            self.refresh_users()

    def update_activity(self, client_socket):
        with self.clients_lock:
            if client_socket in self.clients:
                self.last_active[client_socket] = time.monotonic()

    def get_idle_seconds(self, client_socket):
        with self.clients_lock:
            last_active = self.last_active.get(client_socket)
        if last_active is None:
            return 0
        return max(0, int(time.monotonic() - last_active))

    def send_lag_update(self, client_socket):
        self.send_message(client_socket, f"{LAG_PREFIX}{self.get_idle_seconds(client_socket)}\n")

    def monitor_client_lag(self):
        while self.running:
            time.sleep(LAG_UPDATE_INTERVAL_SECONDS)
            with self.clients_lock:
                client_sockets = list(self.clients.keys())
            for client_socket in client_sockets:
                self.send_lag_update(client_socket)

    def sanitize_username(self, username):
        username = username.strip()
        if not USERNAME_PATTERN.fullmatch(username):
            return ""
        return username

    def sanitize_message(self, message):
        clean = "".join(character for character in message.strip() if character == "\t" or character >= " ")
        return clean[:MAX_MESSAGE_LENGTH]

    def calculate_lag_ms(self, sent_at_text):
        try:
            sent_at = float(sent_at_text)
        except ValueError:
            return None
        return max(0, int((time.time() - sent_at) * 1000))

    def format_chat_message(self, sender, message, lag_ms=None):
        timestamp = datetime.now().strftime("%H:%M")
        lag_text = f" | {lag_ms}ms" if lag_ms is not None else ""
        return f"[{timestamp}] {sender}: {message}{lag_text}\n"


class MasterChatGui:
    def __init__(self):
        self.window = tk.Tk()
        self.window.title("God Chat")
        self.window.geometry("1080x680")
        self.window.minsize(900, 560)

        self.server = ChatServer(self.add_server_log, self.update_user_list)
        self.client_socket = None
        self.client_connected = False
        self.client_receive_buffer = ""
        self.connected_username = ""
        self.current_idle_seconds = 0
        self.theme_name = tk.StringVar(value="Midnight")
        self.font_size = tk.StringVar(value="12")
        self.target_user = tk.StringVar(value="All")
        self.online_users = ["All"]
        self.typing_active = False
        self.typing_stop_job = None
        self.typing_clear_job = None
        self.admin_controls_visible = False
        self.login_username = tk.StringVar(value="Dhika")
        self.login_password = tk.StringVar(value="")
        self.login_host = tk.StringVar(value=CLIENT_HOST)
        self.login_port = tk.StringVar(value=str(PORT))
        self.login_start_server = tk.BooleanVar(value=False)
        self.style = ttk.Style()

        self.build_login_screen()
        self.window.protocol("WM_DELETE_WINDOW", self.close_app)

    def build_login_screen(self):
        theme = THEMES[self.theme_name.get()]
        self.window.configure(bg=theme["bg"])

        self.login_frame = ttk.Frame(self.window, padding=36)
        self.login_frame.pack(fill="both", expand=True)
        self.login_frame.columnconfigure(0, weight=1)
        self.login_frame.columnconfigure(1, weight=1)

        hero = tk.Frame(self.login_frame, bg=theme["bg"])
        hero.grid(row=0, column=0, sticky="nsew", padx=(0, 34))
        hero.columnconfigure(0, weight=1)
        hero.rowconfigure(2, weight=1)

        tk.Label(
            hero,
            text="God Chat",
            bg=theme["bg"],
            fg=theme["text_fg"],
            font=("Arial", 44, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", pady=(52, 10))
        tk.Label(
            hero,
            text="A WhatsApp-style TCP chat app with auth, private messages, typing status, history, and lag feedback.",
            bg=theme["bg"],
            fg=theme["system"],
            font=("Arial", 15),
            justify="left",
            wraplength=430,
            anchor="w",
        ).grid(row=1, column=0, sticky="ew")
        tk.Label(
            hero,
            text="Group chat\nPrivate chat\nOnline users\nTyping indicator\nSQLite history",
            bg=theme["bg"],
            fg=theme["accent"],
            font=("Arial", 13),
            justify="left",
            anchor="sw",
        ).grid(row=2, column=0, sticky="sw", pady=(24, 52))

        panel = tk.Frame(self.login_frame, bg=theme["panel"], padx=28, pady=28)
        panel.grid(row=0, column=1, sticky="nsew")
        panel.columnconfigure(0, weight=1)

        tk.Label(panel, text="Enter Chat", bg=theme["panel"], fg=theme["text_fg"], font=("Arial", 26, "bold")).grid(row=0, column=0, sticky="w", pady=(0, 18))
        self.login_username_entry = self.build_login_field(panel, "Username", self.login_username, 1)
        self.login_password_entry = self.build_login_field(panel, "Password", self.login_password, 3, show="*")
        self.login_host_entry = self.build_login_field(panel, "Server Host", self.login_host, 5)
        self.login_port_entry = self.build_login_field(panel, "Port", self.login_port, 7)

        tk.Checkbutton(
            panel,
            text="Start local server after login",
            variable=self.login_start_server,
            bg=theme["panel"],
            fg=theme["system"],
            activebackground=theme["panel"],
            activeforeground=theme["text_fg"],
            selectcolor=theme["text_bg"],
            font=("Arial", 11),
        ).grid(row=9, column=0, sticky="w", pady=(4, 18))

        ttk.Button(panel, text="Continue", command=self.enter_chat_from_login).grid(row=10, column=0, sticky="ew")
        self.login_username_entry.focus_set()

    def build_login_field(self, parent, label, variable, row, show=None):
        theme = THEMES[self.theme_name.get()]
        tk.Label(parent, text=label, bg=theme["panel"], fg=theme["system"], font=("Arial", 10, "bold")).grid(row=row, column=0, sticky="w")
        entry = tk.Entry(
            parent,
            textvariable=variable,
            show=show,
            bg=theme["text_bg"],
            fg=theme["text_fg"],
            insertbackground=theme["text_fg"],
            relief="flat",
            font=("Arial", 13),
        )
        entry.grid(row=row + 1, column=0, sticky="ew", ipady=9, pady=(4, 14))
        entry.bind("<Return>", lambda event: self.enter_chat_from_login())
        return entry

    def enter_chat_from_login(self):
        username = self.login_username.get().strip()
        password = self.login_password.get()
        host = self.login_host.get().strip()
        port = self.get_port(self.login_port.get())

        if not username:
            messagebox.showwarning("Username required", "Please enter a username first.")
            return
        if not password:
            messagebox.showwarning("Password required", "Please enter a password.")
            return
        if not host or port is None:
            return

        self.login_frame.destroy()
        self.build_ui()
        self.apply_theme()

        self.username.delete(0, tk.END)
        self.username.insert(0, username)
        self.password.delete(0, tk.END)
        self.password.insert(0, password)
        self.client_host.delete(0, tk.END)
        self.client_host.insert(0, host)
        self.client_port.delete(0, tk.END)
        self.client_port.insert(0, str(port))

        if self.login_start_server.get():
            self.start_server()
        self.connect_client()

    def build_ui(self):
        root = ttk.Frame(self.window, padding=18)
        root.pack(fill="both", expand=True)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(1, weight=1)

        header = ttk.Frame(root)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="God Chat", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        self.connection_badge = ttk.Label(header, text="Offline", style="Badge.TLabel")
        self.connection_badge.grid(row=0, column=1, sticky="e")
        self.admin_toggle_button = ttk.Button(header, text="Admin Controls", command=self.toggle_admin_controls)
        self.admin_toggle_button.grid(row=0, column=2, sticky="e", padx=(10, 0))

        workspace = ttk.Frame(root)
        workspace.grid(row=1, column=0, sticky="nsew")
        self.workspace = workspace
        workspace.columnconfigure(0, weight=0)
        workspace.columnconfigure(1, weight=1)
        workspace.columnconfigure(2, weight=2)
        workspace.rowconfigure(0, weight=1)

        self.build_admin_panel(workspace)
        self.build_contacts_panel(workspace)
        self.build_chat_panel(workspace)
        self.admin_panel.grid_remove()
        self.update_server_controls()

    def build_admin_panel(self, parent):
        self.admin_panel = ttk.LabelFrame(parent, text="Admin", padding=14)
        self.admin_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        self.admin_panel.columnconfigure(1, weight=1)
        self.admin_panel.rowconfigure(5, weight=1)

        ttk.Label(self.admin_panel, text="Host").grid(row=0, column=0, sticky="w")
        self.server_host = ttk.Entry(self.admin_panel)
        self.server_host.insert(0, SERVER_HOST)
        self.server_host.grid(row=0, column=1, sticky="ew", pady=3)
        ttk.Label(self.admin_panel, text="Port").grid(row=1, column=0, sticky="w")
        self.server_port = ttk.Entry(self.admin_panel)
        self.server_port.insert(0, str(PORT))
        self.server_port.grid(row=1, column=1, sticky="ew", pady=3)

        self.start_button = ttk.Button(self.admin_panel, text="Start Server", command=self.start_server)
        self.stop_button = ttk.Button(self.admin_panel, text="Stop Server", command=self.stop_server)
        self.start_button.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 4))
        self.stop_button.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 4))

        ttk.Label(self.admin_panel, text="Server Log").grid(row=4, column=0, columnspan=2, sticky="w", pady=(8, 0))
        self.server_log = scrolledtext.ScrolledText(self.admin_panel, height=12, state="disabled")
        self.server_log.grid(row=5, column=0, columnspan=2, sticky="nsew")

    def build_contacts_panel(self, parent):
        self.contacts_panel = ttk.LabelFrame(parent, text="Chats", padding=14)
        self.contacts_panel.grid(row=0, column=1, sticky="nsew", padx=(0, 10))
        self.contacts_panel.rowconfigure(1, weight=1)
        self.contacts_panel.columnconfigure(0, weight=1)

        self.contact_status = ttk.Label(self.contacts_panel, text="Online contacts")
        self.contact_status.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.contacts_list = tk.Listbox(self.contacts_panel, activestyle="none", exportselection=False)
        self.contacts_list.grid(row=1, column=0, sticky="nsew")
        self.contacts_list.bind("<<ListboxSelect>>", self.select_contact)

    def build_chat_panel(self, parent):
        self.chat_panel = ttk.LabelFrame(parent, text="Conversation", padding=14)
        self.chat_panel.grid(row=0, column=2, sticky="nsew")
        self.chat_panel.columnconfigure(1, weight=1)
        self.chat_panel.rowconfigure(7, weight=1)

        ttk.Label(self.chat_panel, text="Host").grid(row=0, column=0, sticky="w")
        self.client_host = ttk.Entry(self.chat_panel)
        self.client_host.insert(0, CLIENT_HOST)
        self.client_host.grid(row=0, column=1, sticky="ew", padx=(8, 0), pady=3)
        ttk.Label(self.chat_panel, text="Port").grid(row=1, column=0, sticky="w")
        self.client_port = ttk.Entry(self.chat_panel)
        self.client_port.insert(0, str(PORT))
        self.client_port.grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=3)
        ttk.Label(self.chat_panel, text="Username").grid(row=2, column=0, sticky="w")
        self.username = ttk.Entry(self.chat_panel)
        self.username.insert(0, "Dhika")
        self.username.grid(row=2, column=1, sticky="ew", padx=(8, 0), pady=3)
        ttk.Label(self.chat_panel, text="Password").grid(row=3, column=0, sticky="w")
        self.password = ttk.Entry(self.chat_panel, show="*")
        self.password.grid(row=3, column=1, sticky="ew", padx=(8, 0), pady=3)
        ttk.Label(self.chat_panel, text="Send To").grid(row=4, column=0, sticky="w")
        self.target_box = ttk.Combobox(self.chat_panel, textvariable=self.target_user, values=["All"], state="readonly")
        self.target_box.grid(row=4, column=1, sticky="ew", padx=(8, 0), pady=3)

        buttons = ttk.Frame(self.chat_panel)
        buttons.grid(row=5, column=0, columnspan=2, sticky="ew", pady=8)
        buttons.columnconfigure(0, weight=1)
        buttons.columnconfigure(1, weight=1)
        ttk.Button(buttons, text="Connect", command=self.connect_client).grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ttk.Button(buttons, text="Disconnect", command=self.disconnect_client).grid(row=0, column=1, sticky="ew", padx=(4, 0))

        self.build_customize_panel(self.chat_panel)

        self.chat_area = scrolledtext.ScrolledText(self.chat_panel, state="disabled")
        self.chat_area.grid(row=7, column=0, columnspan=2, sticky="nsew", pady=(0, 8))

        input_row = ttk.Frame(self.chat_panel)
        input_row.grid(row=8, column=0, columnspan=2, sticky="ew")
        input_row.columnconfigure(0, weight=1)
        self.message_input = ttk.Entry(input_row)
        self.message_input.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.message_input.bind("<Return>", lambda event: self.send_client_message())
        self.message_input.bind("<KeyRelease>", self.handle_message_typing)
        ttk.Button(input_row, text="Send", command=self.send_client_message).grid(row=0, column=1)

        self.typing_label = ttk.Label(self.chat_panel, text="")
        self.typing_label.grid(row=9, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self.status_label = ttk.Label(self.chat_panel, text="Status: offline")
        self.status_label.grid(row=10, column=0, columnspan=2, sticky="w", pady=(6, 0))

    def build_customize_panel(self, parent):
        customize = ttk.LabelFrame(parent, text="Customize", padding=8)
        customize.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        customize.columnconfigure(1, weight=1)
        customize.columnconfigure(3, weight=1)
        ttk.Label(customize, text="Theme").grid(row=0, column=0, sticky="w")
        theme_box = ttk.Combobox(customize, textvariable=self.theme_name, values=list(THEMES.keys()), state="readonly", width=12)
        theme_box.grid(row=0, column=1, sticky="ew", padx=(6, 12))
        theme_box.bind("<<ComboboxSelected>>", lambda event: self.apply_theme())
        ttk.Label(customize, text="Font").grid(row=0, column=2, sticky="w")
        font_box = ttk.Combobox(customize, textvariable=self.font_size, values=FONT_SIZES, state="readonly", width=6)
        font_box.grid(row=0, column=3, sticky="ew", padx=(6, 12))
        font_box.bind("<<ComboboxSelected>>", lambda event: self.apply_theme())
        ttk.Button(customize, text="Clear Chat", command=self.clear_chat).grid(row=0, column=4, sticky="ew", padx=(0, 6))
        ttk.Button(customize, text="Load History", command=self.load_history).grid(row=0, column=5, sticky="ew")

    def toggle_admin_controls(self):
        self.admin_controls_visible = not self.admin_controls_visible
        if self.admin_controls_visible:
            self.admin_panel.grid()
            self.workspace.columnconfigure(0, weight=1)
            self.admin_toggle_button.config(text="Hide Admin")
        else:
            self.admin_panel.grid_remove()
            self.workspace.columnconfigure(0, weight=0)
            self.admin_toggle_button.config(text="Admin Controls")

    def update_server_controls(self):
        if self.server.running:
            self.start_button.grid_remove()
            self.stop_button.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 4))
        else:
            self.stop_button.grid_remove()
            self.start_button.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 4))

    def start_server(self):
        port = self.get_port(self.server_port.get())
        if port is None:
            return
        try:
            self.server.start(self.server_host.get().strip(), port)
            self.update_server_controls()
        except OSError as error:
            messagebox.showerror("Server Error", f"Failed to start server:\n{error}")

    def stop_server(self):
        self.server.stop()
        self.update_server_controls()

    def connect_client(self):
        if self.client_connected:
            return

        port = self.get_port(self.client_port.get())
        username = self.username.get().strip()
        password = self.password.get()
        if port is None:
            return
        if not username or not password:
            messagebox.showwarning("Login required", "Please enter username and password.")
            return

        try:
            self.client_socket = socket.create_connection((self.client_host.get().strip(), port), timeout=5)
            self.client_socket.settimeout(None)
            self.client_receive_buffer = ""
            self.connected_username = username
            self.client_connected = True
            self.status_label.config(text=f"Status: connected as {username}")
            self.connection_badge.config(text="Online")
            self.add_chat_message("[CLIENT] Connected to server.", "system")
            threading.Thread(target=self.receive_client_messages, daemon=True).start()
            self.client_socket.sendall(f"{username}\n".encode(ENCODING))
            self.client_socket.sendall(f"{password}\n".encode(ENCODING))
        except OSError as error:
            self.client_socket = None
            self.client_connected = False
            self.connection_badge.config(text="Offline")
            messagebox.showerror("Client Error", f"Failed to connect:\n{error}")

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
        self.mark_client_disconnected()
        self.add_chat_message("[CLIENT] Disconnected.", "system")

    def receive_client_messages(self):
        while self.client_connected and self.client_socket:
            try:
                data = self.client_socket.recv(BUFFER_SIZE)
                if not data:
                    break
                self.client_receive_buffer += data.decode(ENCODING, errors="replace")
                self.process_client_receive_buffer()
            except OSError:
                break
        self.window.after(0, self.mark_client_disconnected)

    def process_client_receive_buffer(self):
        while "\n" in self.client_receive_buffer:
            line, self.client_receive_buffer = self.client_receive_buffer.split("\n", 1)
            self.handle_incoming_client_line(line.strip())

    def handle_incoming_client_line(self, line):
        if line.startswith(USERLIST_PREFIX):
            users = [user for user in line.removeprefix(USERLIST_PREFIX).split("|") if user]
            self.window.after(0, self.update_target_users, users)
        elif line.startswith(TYPING_PREFIX):
            self.window.after(0, self.update_typing_indicator, line.removeprefix(TYPING_PREFIX))
        elif line.startswith(LAG_PREFIX):
            self.window.after(0, self.update_lag_indicator, line.removeprefix(LAG_PREFIX))
        elif line:
            tag = "system" if line.startswith("[SERVER]") or line.startswith("[CLIENT]") else "other"
            self.add_chat_message(line, tag)

    def send_client_message(self):
        message = self.message_input.get().strip()
        if not message:
            return
        if not self.client_connected or not self.client_socket:
            messagebox.showwarning("Not connected", "Connect to the server first.")
            return

        try:
            self.send_typing_state(False)
            sent_at = time.time()
            target = self.target_user.get()
            if target and target != "All":
                outgoing_message = f"/pm {target} {sent_at} {message}"
                display_message = None
            else:
                outgoing_message = f"/msg {sent_at} {message}"
                display_message = f"You: {message}"

            self.client_socket.sendall(f"{outgoing_message}\n".encode(ENCODING))
            if display_message:
                self.add_chat_message(display_message, "own")
            self.message_input.delete(0, tk.END)
        except OSError:
            self.mark_client_disconnected()

    def handle_message_typing(self, event=None):
        if not self.client_connected or not self.client_socket:
            return
        if self.message_input.get().strip():
            self.send_typing_state(True)
            if self.typing_stop_job:
                self.window.after_cancel(self.typing_stop_job)
            self.typing_stop_job = self.window.after(TYPING_STOP_DELAY_MS, lambda: self.send_typing_state(False))
        else:
            self.send_typing_state(False)

    def send_typing_state(self, is_typing):
        if not self.client_connected or not self.client_socket:
            self.typing_active = False
            return
        if self.typing_active == is_typing:
            return
        self.typing_active = is_typing
        state = "1" if is_typing else "0"
        try:
            self.client_socket.sendall(f"/typing {self.target_user.get() or 'All'} {state}\n".encode(ENCODING))
        except OSError:
            self.mark_client_disconnected()

    def update_typing_indicator(self, payload):
        parts = payload.split("|", 2)
        if len(parts) != 3:
            return
        sender, target, state = parts
        if sender == self.username.get().strip():
            return
        if target != "All" and target != self.username.get().strip():
            return
        if state == "1":
            self.typing_label.config(text=f"{sender} is typing..." if target == "All" else f"{sender} is typing privately...")
            if self.typing_clear_job:
                self.window.after_cancel(self.typing_clear_job)
            self.typing_clear_job = self.window.after(TYPING_STOP_DELAY_MS + 500, self.clear_typing_indicator)
        else:
            self.clear_typing_indicator()

    def clear_typing_indicator(self):
        self.typing_label.config(text="")
        self.typing_clear_job = None

    def update_lag_indicator(self, payload):
        try:
            idle_seconds = int(payload)
        except ValueError:
            return
        if self.client_connected and self.connected_username:
            self.status_label.config(text=f"Status: connected as {self.connected_username} | idle {idle_seconds}s")

    def update_target_users(self, users):
        current_username = self.username.get().strip()
        targets = ["All"]
        targets.extend(user for user in users if user != current_username)
        self.online_users = targets
        self.target_box["values"] = targets
        self.contacts_list.delete(0, tk.END)
        for target in targets:
            self.contacts_list.insert(tk.END, target)
        if self.target_user.get() not in targets:
            self.target_user.set("All")
        if self.contacts_list.size() and not self.contacts_list.curselection():
            self.contacts_list.selection_set(0)

    def select_contact(self, event=None):
        selection = self.contacts_list.curselection()
        if selection:
            self.target_user.set(self.contacts_list.get(selection[0]))

    def mark_client_disconnected(self):
        if self.typing_stop_job:
            self.window.after_cancel(self.typing_stop_job)
            self.typing_stop_job = None
        self.typing_active = False
        if self.client_socket:
            try:
                self.client_socket.close()
            except OSError:
                pass
        self.client_socket = None
        self.client_connected = False
        self.client_receive_buffer = ""
        self.connected_username = ""
        if hasattr(self, "status_label"):
            self.status_label.config(text="Status: offline")
        if hasattr(self, "connection_badge"):
            self.connection_badge.config(text="Offline")

    def add_server_log(self, message):
        self.window.after(0, self.append_text, self.server_log, message)

    def add_chat_message(self, message, tag="other"):
        self.window.after(0, self.append_text, self.chat_area, message, tag)

    def append_text(self, widget, message, tag=None):
        widget.config(state="normal")
        widget.insert(tk.END, f"{message}\n", tag if tag else None)
        widget.see(tk.END)
        widget.config(state="disabled")

    def clear_chat(self):
        self.chat_area.config(state="normal")
        self.chat_area.delete("1.0", tk.END)
        self.chat_area.config(state="disabled")

    def load_history(self):
        rows = ChatStore().recent_messages()
        self.clear_chat()
        if not rows:
            self.add_chat_message("[HISTORY] No chat history yet.", "system")
            return
        self.add_chat_message("[HISTORY] Showing the last 100 messages.", "system")
        for created_at, sender, target, message, is_private, lag_ms in rows:
            lag_text = f" | {lag_ms}ms" if lag_ms is not None else ""
            if is_private:
                text = f"{created_at} [PRIVATE] {sender} -> {target}: {message}{lag_text}"
            else:
                text = f"{created_at} {sender}: {message}{lag_text}"
            self.add_chat_message(text, "system" if is_private else "other")

    def apply_theme(self):
        theme = THEMES[self.theme_name.get()]
        font = ("Arial", int(self.font_size.get()))
        mono_font = ("Consolas", int(self.font_size.get()))

        self.window.configure(bg=theme["bg"])
        self.style.theme_use("clam")
        self.style.configure("TFrame", background=theme["bg"])
        self.style.configure("TLabelframe", background=theme["bg"])
        self.style.configure("TLabelframe.Label", background=theme["bg"], foreground=theme["text_fg"], font=("Arial", 12, "bold"))
        self.style.configure("TLabel", background=theme["bg"], foreground=theme["text_fg"], font=font)
        self.style.configure("Title.TLabel", background=theme["bg"], foreground=theme["text_fg"], font=("Arial", 26, "bold"))
        self.style.configure("Badge.TLabel", background=theme["panel"], foreground=theme["accent"], font=("Arial", 11, "bold"), padding=(12, 6))
        self.style.configure("TButton", font=font, padding=8)
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

        for listbox in (self.contacts_list,):
            listbox.configure(
                bg=theme["text_bg"],
                fg=theme["text_fg"],
                selectbackground=theme["accent"],
                selectforeground="#ffffff",
                font=font,
                relief="flat",
            )

    def get_port(self, value):
        try:
            port = int(value)
        except ValueError:
            messagebox.showwarning("Invalid port", "Port must be a number.")
            return None
        if not 1 <= port <= 65535:
            messagebox.showwarning("Invalid port", "Port must be between 1 and 65535.")
            return None
        return port

    def close_app(self):
        self.disconnect_client()
        self.server.stop()
        self.window.destroy()

    def run(self):
        self.window.mainloop()


if __name__ == "__main__":
    MasterChatGui().run()
