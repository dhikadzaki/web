import socket
import threading


HOST = "127.0.0.1"
PORT = 5000
BUFFER_SIZE = 1024
ENCODING = "utf-8"

clients = {}
clients_lock = threading.Lock()


def send_message(client_socket, message):
    try:
        client_socket.sendall(message.encode(ENCODING))
    except OSError:
        remove_client(client_socket)


def broadcast(message, sender_socket=None):
    with clients_lock:
        client_sockets = list(clients.keys())

    for client_socket in client_sockets:
        if client_socket != sender_socket:
            send_message(client_socket, message)


def remove_client(client_socket):
    with clients_lock:
        username = clients.pop(client_socket, None)

    try:
        client_socket.close()
    except OSError:
        pass

    if username:
        print(f"{username} disconnected")
        broadcast(f"\n[SERVER] {username} left the chat.\n")


def receive_line(client_socket):
    data = client_socket.recv(BUFFER_SIZE)
    if not data:
        return ""
    return data.decode(ENCODING, errors="replace").strip()


def handle_client(client_socket, address):
    print(f"Connected by {address[0]}:{address[1]}")

    send_message(client_socket, "Welcome to the TCP chat server!\n")
    send_message(client_socket, "Enter your username: ")

    username = receive_line(client_socket)
    if not username:
        client_socket.close()
        return

    with clients_lock:
        clients[client_socket] = username

    send_message(
        client_socket,
        "\nYou joined the chat. Type /quit to leave.\n",
    )
    broadcast(f"\n[SERVER] {username} joined the chat.\n", client_socket)
    print(f"{username} joined from {address[0]}:{address[1]}")

    try:
        while True:
            message = receive_line(client_socket)
            if not message or message.lower() == "/quit":
                break

            formatted_message = f"{username}: {message}\n"
            print(formatted_message, end="")
            broadcast(formatted_message, client_socket)
    except ConnectionResetError:
        pass
    finally:
        remove_client(client_socket)


def start_server(host=HOST, port=PORT):
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind((host, port))
    server_socket.listen()

    print(f"Chat server running on {host}:{port}")
    print("Press Ctrl+C to stop the server.")

    try:
        while True:
            client_socket, address = server_socket.accept()
            thread = threading.Thread(
                target=handle_client,
                args=(client_socket, address),
                daemon=True,
            )
            thread.start()
    except KeyboardInterrupt:
        print("\nStopping server...")
    finally:
        with clients_lock:
            client_sockets = list(clients.keys())

        for client_socket in client_sockets:
            send_message(client_socket, "\n[SERVER] Server is shutting down.\n")
            remove_client(client_socket)

        server_socket.close()


if __name__ == "__main__":
    start_server()
