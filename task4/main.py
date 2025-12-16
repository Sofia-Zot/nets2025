import sys, os, json, time, random, logging
from PyQt6.QtWidgets import QApplication, QWidget, QTableWidgetItem
from PyQt6.QtGui import QMovie
from PyQt6.QtNetwork import QNetworkDatagram
from qtpy import uic
import snakes.snakes_pb2 as snakes
from network import NetworkHandler, Subscriber
from game_widget import GameWidget
from settings import ServerSettingsWindow



class ClientWindow(QWidget, Subscriber):
    def __init__(self):
        super().__init__()
        self.ui = uic.loadUi('ui/client.ui', self)

        self.snakes_gif_movie = QMovie('ui/snakes.gif')
        self.gameLabel.setMovie(self.snakes_gif_movie)
        self.snakes_gif_movie.start()

        self.networkHandler = NetworkHandler()
        self.networkHandler.subscribe(self)

        self.gameWidget = None
        self.games = dict()
        self.trying_to_join = None

        self.setWindowTitle("Snakes | Client")

        self.playerNameLine.editingFinished.connect(self.saveUserConfig)
        self.hostButton.clicked.connect(self.openServerSettingsScreen)
        self.avaliableGamesTable.cellDoubleClicked.connect(self.onServerDoubleClick)
        self.modeButton.clicked.connect(self.changeConnectionMode)

        self.loadUserConfig()
        self.show()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        self.adjustTableSize()

    def notify(self, datagram: QNetworkDatagram):
        try:
            raw = bytes(datagram.data())
            message = snakes.GameMessage()
            message.ParseFromString(raw)
            msg_type = message.WhichOneof("Type")
            if msg_type == "announcement":
                games = message.announcement.games
                for game in games:
                    if not game.can_join:
                        continue
                    masters = [p for p in game.players.players if p.role == snakes.NodeRole.MASTER]
                    if len(masters) != 1:
                        logging.info(f"got strange announce packet with {len(masters)} MASTERS from {game.game_name}")
                        return
                    master = masters[0]
                    self.games[master.name] = {
                        "host": datagram.senderAddress(),
                        "port": datagram.senderPort(),
                        "game": game,
                        "last_update": time.time_ns()
                    }
        except Exception as e:
            print("notify", e)

    def adjustTableSize(self):
        width = self.avaliableGamesTable.width()
        col0 = int(width / 100 * 40) - 1
        col1 = int(width / 100 * 20) - 1
        col2 = int(width / 100 * 20) - 1
        col3 = int(width / 100 * 20)
        self.avaliableGamesTable.setColumnWidth(0, col0)
        self.avaliableGamesTable.setColumnWidth(1, col1)
        self.avaliableGamesTable.setColumnWidth(2, col2)
        self.avaliableGamesTable.setColumnWidth(3, col3)

        try:
            name_to_row = dict()
            for row in range(self.avaliableGamesTable.rowCount()):
                item = self.avaliableGamesTable.item(row, 0)
                if item:
                    name_to_row[item.text()] = row

            current_time = time.time_ns()
            to_be_deleted = []
            for master, data in self.games.items():
                if current_time - data["last_update"] > 3e9:
                    to_be_deleted.append(master)
                    continue

                if master in name_to_row:
                    continue
                else:
                    row = self.avaliableGamesTable.rowCount()
                    self.avaliableGamesTable.setRowCount(row + 1)

                players = f'{len(data["game"].players.players)}'
                size = f'{data["game"].config.width}x{data["game"].config.height}'
                food = f'{data["game"].config.food_static} + 1x'
                self.avaliableGamesTable.setItem(row, 0, QTableWidgetItem(master))
                self.avaliableGamesTable.setItem(row, 1, QTableWidgetItem(players))
                self.avaliableGamesTable.setItem(row, 2, QTableWidgetItem(size))
                self.avaliableGamesTable.setItem(row, 3, QTableWidgetItem(food))

            for i in to_be_deleted:
                if i in self.games:
                    self.games.pop(i)
                if i in name_to_row:
                    self.avaliableGamesTable.removeRow(name_to_row[i])
        except Exception as e:
            print("adjustTableSize", e, type(e))

    def changeConnectionMode(self):
        current = self.modeButton.text()
        if current == "MODE: NORMAL":
            self.modeButton.setText("MODE: VIEVER")
        else:
            self.modeButton.setText("MODE: NORMAL")

    def onServerDoubleClick(self, row, col):
        try:
            name = self.avaliableGamesTable.item(row, 0).text()
            data = self.games[name]
            self.trying_to_join = name
            self.startGame()
        except Exception as e:
            print(e)

    def joinServer(self, host: str, port: int, game: snakes.GameAnnouncement, player: bool = True):
        message = snakes.GameMessage()
        message.msg_seq = 0
        message.join.player_name = self.playerNameLine.text()
        message.join.game_name = game.game_name
        if player:
            message.join.requested_role = snakes.NodeRole.NORMAL
        else:
            message.join.requested_role = snakes.NodeRole.VIEWER
        self.networkHandler.unicast(message, host, port)

    def startGame(self):
        try:
            if self.trying_to_join is None:
                return
            game = self.games[self.trying_to_join]["game"]
            self.gameWidget = GameWidget(
                self,
                self.networkHandler,
                self.games[self.trying_to_join]["host"].toString().replace("::ffff:", ""),
                self.games[self.trying_to_join]["port"],
                game.game_name,
                snakes.GameConfig(
                    width=game.config.width,
                    height=game.config.height,
                    food_static=game.config.food_static,
                    state_delay_ms=game.config.state_delay_ms
                ),
                game.players,
                is_host=False
            )
            self.hide()
        except Exception as e:
            print("startGame_main", e)

    def loadUserConfig(self):
        if not os.path.exists("user_conf.json"):
            self.applyBaseConfig()
            self.saveUserConfig()
            return

        try:
            with open("user_conf.json", "r") as js_file:
                conf = json.load(js_file)
                self.playerNameLine.setText(conf["playername"])
        except Exception as e:
            logging.debug(f"Exception while parsing user_conf: {e}")
            self.applyBaseConfig()
            self.saveUserConfig()

    def applyBaseConfig(self):
        self.playerNameLine.setText(f"Player-{random.randint(1, 16677)}")

    def saveUserConfig(self):
        conf = dict()
        if os.path.exists("user_conf.json"):
            with open("user_conf.json", "r") as js_file:
                conf = json.load(js_file)

        conf["playername"] = self.playerNameLine.text()

        with open("user_conf.json", "w") as js_file:
            json.dump(conf, js_file, indent=4)

    def openServerSettingsScreen(self):
        try:
            settingsWindow = ServerSettingsWindow(self)
            self.playerNameLine.setEnabled(False)
            self.hostButton.setEnabled(False)
            self.avaliableGamesTable.setEnabled(False)
        except Exception as e:
            logging.info(e)


if __name__ == "__main__":
    logging.basicConfig(format="[%(levelname)s]: %(message)s", level=logging.INFO)
    app = QApplication(sys.argv)
    clientWindow = ClientWindow()
    app.exec()
