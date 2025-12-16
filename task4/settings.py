import random, logging, os, json
from PyQt6.QtWidgets import QWidget
from PyQt6.QtGui import QCloseEvent
from qtpy import uic
import snakes.snakes_pb2 as snakes
from game_widget import GameWidget



class ServerSettingsWindow(QWidget):
    def __init__(self, parent_client: QWidget):
        super().__init__()
        self.client = parent_client
        self.ui = uic.loadUi('ui/config.ui', self)

        self.setWindowTitle("Snakes | Server Settings")
        self.loadSettings()

        self.startButton.clicked.connect(self.startGame)
        self.serverNameLine.editingFinished.connect(self.saveSettings)
        self.widthBox.valueChanged.connect(self.saveSettings)
        self.heightBox.valueChanged.connect(self.saveSettings)
        self.foodBox.valueChanged.connect(self.saveSettings)
        self.delayBox.valueChanged.connect(self.saveSettings)

        self.show()

    def closeEvent(self, a0: QCloseEvent) -> None:
        if self.client.gameWidget is None:
            self.client.playerNameLine.setEnabled(True)
            self.client.hostButton.setEnabled(True)
            self.client.avaliableGamesTable.setEnabled(True)

    def applyBaseSettings(self):
        self.serverNameLine.setText(self.client.playerNameLine.text() + "'s game")
        self.widthBox.setValue(40)
        self.heightBox.setValue(30)
        self.foodBox.setValue(1)
        self.delayBox.setValue(1000)

    def loadSettings(self):
        if not os.path.exists("user_conf.json"):
            self.applyBaseSettings()
            self.saveSettings()
            return
        try:
            with open("user_conf.json", "r") as js_file:
                conf = json.load(js_file)["server"]
                self.serverNameLine.setText(conf["name"])
                w = conf["width"]
                h = conf["height"]
                f = conf["food"]
                d = conf["delay"]
                self.widthBox.setValue(max(self.widthBox.minimum(), min(self.widthBox.maximum(), w)))
                self.heightBox.setValue(max(self.heightBox.minimum(), min(self.heightBox.maximum(), h)))
                self.foodBox.setValue(max(self.foodBox.minimum(), min(self.foodBox.maximum(), f)))
                self.delayBox.setValue(max(self.delayBox.minimum(), min(self.delayBox.maximum(), d)))
        except Exception as e:
            logging.debug(f"Exception while parsing user_conf: {e}")
            self.applyBaseSettings()
            self.saveSettings()

    def saveSettings(self):
        conf = dict()
        if os.path.exists("user_conf.json"):
            with open("user_conf.json", "r") as js_file:
                conf = json.load(js_file)
        server = dict()
        if "server" in conf.keys():
            server = conf["server"]
        server["name"] = self.serverNameLine.text()
        server["width"] = self.widthBox.value()
        server["height"] = self.heightBox.value()
        server["food"] = self.foodBox.value()
        server["delay"] = self.delayBox.value()
        conf["server"] = server
        with open("user_conf.json", "w") as js_file:
            json.dump(conf, js_file, indent=4)

    def startGame(self):
        try:
            self.client.gameWidget = GameWidget(
                client_widget=self.client,
                network_handler=self.client.networkHandler,
                host=self.client.networkHandler.host,
                port=self.client.networkHandler.port,
                server_name=self.serverNameLine.text(),
                game_config=snakes.GameConfig(
                    width=self.widthBox.value(),
                    height=self.heightBox.value(),
                    food_static=self.foodBox.value(),
                    state_delay_ms=self.delayBox.value()
                ),
                is_host=True
            )
            self.client.hide()
            self.close()
        except Exception as e:
            print("startGame_settings", e)
