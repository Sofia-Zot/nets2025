import logging
from typing import Set, Union, List
from google.protobuf.internal.containers import RepeatedCompositeFieldContainer
import snakes.snakes_pb2 as snakes



class Player:
    def __init__(
            self,
            name: str,
            id: int,
            ip_address: str,
            port: int,
            role: snakes.NodeRole = snakes.NORMAL,
            type: snakes.PlayerType = snakes.HUMAN,
            score: int = 0,
            is_client: bool = False
    ):
        self.name = name
        self.id = id
        self.ip_address = ip_address
        self.port = port
        self.role = role
        self.score = score
        self.type = type
        self.is_client = is_client
        self.last_socket_message_got = 0
        self.last_socket_message_sent = 0

    def asMsg(self):
        return snakes.GamePlayer(
            name=self.name,
            id=self.id,
            ip_address=self.ip_address,
            port=self.port,
            role=self.role,
            score=self.score
        )


class PlayerManager:
    def __init__(self, client_player: Player, existing_players: snakes.GamePlayers):
        self.client_player = client_player
        self._players: set[Player] = set()
        self.addPlayer(client_player)
        if existing_players is not None:
            try:
                self.playersFromMsg(existing_players.players)
            except Exception as e:
                print(e)

    def asMsg(self) -> List[snakes.GamePlayer]:
        game_players = list()
        for player in self._players:
            game_player = snakes.GamePlayer(
                name=player.name,
                id=player.id,
                ip_address=player.ip_address,
                port=player.port,
                role=player.role,
                type=player.type,
                score=player.score
            )
            game_players.append(game_player)
        return game_players

    def playersFromMsg(self, players: RepeatedCompositeFieldContainer[snakes.GamePlayer]):
        for player in players:
            found = False
            for old_player in self._players:
                if player.id == old_player.id:
                    old_player.name = player.name
                    old_player.role = player.role
                    old_player.type = player.type
                    old_player.score = player.score
                    found = True
                    break
            if not found:
                self._players.add(
                    Player(
                        name=player.name,
                        id=player.id,
                        ip_address=player.ip_address,
                        port=player.port,
                        role=player.role,
                        type=player.type,
                        score=player.score
                    )
                )

    def getPlayers(self, fn=lambda x: True) -> Set[Player]:
        return set(filter(fn, self._players))

    def getPlayerByID(self, id: int) -> Union[Player, None]:
        players_with_id = self.getPlayers(lambda x: x.id == id)
        if len(players_with_id) == 0:
            return None
        if len(players_with_id) > 1:
            logging.warning(f"More than 1 player have id {id}")
        return players_with_id.pop()

    def getPlayersWithRole(self, role: snakes.NodeRole) -> Set[Player]:
        players_with_role = self.getPlayers(lambda x: x.role == role)
        return players_with_role

    def getMaster(self) -> Union[Player, None]:
        masters = self.getPlayersWithRole(snakes.MASTER)
        if len(masters) == 0:
            return None
        if len(masters) > 1:
            logging.warning("More than 1 player with MASTER role were found.")
        return masters.pop()

    def getDeputy(self) -> Union[Player, None]:
        deputies = self.getPlayersWithRole(snakes.DEPUTY)
        if len(deputies) == 0:
            return None
        if len(deputies) > 1:
            logging.warning("More than 1 player with DEPUTY role were found.")
        return deputies.pop()

    def addPlayer(self, player: Player) -> None:
        self._players.add(player)

    def removePlayerByID(self, id: int) -> None:
        players_with_id = set(filter(lambda x: x.id == id, self._players))
        if len(players_with_id) > 1:
            logging.warning(f"More than 1 player have id {id}")
        self._players.difference_update(players_with_id)

    def getMaxPlayerID(self) -> int:
        max_ = -1
        for player in self._players:
            if player.id > max_:
                max_ = player.id
        return max_
