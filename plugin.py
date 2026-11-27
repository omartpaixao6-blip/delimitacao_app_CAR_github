import os
from qgis.PyQt.QtWidgets import QAction
from qgis.PyQt.QtGui import QIcon
from .dialog import DelimitacaoAPPsDialog


class DelimitacaoAPPs:

    def __init__(self, iface):
        # iface é a interface do QGIS — dá acesso à janela principal, canvas, etc.
        self.iface = iface
        self.action = None
        self.dialog = None

    def initGui(self):
        # Cria o botão que aparece no menu Vetor do QGIS
        icon_path = os.path.join(os.path.dirname(__file__), 'icon.png')
        self.action = QAction(
            QIcon(icon_path),
            'Delimitação de APPs',
            self.iface.mainWindow()
        )
        self.action.triggered.connect(self.run)

        # Adiciona ao menu "Vetor" e à barra de ferramentas de plugins
        self.iface.addPluginToVectorMenu('Delimitação de APPs', self.action)
        self.iface.addToolBarIcon(self.action)

    def unload(self):
        # Remove o botão quando o plugin é desativado
        self.iface.removePluginVectorMenu('Delimitação de APPs', self.action)
        self.iface.removeToolBarIcon(self.action)

    def run(self):
        # Abre a janela do plugin
        if self.dialog is None:
            self.dialog = DelimitacaoAPPsDialog(self.iface)
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()
