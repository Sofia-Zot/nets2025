import socket
import time
from PyQt6.QtNetwork import QUdpSocket, QAbstractSocket, QHostAddress, QNetworkDatagram
import snakes.snakes_pb2 as snakes



class Subscriber:
    def notify(self, datagram: QNetworkDatagram):
        pass



class NetworkHandler:
    MULTICAST_GROUP = "224.0.0.1"
    MULTICAST_PORT = 9192

    def __init__(self):
        self._subscribers = list()

        self.direct_socket = QUdpSocket()
        self.direct_socket.bind()
        self.direct_socket.readyRead.connect(self.processP2PDatagram)

        self.multicast_socket = QUdpSocket()
        self.multicast_socket.setSocketOption(QAbstractSocket.SocketOption.MulticastTtlOption, 100)
        self.multicast_socket.setSocketOption(QAbstractSocket.SocketOption.MulticastLoopbackOption, 1)
        self.multicast_socket.bind(
            QHostAddress.SpecialAddress.AnyIPv4,
            self.MULTICAST_PORT,
            QAbstractSocket.BindFlag.ShareAddress | QAbstractSocket.BindFlag.ReuseAddressHint
        )
        self.multicast_socket.joinMulticastGroup(QHostAddress(self.MULTICAST_GROUP))
        self.multicast_socket.readyRead.connect(self.processMulticastDatagram)

    def processP2PDatagram(self):
        try:
            while self.direct_socket.hasPendingDatagrams():
                datagram = self.direct_socket.receiveDatagram()
                self.notifySubscribers(datagram)
        except Exception as e:
            print("processP2PDatagram", e)

    def processMulticastDatagram(self):
        try:
            while self.multicast_socket.hasPendingDatagrams():
                datagram = self.multicast_socket.receiveDatagram()
                self.notifySubscribers(datagram)
        except Exception as e:
            print("processMulticastDatagram", e)

    def subscribe(self, subscriber: Subscriber):
        self._subscribers.append(subscriber)

    def unsubscribe(self, subscriber: Subscriber):
        self._subscribers.remove(subscriber)

    def notifySubscribers(self, datagram: QNetworkDatagram):
        for subscriber in self._subscribers:
            subscriber.notify(datagram)

    def multicast(self, message: snakes.GameMessage):
        self.multicast_socket.writeDatagram(
            message.SerializeToString(),
            QHostAddress(self.MULTICAST_GROUP),
            self.MULTICAST_PORT
        )

    def unicast(self, message: snakes.GameMessage, host: str, port: int):
        self.direct_socket.writeDatagram(
            message.SerializeToString(),
            QHostAddress(host),
            port
        )

    @property
    def port(self):
        return self.direct_socket.localPort()

    @property
    def host(self):
        local_hostname = socket.gethostname()
        ip_addresses = socket.gethostbyname_ex(local_hostname)[2]
        filtered_ips = [ip for ip in ip_addresses if not ip.startswith("127.")]
        return filtered_ips[0]
