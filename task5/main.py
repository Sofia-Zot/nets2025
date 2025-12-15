import argparse
import logging
import socket
import select
from typing import List

from network import SocksProxyClient


def create_server_socket() -> socket.socket:
    server_sock = socket.socket(
        family=socket.AF_INET,
        type=socket.SOCK_STREAM,
        proto=socket.IPPROTO_TCP
    )

    server_sock.setsockopt(
        socket.SOL_SOCKET,
        socket.SO_REUSEADDR,
        1
    )

    server_sock.setblocking(False)
    server_sock.settimeout(60.0)

    return server_sock


def build_select_lists(active_clients: List[SocksProxyClient],
                       server_sock: socket.socket) -> List[socket.socket]:
    read_sockets = [server_sock]

    for client in active_clients:
        if not client.is_active:
            continue

        read_sockets.append(client.client_socket)

        if client.target_socket:
            read_sockets.append(client.target_socket)

    return read_sockets


def cleanup_inactive_clients(clients: List[SocksProxyClient]) -> List[SocksProxyClient]:
    return [client for client in clients if client.is_active]


def main():
    logging.basicConfig(
        format="[%(levelname)s] %(asctime)s - %(message)s",
        level=logging.INFO,
        datefmt="%H:%M:%S"
    )

    arg_parser = argparse.ArgumentParser(
        prog="SOCKS5-Proxy",
        description="SOCKS5 Proxy Server Implementation"
    )

    arg_parser.add_argument(
        "port",
        type=int,
        default=5245,
        help="Port number to listen on"
    )

    arguments = arg_parser.parse_args()

    logging.info(f"Starting SOCKS5 proxy server on port {arguments.port}")

    try:
        listener_socket = create_server_socket()
        listener_socket.bind(("0.0.0.0", arguments.port))
        listener_socket.listen(10)

        logging.info("Proxy server is ready to accept connections")

        connected_clients = []

        while True:
            sockets_to_monitor = build_select_lists(connected_clients, listener_socket)

            try:
                ready_to_read, _, _ = select.select(sockets_to_monitor, [], [], 1.0)
            except (ValueError, OSError) as select_error:
                logging.warning(f"Select error: {select_error}")
                continue

            if listener_socket in ready_to_read:
                try:
                    client_connection, (client_ip, client_port) = listener_socket.accept()

                    new_client = SocksProxyClient(client_connection, client_ip, client_port)
                    connected_clients.append(new_client)

                    logging.info(f"New client connected: {client_ip}:{client_port}")
                except socket.error as accept_error:
                    logging.error(f"Failed to accept connection: {accept_error}")
                    continue

            for client_instance in connected_clients[:]:
                if not client_instance.is_active:
                    continue

                if client_instance.client_socket in ready_to_read:
                    client_instance.process_client_data()

                if (client_instance.target_socket and
                        client_instance.target_socket in ready_to_read):
                    client_instance.forward_to_client()

            connected_clients = cleanup_inactive_clients(connected_clients)

    except KeyboardInterrupt:
        logging.info("Shutdown signal received")
    except Exception as unexpected_error:
        logging.error(f"Unexpected error: {unexpected_error}")
    finally:
        try:
            listener_socket.close()
        except:
            pass

        for client in connected_clients:
            client.terminate_connection()

        logging.info("Proxy server stopped")


if __name__ == "__main__":
    main()
