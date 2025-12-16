from PyQt6 import uic
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QKeyEvent, QPainter, QColor
from PyQt6.QtWidgets import QWidget, QListWidgetItem
import random
from math import ceil
from string import ascii_letters
from typing import Set, Tuple
import snakes.snakes_pb2 as snakes
from network import NetworkHandler, Subscriber
from game.engine import GameEngine, Snake



class GameWidget(QWidget):
    key_pressed = pyqtSignal(QKeyEvent)
    keys_to_directions = {
        16777234: snakes.Direction.LEFT,
        16777235: snakes.Direction.UP,
        16777236: snakes.Direction.RIGHT,
        16777237: snakes.Direction.DOWN
    }

    def paintEvent(self, event) -> None:
        try:
            self.drawServerData()
            self.updateRatingData()
            self.drawField()
        except Exception as e:
            print("paintEvent", e)

    def closeEvent(self, event) -> None:
        self.engine.stop()
        self.client_widget.gameWidget = None
        self.client_widget.playerNameLine.setEnabled(True)
        self.client_widget.hostButton.setEnabled(True)
        self.client_widget.avaliableGamesTable.setEnabled(True)
        self.client_widget.show()

    def __init__(
            self,
            client_widget: QWidget,
            network_handler: NetworkHandler,
            host: str,
            port: int,
            server_name: str,
            game_config: snakes.GameConfig,
            players: snakes.GamePlayers = None,
            is_host: bool = False,
    ):
        super().__init__()
        self.ui = uic.loadUi('ui/game.ui', self)
        self.client_widget = client_widget

        client_name = client_widget.playerNameLine.text()
        if len(client_name) == 0:
            client_name = ''.join(random.choices(ascii_letters))

        if self.client_widget.modeButton.text() == "MODE: NORMAL":
            client_requested_role = snakes.NodeRole.NORMAL
        else:
            client_requested_role = snakes.NodeRole.VIEWER

        self.engine = GameEngine(
            game_name=server_name,
            field_width=game_config.width,
            field_height=game_config.height,
            food_static=game_config.food_static,
            state_delay_ms=game_config.state_delay_ms,
            network_handler=network_handler,
            client_name=client_name,
            client_requested_role=client_requested_role,
            existing_players=players,
            update_callback=self._update_callback
        )

        self.field_widget = FieldWidget(
            canvas=self.artWidget,
            parent=self,
            width=game_config.width,
            height=game_config.height
        )

        self.key_pressed.connect(self.onKey)
        self.leaveButton.clicked.connect(self.engine.becomeViewer)
        self.setWindowTitle(f"Snakes | {server_name} | {client_name}")
        self.show()
        self.engine.start(is_host, host, port)

    def _update_callback(self):
        self.update()

    def keyPressEvent(self, event: QKeyEvent):
        super().keyPressEvent(event)
        self.key_pressed.emit(event)

    def onKey(self, event: QKeyEvent):
        key = event.key()
        if key not in self.keys_to_directions:
            return
        self.engine.moveClientSnake(self.keys_to_directions[key])

    def drawField(self) -> None:
        self.field_widget.startDrawing()
        self.field_widget.drawFood(self.engine.field_manager.getFood())
        self.field_widget.drawSnakes(
            self.engine.field_manager.getSnakes(),
            client_player_id=self.engine.player_manager.client_player.id
        )
        self.field_widget.stopDrawing()

    def drawServerData(self) -> None:
        master = self.engine.player_manager.getMaster()
        if master is not None:
            self.masterLabel.setText(f"MASTER: {master.name}")
        else:
            self.masterLabel.setText(f"MASTER: <NOT FOUND>")
        self.foodLabel.setText(f"FOOD: {self.engine.field_manager.food_static} + {len(self.engine.field_manager.getSnakes())}")
        self.sizeLabel.setText(f"SIZE: {self.engine.field_manager.width}x{self.engine.field_manager.height}")

    def updateRatingData(self):
        self.ratingList.clear()
        sorted_active_players = sorted(
            self.engine.player_manager.getPlayers(
                lambda x: x.role != snakes.VIEWER or x.score > 0
            ),
            key=lambda x: x.score,
            reverse=True
        )
        for player in sorted_active_players:
            self.ratingList.addItem(QListWidgetItem(f"{player.score:5} | {player.name}#{player.id}"))



class FieldWidget:
    def __init__(self, canvas: QWidget, parent: QWidget, width: int, height: int):
        self.canvas = canvas
        self.parent = parent
        self.width = width
        self.height = height
        self._painter = None

    def getPos(self):
        block_dimension = self.getBlockDimension()
        left_x = ceil((self.canvas.width() - block_dimension * self.width) / 2)
        top_y = ceil((self.canvas.height() - block_dimension * self.height) / 2)
        return left_x + self.canvas.x(), top_y + self.canvas.y()

    def getBlockDimension(self):
        max_width_in_pixels = self.canvas.width()
        max_height_in_pixels = self.canvas.height()
        width_in_blocks = self.width
        height_in_blocks = self.height
        w_pixels_per_block = int(max_width_in_pixels / width_in_blocks)
        h_pixels_per_block = int(max_height_in_pixels / height_in_blocks)
        return min(w_pixels_per_block, h_pixels_per_block)

    def drawSnakes(self, snakes_set: Set[Snake], client_player_id: int) -> None:
        if self._painter is None:
            return
        a, b = self.getPos()
        base = self.getBlockDimension()
        for snake in snakes_set:
            x = snake.head_x % self.width
            y = snake.head_y % self.height
            if snake.player_id == client_player_id:
                head_color = QColor("blue")
                tail_color = QColor("aqua")
            else:
                head_color = QColor("red")
                tail_color = QColor("pink")
            self._painter.fillRect(a + x * base, b + y * base, base, base, head_color)
            for tail_block in snake.tail:
                tx = tail_block[0] % self.width
                ty = tail_block[1] % self.height
                self._painter.fillRect(a + tx * base, b + ty * base, base, base, tail_color)

    def drawFood(self, food_set: Set[Tuple[int, int]]) -> None:
        if self._painter is None:
            return
        a, b = self.getPos()
        base = self.getBlockDimension()
        for x, y in food_set:
            self._painter.fillRect(a + x * base, b + y * base, base, base, QColor("green"))

    def startDrawing(self):
        if self._painter is not None:
            return
        self._painter = QPainter(self.parent)
        x, y = self.getPos()
        block_dimension = self.getBlockDimension()
        self._painter.fillRect(x, y, block_dimension * self.width, block_dimension * self.height, QColor('black'))

    def stopDrawing(self):
        if self._painter is None:
            return
        self._painter.end()
        self._painter = None
