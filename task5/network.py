import socket
import logging
from enum import Enum
from typing import Optional, Tuple


class ConnectionPhase(Enum):
    INITIAL = 0
    GREETING = 1
    CONNECTION_REQUEST = 2
    ACTIVE = 3


class SocksProxyClient:

    def __init__(self, client_sock: socket.socket,
                 client_ip: str = None, client_port: int = None):
        self.is_active = True
        self.client_socket = client_sock
        self.client_address = client_ip
        self.client_port = client_port
        self.connection_phase = ConnectionPhase.INITIAL
        self.target_socket = None
        self.target_host = None
        self.target_port = None

    def process_client_data(self):
        if not self.is_active:
            return

        if self.connection_phase == ConnectionPhase.INITIAL:
            self.connection_phase = ConnectionPhase.GREETING
            logging.debug(f"{self.client_address}:{self.client_port} -> Starting handshake")
            return

        elif self.connection_phase == ConnectionPhase.GREETING:
            self._handle_greeting_phase()

        elif self.connection_phase == ConnectionPhase.CONNECTION_REQUEST:
            self._handle_connection_request()

        elif self.connection_phase == ConnectionPhase.ACTIVE:
            self._handle_data_transfer()

    def _handle_greeting_phase(self):
        logging.debug(f"{self.client_address}:{self.client_port} -> Processing greeting")

        try:
            version = self.client_socket.recv(1)
            if version != b'\x05':
                logging.warning(f"Unsupported SOCKS version from {self.client_address}")
                self._terminate_with_error()
                return

            auth_methods_count = self.client_socket.recv(1)
            auth_methods = self.client_socket.recv(int.from_bytes(auth_methods_count, "big"))

            if b'\x00' in auth_methods:
                self.client_socket.send(b'\x05\x00')
                self.connection_phase = ConnectionPhase.CONNECTION_REQUEST
                logging.debug(f"{self.client_address}:{self.client_port} -> Greeting accepted")
            else:
                self.client_socket.send(b'\x05\xFF')
                logging.warning(f"No acceptable auth methods from {self.client_address}")
                self._terminate_with_error()

        except socket.error as recv_error:
            logging.error(f"Greeting error: {recv_error}")
            self._terminate_with_error()

    def _handle_connection_request(self):
        logging.debug(f"{self.client_address}:{self.client_port} -> Connection request")

        try:
            version = self.client_socket.recv(1)
            if version != b'\x05':
                logging.warning(f"Invalid version in connection request")
                self._terminate_with_error()
                return

            command = self.client_socket.recv(1)
            if command != b'\x01':
                self._send_command_not_supported()
                return

            self.client_socket.recv(1)

            address_type = self.client_socket.recv(1)
            destination_address = self._parse_destination_address(address_type)

            if not destination_address:
                self._send_address_not_supported()
                return

            port_bytes = self.client_socket.recv(2)
            destination_port = int.from_bytes(port_bytes, "big")

            if self._establish_target_connection(destination_address, destination_port):
                self._send_success_response()
                self.connection_phase = ConnectionPhase.ACTIVE
                logging.info(f"{self.client_address}:{self.client_port} -> Connected to {destination_address}:{destination_port}")
            else:
                self._send_connection_failed()

        except socket.error as request_error:
            logging.error(f"Connection request error: {request_error}")
            self._terminate_with_error()

    def _parse_destination_address(self, address_type: bytes) -> Optional[str]:
        try:
            if address_type == b'\x01':
                ipv4_bytes = self.client_socket.recv(4)
                return socket.inet_ntop(socket.AF_INET, ipv4_bytes)

            elif address_type == b'\x03':
                domain_length = self.client_socket.recv(1)
                domain_name = self.client_socket.recv(int.from_bytes(domain_length, "big"))
                return socket.gethostbyname(domain_name.decode("utf-8"))

            elif address_type == b'\x04':
                ipv6_bytes = self.client_socket.recv(16)
                return socket.inet_ntop(socket.AF_INET6, ipv6_bytes)

        except (socket.error, UnicodeDecodeError) as parse_error:
            logging.error(f"Address parsing error: {parse_error}")

        return None

    def _establish_target_connection(self, host: str, port: int) -> bool:
        try:
            self.target_socket = socket.socket(
                family=socket.AF_INET,
                type=socket.SOCK_STREAM,
                proto=socket.IPPROTO_TCP
            )

            self.target_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.target_socket.setblocking(False)
            self.target_socket.settimeout(30.0)

            self.target_socket.connect((host, port))
            self.target_host, self.target_port = host, port

            return True

        except (socket.error, OSError) as connect_error:
            logging.error(f"Target connection failed to {host}:{port}: {connect_error}")
            return False

    def _handle_data_transfer(self):
        try:
            client_data = self.client_socket.recv(4096)

            if len(client_data) == 0:
                logging.debug(f"{self.client_address}:{self.client_port} -> Client disconnected")
                self._terminate_with_error()
                return

            logging.debug(f"{self.client_address}:{self.client_port} -> Forwarding {len(client_data)} bytes")
            self.target_socket.send(client_data)

        except (socket.error, ConnectionError) as transfer_error:
            logging.warning(f"Data transfer error: {transfer_error}")
            self._terminate_with_error()

    def forward_to_client(self):
        if not self.is_active or not self.target_socket:
            return

        try:
            server_data = self.target_socket.recv(4096)

            if len(server_data) == 0:
                logging.debug(f"{self.client_address}:{self.client_port} -> Target disconnected")
                self._terminate_with_error()
                return

            logging.debug(f"{self.client_address}:{self.client_port} <- Receiving {len(server_data)} bytes")
            self.client_socket.send(server_data)

        except (socket.error, ConnectionError) as forward_error:
            logging.warning(f"Forwarding error: {forward_error}")
            self._terminate_with_error()

    def _send_success_response(self):
        try:
            response = b'\x05\x00\x00\x01'  # Success, IPv4
            response += socket.inet_aton(self.target_socket.getsockname()[0])
            response += self.target_socket.getsockname()[1].to_bytes(2, "big")
            self.client_socket.send(response)
        except socket.error:
            pass

    def _send_command_not_supported(self):
        self.client_socket.send(b'\x05\x07\x00\x01\x00\x00\x00\x00\x00\x00')
        self._terminate_with_error()

    def _send_address_not_supported(self):
        self.client_socket.send(b'\x05\x08\x00\x01\x00\x00\x00\x00\x00\x00')
        self._terminate_with_error()

    def _send_connection_failed(self):
        self.client_socket.send(b'\x05\x01\x00\x01\x00\x00\x00\x00\x00\x00')
        self._terminate_with_error()

    def _terminate_with_error(self):
        self.terminate_connection()

    def terminate_connection(self):
        self.is_active = False

        for sock in [self.client_socket, self.target_socket]:
            if sock:
                try:
                    sock.close()
                except:
                    pass
                finally:
                    if sock == self.client_socket:
                        self.client_socket = None
                    else:
                        self.target_socket = None

    def __del__(self):
        self.terminate_connection()
