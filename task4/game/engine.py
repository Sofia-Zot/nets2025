import logging
import random
import time

from PyQt6.QtCore import QTimer
from PyQt6.QtNetwork import QNetworkDatagram

import snakes.snakes_pb2 as snakes
from game.player_manager import PlayerManager, Player
from game.field_manager import FieldManager, Snake
from typing import Union, List, Tuple, Set, Dict
from types import FunctionType

from network import NetworkHandler, Subscriber


class GameEngine(Subscriber):
    def __init__(
            self,
            game_name: str,
            field_width: int,
            field_height: int,
            food_static: int,
            state_delay_ms: int,
            network_handler: NetworkHandler,
            client_name: str,
            client_requested_role: snakes.NodeRole,
            existing_players: snakes.GamePlayers,
            update_callback
    ):
        self._update_callback = update_callback
        self.game_name = game_name
        self.state_delay_ms = state_delay_ms
        self.network_handler = network_handler

        self.network_handler.subscribe(self)

        self.__player_id = 0
        self.player_manager = PlayerManager(
            client_player=Player(
                name=client_name,
                id=-1,
                ip_address=network_handler.host,
                port=network_handler.port,
                role=client_requested_role,
                is_client=True
            ),
            existing_players=existing_players
        )

        self.field_manager = FieldManager(
            width=field_width,
            height=field_height,
            food_static=food_static
        )
        self._timers: Set[QTimer] = set()

        self._messages_expecting_ack = dict()
        self.__msg_seq = 0
        self._state_order = 0
        self._ack_timer = self._init_timer(
            delay_ms=self.state_delay_ms // 10,
            callback=self._retrySending2Master
        )

        self._ping_timer = self._init_timer(
            delay_ms=self.state_delay_ms // 10,
            callback=self._ping
        )

        self._tick_timer = self._init_timer(
            delay_ms=self.state_delay_ms,
            callback=self._tick
        )

        self._announce_timer = self._init_timer(
            delay_ms=1000,
            callback=self._announce
        )

    def start(self, is_host: bool, master_host: str, master_port: int) -> None:
        try:
            # Step 1. Если is_host, то вызываем запуск СЕРВЕРНЫХ служб
            if is_host:
                self.player_manager.client_player.id = self._player_id()
                self._becomeMaster()
                x, y = self.field_manager.getPosForNewSnake()
                self.field_manager.spawnSnake(x, y, self.player_manager.client_player.id)

            # Step 2. Запустить все нужные для КЛИЕНТА службы
            else:
                joinMessage = snakes.GameMessage(
                    msg_seq=self._msg_seq(),
                    join=snakes.GameMessage.JoinMsg(
                        player_type=snakes.HUMAN,
                        player_name=self.player_manager.client_player.name,
                        game_name=self.game_name,
                        requested_role=self.player_manager.client_player.role
                    )
                )
                self._sendMessage(message=joinMessage, host=master_host, port=master_port, expect_ack=True)
                master = self.player_manager.getMaster()
                if master is not None:
                    master.ip_address = master_host
                    master.port = master_port
                    # print(f"Found master {master.name}#{master.id}, set {master_host}:{master_port}")

            self._ack_timer.start()
            self._ping_timer.start()
        except Exception as e:
            print("start", e)

    def stop(self) -> None:
        # Остановка всех служб
        for timer in self._timers:
            timer.stop()

        self.network_handler.unsubscribe(self)

    def moveClientSnake(self, direction: snakes.Direction) -> None:
        if self.player_manager.client_player.role == snakes.VIEWER:
            return
        message = snakes.GameMessage(
            steer=snakes.GameMessage.SteerMsg(
                direction=direction
            )
        )
        self._sendMessage2Master(message, expect_ack=True)
        master = self.player_manager.getMaster()
        logging.info(f"Sent steer message {direction} to {master.name}#{master.id} {master.ip_address}:{master.port}")

    def _init_timer(self, delay_ms: int, callback, start: bool = False) -> QTimer:
        timer = QTimer()
        timer.setInterval(delay_ms)
        timer.timeout.connect(callback)
        timer.setSingleShot(False)
        self._timers.add(timer)
        if start:
            timer.start()
        return timer

    def _msg_seq(self):
        msg_seq = self.__msg_seq
        self.__msg_seq += 1
        return msg_seq

    def _player_id(self):
        player_id = self.__player_id
        self.__player_id += 1
        return player_id

    def _sendMessage2Master(self, message: snakes.GameMessage,
                            expect_ack: bool = False, calibrate: bool = True) -> None:
        master = self.player_manager.getMaster()
        if master is None:
            logging.warning("tried to send message to MASTER, but no MASTER was found!")
            logging.warning("message dropped:")
            logging.warning(message)

            if self.player_manager.client_player.role == snakes.DEPUTY:
                self._becomeMaster()
                self._sendMessage2Master(message, expect_ack, calibrate)
            return
        self._sendMessage2Player(message=message, player=master, expect_ack=expect_ack, calibrate=calibrate)

    def _sendMessage2Player(self, message: snakes.GameMessage, player: Player,
                            expect_ack: bool = False, calibrate: bool = True):
        if calibrate:
            message.msg_seq = self._msg_seq()
            message.sender_id = self.player_manager.client_player.id
            message.receiver_id = player.id
        self._sendMessage(message=message, host=player.ip_address, port=player.port, expect_ack=expect_ack)
        player.last_socket_message_sent = time.time_ns()

    def _sendMessage(self, message: snakes.GameMessage, host: str, port: int, expect_ack: bool = False) -> None:
        if expect_ack:
            self._messages_expecting_ack[message.msg_seq] = message
        self.network_handler.unicast(message=message, host=host, port=port)

    def _retrySending2Master(self):
        try:
            for message in self._messages_expecting_ack.values():
                self._sendMessage2Master(message, expect_ack=True, calibrate=False)
        except Exception as e:
            print("_retrySending2Master", e)

    def _acknowledge(self, message: snakes.GameMessage, host: str, port: int):
        ackMessage = snakes.GameMessage(
            msg_seq=message.msg_seq,
            sender_id=message.receiver_id,
            receiver_id=message.sender_id,
            ack=snakes.GameMessage.AckMsg()
        )
        self._sendMessage(message=ackMessage, host=host, port=port, expect_ack=False)

    def _announce(self, address: tuple[str, int] = None):
        announceMessage = snakes.GameMessage(
            msg_seq=self._msg_seq(),
            announcement=snakes.GameMessage.AnnouncementMsg(
                games=[
                    snakes.GameAnnouncement(
                        can_join=self.field_manager.getPosForNewSnake() is not None,
                        game_name=self.game_name,
                        config=snakes.GameConfig(
                            width=self.field_manager.width,
                            height=self.field_manager.height,
                            food_static=self.field_manager.food_static,
                            state_delay_ms=self.state_delay_ms
                        ),
                        players=snakes.GamePlayers(
                            players=self.player_manager.asMsg()
                        )
                    )
                ]
            )
        )
        if address is not None:
            host, port = address
            self._sendMessage(message=announceMessage, host=host, port=port, expect_ack=False)
            return
        self.network_handler.multicast(message=announceMessage)

    def _ping(self):
        try:
            to_be_deleted = set()
            current_time = time.time_ns()

            for player in self.player_manager.getPlayers():
                if player == self.player_manager.client_player:
                    continue  # better not to kick yourself, even if something is wrong

                if current_time - player.last_socket_message_sent > self.state_delay_ms // 10 * 1e6:
                    pingMessage = snakes.GameMessage(ping=snakes.GameMessage.PingMsg())
                    self._sendMessage2Player(message=pingMessage, player=player)

                if current_time - player.last_socket_message_got > self.state_delay_ms * 0.8 * 1e6:
                    logging.warning(f"{player.name}#{player.id} does not respond. Kicked from formation.")
                    to_be_deleted.add(player)

                    # Situation A. NORMAL sees MASTER died
                    if self.player_manager.client_player.role == snakes.NORMAL:
                        if player.role == snakes.MASTER:
                            logging.info("MASTER dead, switching to DEPUTY.")
                            self._switch2NewMaster()

                    # Situation B. MASTER sees DEPUTY died
                    elif self.player_manager.client_player.role == snakes.MASTER:
                        if player.role == snakes.DEPUTY:
                            logging.info("DEPUTY dead, assigning new DEPUTY.")
                            self._assignNewDeputy()

                    # Situation C. DEPUTY sees MASTER died
                    elif self.player_manager.client_player.role == snakes.DEPUTY:
                        if player.role == snakes.MASTER:
                            logging.info("MASTER dead, i shall become new MASTER.")
                            self._becomeMaster()
            for player in to_be_deleted:
                self.player_manager.removePlayerByID(player.id)
                snakes_with_id = set(
                    filter(lambda s: s.player_id == player.id, self.field_manager.getSnakes())
                )
                for snake in snakes_with_id:
                    snake.state = snakes.GameState.Snake.SnakeState.ZOMBIE
        except Exception as e:
            print("_ping", e)

    def _findNewDeputy(self) -> Union[Player, None]:
        normal_players = self.player_manager.getPlayersWithRole(snakes.NORMAL)
        if len(normal_players) < 1:
            logging.warning("No NORMAL nodes found!")
            return None
        deputy = normal_players.pop()
        deputy.role = snakes.DEPUTY
        return deputy

    def _switch2NewMaster(self):
        deputy = self.player_manager.getDeputy()
        if deputy is None:
            logging.warning(f"No DEPUTY found!")
            return
        deputy.role = snakes.MASTER

    def _assignNewDeputy(self):
        deputy = self._findNewDeputy()
        if deputy is not None:
            roleChangeMessage = snakes.GameMessage(
                role_change=snakes.GameMessage.RoleChangeMsg(
                    sender_role=self.player_manager.client_player.role,
                    receiver_role=deputy.role
                )
            )
            self._sendMessage2Player(message=roleChangeMessage, player=deputy)
        else:
            logging.info("Could not assign new DEPUTY.")

    def _becomeMaster(self):
        logging.info("I am now MASTER")
        self.player_manager.client_player.role = snakes.MASTER
        deputy = self._findNewDeputy()
        if deputy is None:
            logging.info("Could not assign new DEPUTY.")

        for other_player in self.player_manager.getPlayers():
            if other_player == self.player_manager.client_player:
                continue
            newMasterMessage = snakes.GameMessage(
                role_change=snakes.GameMessage.RoleChangeMsg(
                    sender_role=self.player_manager.client_player.role,
                    receiver_role=other_player.role
                )
            )
            self._sendMessage2Player(message=newMasterMessage, player=other_player)

        self._tick_timer.start()
        self._announce_timer.start()

    def becomeViewer(self):
        if self.player_manager.client_player.role == snakes.VIEWER:
            return

        roleChangeMessage = snakes.GameMessage(
            role_change=snakes.GameMessage.RoleChangeMsg(
                sender_role=snakes.VIEWER,
                receiver_role=snakes.MASTER
            )
        )
        self._sendMessage2Master(roleChangeMessage, expect_ack=True)
        if self.player_manager.client_player.role == snakes.MASTER:
            self._tick_timer.stop()
            self._announce_timer.stop()
            deputy = self.player_manager.getDeputy()
            if deputy is not None:
                roleChangeMessage = snakes.GameMessage(
                    role_change=snakes.GameMessage.RoleChangeMsg(
                        sender_role=snakes.MASTER,
                        receiver_role=snakes.MASTER
                    )
                )
                self._sendMessage2Player(roleChangeMessage, player=deputy, expect_ack=True)

    def _sendGameState(self, player: Player = None):
        gameStateMessage = snakes.GameMessage(
            state=snakes.GameMessage.StateMsg(
                state=snakes.GameState(
                    state_order=self._state_order + 1,
                    players=snakes.GamePlayers(
                        players=self.player_manager.asMsg()
                    ),
                    foods=[snakes.GameState.Coord(x=x, y=y) for x, y in self.field_manager.getFood()],
                    snakes=[snake.asMsg(self.field_manager.width, self.field_manager.height)
                            for snake in self.field_manager.getSnakes()]
                )
            )
        )
        if player is not None:
            self._sendMessage2Player(message=gameStateMessage, player=player, expect_ack=False)
            return
        for player in self.player_manager.getPlayers():
            self._sendMessage2Player(message=gameStateMessage, player=player, expect_ack=False)

    def _tick(self) -> None:
        # Step 1. Tick Field
        player_updates = self.field_manager.tick()

        master_died = False
        # Step 2. Apply player changes that are out of scope of the field
        for player_id, update_id in player_updates:
            player = self.player_manager.getPlayerByID(player_id)
            if player is None:
                logging.warning("Snake has id of non-existent player")
                continue
            match update_id:
                case FieldManager.UPDATE_SCORE:
                    player.score += 1
                case FieldManager.UPDATE_DEATH:
                    if player == self.player_manager.client_player:
                        master_died = True
                        continue
                    player.role = snakes.VIEWER
                    roleChangeMessage = snakes.GameMessage(
                        role_change=snakes.GameMessage.RoleChangeMsg(
                            sender_role=snakes.MASTER,
                            receiver_role=snakes.VIEWER
                        )
                    )
                    self._sendMessage2Player(message=roleChangeMessage, player=player, expect_ack=True)

        # Step 3. Send states
        self._sendGameState()
        if master_died:
            self.becomeViewer()

    def notify(self, datagram: QNetworkDatagram):
        current_time = time.time_ns()

        raw = bytes(datagram.data())
        message = snakes.GameMessage()
        message.ParseFromString(raw)
        # print(message.WhichOneof("Type"), type(message))
        match message.WhichOneof("Type"):
            # do not care
            case "announcement":
                return

            # client and server
            case "ack":
                try:
                    self._on_notify_ack(message)
                except Exception as e:
                    print("ack", e)
            case "ping":
                pass  # do nothing, code at the end of the method does everything needed
            case "error":
                logging.error(message.error.error_message)
                self._acknowledge(
                    message,
                    datagram.senderAddress().toString().replace("::ffff:", ""),
                    datagram.senderPort()
                )
            case "role_change":
                try:
                    self._on_notify_role_change(message, datagram)
                except Exception as e:
                    print("role_change", e)

            # server
            case "discover":
                self._announce((datagram.senderAddress(), datagram.senderPort()))

            case "steer":
                try:
                    self._on_notify_steer(message, datagram)
                except Exception as e:
                    print("steer", e)

            case "join":
                try:
                    self._on_notify_join(message, datagram)
                except Exception as e:
                    print("join", e)

            # client
            case "state":
                try:
                    self._on_notify_state(message)
                except Exception as e:
                    print("state", e)

        try:
            player = self.player_manager.getPlayerByID(message.sender_id)
            if player is None:
                logging.warning(
                    f"Got {message.WhichOneof('Type')} message from unknown player with id {message.sender_id}")
                return
            player.last_socket_message_got = time.time_ns()
        except Exception as e:
            print("last_socket_message_got", e)

    def _on_notify_state(self, message: snakes.GameMessage):
        if message.state.state.state_order > self._state_order:
            self._state_order = message.state.state.state_order
            if self.player_manager.client_player.role != snakes.MASTER:
                self.field_manager.foodFromMsg(message.state.state.foods)
                self.field_manager.snakesFromMsg(message.state.state.snakes)
                self.player_manager.playersFromMsg(message.state.state.players.players)
                self.__player_id = self.player_manager.getMaxPlayerID() + 1

            self._update_callback()

    def _on_notify_ack(self, message: snakes.GameMessage):
        if message.msg_seq in self._messages_expecting_ack.keys():
            self._messages_expecting_ack.pop(message.msg_seq)
            match message.WhichOneof("Type"):
                case "role_change":
                    self.player_manager.client_player.role = message.role_change.sender_role
                    player = self.player_manager.getPlayerByID(message.receiver_id)
                    if player is not None:
                        player.role = message.role_change.receiver_role
        # first ACK message from MASTER contains player's ID
        if self.player_manager.client_player.id == -1:
            logging.info(f"Ack from MASTER, obtained player_id {message.receiver_id}")
            self.player_manager.client_player.id = message.receiver_id
            self.__player_id = message.receiver_id

    def _on_notify_steer(self, message: snakes.GameMessage, datagram: QNetworkDatagram):
        snakes_with_id = set(filter(lambda s: s.player_id == message.sender_id, self.field_manager.getSnakes()))
        if len(snakes_with_id) > 0:
            for snake in snakes_with_id:
                if Snake.steer_block[message.steer.direction] != snake.direction:
                    snake.turn(message.steer.direction)
            self._acknowledge(message=message, host=datagram.senderAddress(), port=datagram.senderPort())

    def _on_notify_role_change(self, message: snakes.GameMessage, datagram: QNetworkDatagram):
        if message.role_change.sender_role == snakes.MASTER and message.role_change.receiver_role == snakes.VIEWER:
            self.player_manager.client_player.role = snakes.VIEWER
            self._acknowledge(
                message,
                datagram.senderAddress().toString().replace("::ffff:", ""),
                datagram.senderPort()
            )
        elif message.role_change.sender_role == snakes.MASTER and message.role_change.receiver_role == snakes.MASTER:
            if self.player_manager.client_player.role == snakes.DEPUTY:
                self._acknowledge(
                    message,
                    datagram.senderAddress().toString().replace("::ffff:", ""),
                    datagram.senderPort()
                )
                master = self.player_manager.getMaster()
                master.role = snakes.VIEWER
                self._becomeMaster()
        elif self.player_manager.client_player.role == snakes.MASTER == message.role_change.receiver_role:
            if message.role_change.sender_role == snakes.VIEWER:
                player = self.player_manager.getPlayerByID(message.sender_id)
                if player is not None:
                    player.role = snakes.VIEWER
                    snakes_with_id = set(
                        filter(lambda s: s.player_id == player.id, self.field_manager.getSnakes())
                    )
                    for snake in snakes_with_id:
                        snake.state = snakes.GameState.Snake.SnakeState.ZOMBIE
                    self._acknowledge(message, player.ip_address, player.port)
                else:
                    logging.warning(f"Player with id {message.sender_id} requested changing role "
                                    f"but he does not exist")
        elif self.player_manager.client_player.role == snakes.NORMAL:
            if (message.role_change.sender_role == snakes.MASTER and
                    message.role_change.receiver_role == snakes.DEPUTY):
                self.player_manager.client_player.role = snakes.DEPUTY
                master = self.player_manager.getMaster()
                self._acknowledge(message, master.ip_address, master.port)
            elif (message.role_change.sender_role == snakes.MASTER and
                  message.role_change.receiver_role == snakes.NORMAL):
                player = self.player_manager.getPlayerByID(message.sender_id)
                if player is not None:
                    player.role = message.role_change.sender_role
                    self._acknowledge(message, player.ip_address, player.port)
                else:
                    logging.warning(f"Player with id {message.sender_id} requested changing role "
                                    f"but he does not exist")
        else:
            logging.warning("Unsupported role_change request:")
            logging.warning(message)
            return
        self._acknowledge(message, datagram.senderAddress().toString().replace("::ffff:", ""), datagram.senderPort())

    def _on_notify_join(self, message: snakes.GameMessage, datagram: QNetworkDatagram):
        ip_address = datagram.senderAddress().toString().replace("::ffff:", "")
        if message.join.requested_role == snakes.VIEWER:
            player_id = self._player_id()
            player = Player(
                name=message.join.player_name,
                id=player_id,
                ip_address=ip_address,
                port=datagram.senderPort(),
                role=snakes.VIEWER
            )
            self.player_manager.addPlayer(player)
            message.sender_id, message.receiver_id = player_id, self.player_manager.client_player.id
            self._acknowledge(message=message, host=ip_address, port=datagram.senderPort())
            self._sendGameState(player)
            logging.info(f"{player.name}#{player.id} ({player.ip_address}:{player.port}) has joined as VIEWER.")
            return

        pos = self.field_manager.getPosForNewSnake()
        if pos is None:
            errorMessage = snakes.GameMessage(
                msg_seq=message.msg_seq,
                error=snakes.GameMessage.ErrorMsg(
                    error_message="Could not find space on field."
                )
            )
            self._sendMessage(message=errorMessage, host=ip_address, port=datagram.senderPort())
            return

        player_id = self._player_id()
        player = Player(
            name=message.join.player_name,
            id=player_id,
            ip_address=ip_address,
            port=datagram.senderPort(),
            role=snakes.VIEWER if message.join.requested_role == snakes.VIEWER else snakes.NORMAL
        )
        self.player_manager.addPlayer(player)

        snake_x, snake_y = pos
        self.field_manager.spawnSnake(x=snake_x, y=snake_y, player_id=player_id)

        message.sender_id, message.receiver_id = player_id, self.player_manager.client_player.id
        self._acknowledge(message=message, host=ip_address, port=datagram.senderPort())
        self._sendGameState(player)

        if self.player_manager.getDeputy() is None:
            self._assignNewDeputy()
