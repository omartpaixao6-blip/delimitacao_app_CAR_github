import os
import shutil
import string
import tempfile
import urllib.request
import zipfile

from qgis import processing
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QComboBox, QPushButton, QProgressBar, QMessageBox, QSizePolicy,
    QCompleter
)
from qgis.PyQt.QtCore import Qt, QThread, pyqtSignal, QVariant
from qgis.PyQt.QtGui import QColor
from qgis.core import (
    QgsVectorLayer, QgsProject, QgsVectorFileWriter,
    QgsCoordinateReferenceSystem, QgsField, QgsProperty,
    QgsSimpleFillSymbolLayer, QgsFillSymbol,
    QgsMarkerSymbol, QgsSimpleMarkerSymbolLayer,
    QgsPalLayerSettings, QgsVectorLayerSimpleLabeling,
    QgsTextFormat, QgsTextBufferSettings,
    QgsUnitTypes, edit
)


# ─────────────────────────────────────────────────────────────────────────────
# CAMINHOS RELATIVOS, DETECÇÃO DE DISCO E DOWNLOAD (GITHUB RELEASES)
# ─────────────────────────────────────────────────────────────────────────────
PASTA_PLUGIN      = os.path.dirname(os.path.abspath(__file__))
PASTA_DATA_PADRAO = os.path.join(PASTA_PLUGIN, 'data')
NOME_GPKG         = 'banco_hidro_mg.gpkg'
CAMADA_MUNI       = 'municipios_mg'
CAMADA_HIDRO      = 'hidrografia_pol'
CAMADA_NASC       = 'nascentes_pto'

URL_DADOS_ZIP = 'https://github.com/omartpaixao6-blip/delimitacao-apps-mg/releases/download/v1.0.0/data.zip'

# Espaço mínimo exigido (3.2 GB em bytes) para comportar o .zip + .gpkg extraído
ESPACO_MINIMO_BYTES = int(3.2 * 1024 * 1024 * 1024)


def _pastas_candidatas():
    """Retorna a pasta padrão do plugin e eventuais pastas alternativas em outros discos."""
    candidatas = [PASTA_DATA_PADRAO]
    if os.name == 'nt':  # Windows: verifica unidades D: até Z:
        drive_plugin = os.path.splitdrive(PASTA_PLUGIN)[0].upper()
        for letra in string.ascii_uppercase[3:]:  # D..Z
            drive = f'{letra}:\\'
            if f'{letra}:' != drive_plugin and os.path.exists(drive):
                candidatas.append(os.path.join(drive, 'QGIS_APPs_MG_Dados'))
    return candidatas


def obter_caminho_gpkg():
    """Procura o banco_hidro_mg.gpkg na pasta padrão ou em discos alternativos."""
    for pasta in _pastas_candidatas():
        gpkg = os.path.join(pasta, NOME_GPKG)
        if os.path.exists(gpkg) and os.path.getsize(gpkg) > 100 * 1024 * 1024:
            return gpkg
    return None


def dados_existem():
    """Verifica se o GeoPackage completo já está disponível em algum disco."""
    return obter_caminho_gpkg() is not None


def _escolher_pasta_destino():
    """Escolhe a primeira pasta em um disco com pelo menos 3.2 GB livres."""
    for pasta in _pastas_candidatas():
        raiz = os.path.splitdrive(pasta)[0] + os.sep if os.name == 'nt' else '/'
        try:
            livre = shutil.disk_usage(raiz).free
            if livre >= ESPACO_MINIMO_BYTES:
                return pasta
        except OSError:
            continue
    raise RuntimeError(
        'Espaço em disco insuficiente (necessário pelo menos 3,2 GB livres em algum disco).'
    )


def garantir_dados_baixados(callback_progresso=None):
    """Baixa e extrai data.zip no primeiro disco com espaço suficiente."""
    if dados_existem():
        return

    pasta_destino = _escolher_pasta_destino()
    os.makedirs(pasta_destino, exist_ok=True)
    zip_temp = os.path.join(pasta_destino, 'sgorl_hidro_data.zip')

    def _reportar_download(blocos_lidos, tamanho_bloco, tamanho_total):
        if callback_progresso and tamanho_total > 0:
            pct_dl = min(blocos_lidos * tamanho_bloco / tamanho_total, 1.0)
            progresso_barra = 2 + int(pct_dl * 5)
            mb_baixados = (blocos_lidos * tamanho_bloco) / (1024 * 1024)
            mb_total    = tamanho_total / (1024 * 1024)
            callback_progresso(
                progresso_barra,
                f'Baixando base cartográfica ({mb_baixados:.0f} / {mb_total:.0f} MB)...'
            )

    if callback_progresso:
        callback_progresso(2, f'Baixando base cartográfica em {pasta_destino}...')

    urllib.request.urlretrieve(URL_DADOS_ZIP, zip_temp, reporthook=_reportar_download)

    if callback_progresso:
        callback_progresso(8, 'Extraindo banco de dados cartográfico...')

    with zipfile.ZipFile(zip_temp, 'r') as zf:
        zf.extractall(pasta_destino)

    if os.path.exists(zip_temp):
        os.remove(zip_temp)


# ─────────────────────────────────────────────────────────────────────────────
# ESTILIZAÇÃO
# ─────────────────────────────────────────────────────────────────────────────
def _fazer_rotulo(campo):
    """Cria configuração de rótulo com buffer de texto branco 1mm, junção arredondada."""
    buffer_cfg = QgsTextBufferSettings()
    buffer_cfg.setEnabled(True)
    buffer_cfg.setSize(1.0)
    buffer_cfg.setSizeUnit(QgsUnitTypes.RenderMillimeters)
    buffer_cfg.setColor(QColor('#fafafa'))
    buffer_cfg.setOpacity(1.0)
    buffer_cfg.setJoinStyle(Qt.RoundJoin)
    buffer_cfg.setBlendMode(0)  # Normal

    fmt = QgsTextFormat()
    fmt.setBuffer(buffer_cfg)

    pal = QgsPalLayerSettings()
    pal.fieldName    = campo
    pal.isExpression = False
    pal.enabled      = True
    pal.setFormat(fmt)

    return pal


def estilizar_poligono(layer, hex_cor, opacidade_pct, rotulo_campo=None):
    """Polígono: preenchimento colorido sem contorno. Rótulo opcional."""
    cor = QColor(hex_cor)
    cor.setAlpha(int(opacidade_pct / 100 * 255))

    fill = QgsSimpleFillSymbolLayer()
    fill.setColor(cor)
    fill.setStrokeStyle(Qt.NoPen)

    simbolo = QgsFillSymbol()
    simbolo.changeSymbolLayer(0, fill)
    layer.renderer().setSymbol(simbolo)

    if rotulo_campo:
        layer.setLabeling(QgsVectorLayerSimpleLabeling(_fazer_rotulo(rotulo_campo)))
        layer.setLabelsEnabled(True)

    layer.triggerRepaint()


def estilizar_ponto(layer, hex_cor, opacidade_pct):
    """Ponto: marcador colorido."""
    cor = QColor(hex_cor)
    cor.setAlpha(int(opacidade_pct / 100 * 255))

    marker = QgsSimpleMarkerSymbolLayer()
    marker.setColor(cor)
    marker.setSize(2.5)

    simbolo = QgsMarkerSymbol()
    simbolo.changeSymbolLayer(0, marker)
    layer.renderer().setSymbol(simbolo)
    layer.triggerRepaint()


# ─────────────────────────────────────────────────────────────────────────────
# WORKER (100% API NATIVA DO QGIS)
# ─────────────────────────────────────────────────────────────────────────────
class ProcessamentoWorker(QThread):
    progresso       = pyqtSignal(int, str)
    dados_baixados  = pyqtSignal()
    finalizado      = pyqtSignal(list)
    erro            = pyqtSignal(str)

    def __init__(self, nome_municipio):
        super().__init__()
        self.nome_municipio = nome_municipio

    @staticmethod
    def _definir_largura_buffer(categoria_val):
        val = str(categoria_val or '').lower()
        if 'até 10'       in val or 'ate 10' in val: return 30
        if '10 a 50'      in val:                    return 50
        if '50 a 200'     in val:                    return 100
        if '200 a 600'    in val:                    return 200
        if 'acima de 600' in val:                    return 500
        return 30

    def _salvar_shapefile(self, camada, caminho_saida, epsg_destino=4674):
        """Reprojeta (se necessário) e salva a camada em Shapefile UTF-8."""
        crs_destino = QgsCoordinateReferenceSystem(f'EPSG:{epsg_destino}')
        if camada.crs() != crs_destino:
            res_reproj = processing.run('native:reprojectlayer', {
                'INPUT': camada,
                'TARGET_CRS': crs_destino,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            })
            camada = res_reproj['OUTPUT']

        opcoes = QgsVectorFileWriter.SaveVectorOptions()
        opcoes.driverName   = 'ESRI Shapefile'
        opcoes.fileEncoding = 'UTF-8'

        QgsVectorFileWriter.writeAsVectorFormatV3(
            camada,
            caminho_saida,
            QgsProject.instance().transformContext(),
            opcoes
        )

    def run(self):
        try:
            # ── ETAPA 0: garantir base de dados local ─────────────────────
            estava_sem_dados = not dados_existem()
            garantir_dados_baixados(callback_progresso=self.progresso.emit)
            if estava_sem_dados:
                self.dados_baixados.emit()

            caminho_gpkg = obter_caminho_gpkg()
            if not caminho_gpkg:
                self.erro.emit('Arquivo banco_hidro_mg.gpkg não encontrado após o download.')
                return

            nome       = self.nome_municipio
            pasta_temp = tempfile.mkdtemp(prefix='app_qgis_')
            crs_4674   = QgsCoordinateReferenceSystem('EPSG:4674')
            crs_31983  = QgsCoordinateReferenceSystem('EPSG:31983')

            # ── ETAPA 1: município (lendo de dentro do GeoPackage) ────────
            self.progresso.emit(10, 'Carregando municípios...')
            lyr_muni = QgsVectorLayer(f'{caminho_gpkg}|layername={CAMADA_MUNI}', 'municipios', 'ogr')
            if not lyr_muni.isValid():
                self.erro.emit('Não foi possível abrir a camada de municípios no GeoPackage.')
                return

            if not lyr_muni.crs().isValid():
                lyr_muni.setCrs(crs_4674)

            nome_escapado = nome.replace("'", "''")
            res_mun = processing.run('native:extractbyexpression', {
                'INPUT': lyr_muni,
                'EXPRESSION': f"upper(trim(\"nome\")) = upper('{nome_escapado}')",
                'OUTPUT': 'TEMPORARY_OUTPUT'
            })
            mun_alvo = res_mun['OUTPUT']

            if mun_alvo.featureCount() == 0:
                self.erro.emit(f'Município "{nome}" não encontrado.')
                return

            # ── ETAPA 2: leitura de hidrografia e nascentes do GeoPackage ─
            self.progresso.emit(22, 'Carregando hidrografia e nascentes...')
            lyr_hidro = QgsVectorLayer(f'{caminho_gpkg}|layername={CAMADA_HIDRO}', 'hidro', 'ogr')
            lyr_nasc  = QgsVectorLayer(f'{caminho_gpkg}|layername={CAMADA_NASC}',  'nasc',  'ogr')

            if not lyr_hidro.isValid() or not lyr_nasc.isValid():
                self.erro.emit('Erro ao ler camadas de hidrografia/nascentes do GeoPackage.')
                return

            # ── ETAPA 3: recorte geográfico ───────────────────────────────
            self.progresso.emit(35, f'Recortando para {nome}...')
            if lyr_hidro.crs() != mun_alvo.crs():
                lyr_hidro = processing.run('native:reprojectlayer', {
                    'INPUT': lyr_hidro,
                    'TARGET_CRS': mun_alvo.crs(),
                    'OUTPUT': 'TEMPORARY_OUTPUT'
                })['OUTPUT']

            if lyr_nasc.crs() != mun_alvo.crs():
                lyr_nasc = processing.run('native:reprojectlayer', {
                    'INPUT': lyr_nasc,
                    'TARGET_CRS': mun_alvo.crs(),
                    'OUTPUT': 'TEMPORARY_OUTPUT'
                })['OUTPUT']

            hidro_clip = processing.run('native:clip', {
                'INPUT': lyr_hidro,
                'OVERLAY': mun_alvo,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            })['OUTPUT']

            nasc_clip = processing.run('native:clip', {
                'INPUT': lyr_nasc,
                'OVERLAY': mun_alvo,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            })['OUTPUT']

            tem_hidro = hidro_clip.featureCount() > 0
            tem_nasc  = nasc_clip.featureCount() > 0

            if not tem_hidro and not tem_nasc:
                self.erro.emit('Nenhuma feição encontrada no município selecionado.')
                return

            # ── ETAPA 4: APP dos rios ─────────────────────────────────────
            self.progresso.emit(55, 'Calculando APPs dos rios...')
            app_rios = None
            if tem_hidro:
                rios_utm = processing.run('native:reprojectlayer', {
                    'INPUT': hidro_clip,
                    'TARGET_CRS': crs_31983,
                    'OUTPUT': 'TEMPORARY_OUTPUT'
                })['OUTPUT']

                with edit(rios_utm):
                    if rios_utm.fields().indexOf('largura_v') == -1:
                        rios_utm.addAttribute(QgsField('largura_v', QVariant.Int))
                    if rios_utm.fields().indexOf('medida') == -1:
                        rios_utm.addAttribute(QgsField('medida', QVariant.String, len=20))
                    rios_utm.updateFields()

                    idx_cat     = rios_utm.fields().indexOf('categoria_')
                    idx_largura = rios_utm.fields().indexOf('largura_v')
                    idx_medida  = rios_utm.fields().indexOf('medida')

                    for feat in rios_utm.getFeatures():
                        cat_val = feat[idx_cat] if idx_cat != -1 else ''
                        larg = self._definir_largura_buffer(cat_val)
                        rios_utm.changeAttributeValue(feat.id(), idx_largura, larg)
                        rios_utm.changeAttributeValue(feat.id(), idx_medida, f'{larg} metros')

                app_rios = processing.run('native:buffer', {
                    'INPUT': rios_utm,
                    'DISTANCE': QgsProperty.fromField('largura_v'),
                    'SEGMENTS': 16,
                    'END_CAP_STYLE': 0,
                    'JOIN_STYLE': 0,
                    'MITER_LIMIT': 2,
                    'DISSOLVE': False,
                    'OUTPUT': 'TEMPORARY_OUTPUT'
                })['OUTPUT']

            # ── ETAPA 5: APP das nascentes ────────────────────────────────
            self.progresso.emit(72, 'Calculando APPs das nascentes...')
            app_nasc = None
            if tem_nasc:
                nasc_utm = processing.run('native:reprojectlayer', {
                    'INPUT': nasc_clip,
                    'TARGET_CRS': crs_31983,
                    'OUTPUT': 'TEMPORARY_OUTPUT'
                })['OUTPUT']

                with edit(nasc_utm):
                    if nasc_utm.fields().indexOf('medida') == -1:
                        nasc_utm.addAttribute(QgsField('medida', QVariant.String, len=20))
                    nasc_utm.updateFields()

                    idx_medida = nasc_utm.fields().indexOf('medida')
                    for feat in nasc_utm.getFeatures():
                        nasc_utm.changeAttributeValue(feat.id(), idx_medida, '50 metros')

                app_nasc = processing.run('native:buffer', {
                    'INPUT': nasc_utm,
                    'DISTANCE': 50,
                    'SEGMENTS': 16,
                    'END_CAP_STYLE': 0,
                    'JOIN_STYLE': 0,
                    'MITER_LIMIT': 2,
                    'DISSOLVE': False,
                    'OUTPUT': 'TEMPORARY_OUTPUT'
                })['OUTPUT']

            # ── ETAPA 6: salvar shapefiles ────────────────────────────────
            self.progresso.emit(85, 'Salvando camadas...')
            arquivos_gerados = []  # (caminho, nome_camada, tipo)

            if tem_hidro:
                path = os.path.join(pasta_temp, '01_Hidro_Recorte.shp')
                self._salvar_shapefile(hidro_clip, path, 4674)
                arquivos_gerados.append((path, f'Hidrografia — {nome}', 'hidro'))

            if app_rios is not None and app_rios.featureCount() > 0:
                path = os.path.join(pasta_temp, '02_APP_Hidro.shp')
                self._salvar_shapefile(app_rios, path, 4674)
                arquivos_gerados.append((path, f'APP Rios — {nome}', 'app_rios'))

            if tem_nasc:
                path = os.path.join(pasta_temp, '03_Nasc_Recorte.shp')
                self._salvar_shapefile(nasc_clip, path, 4674)
                arquivos_gerados.append((path, f'Nascentes — {nome}', 'nascentes'))

            if app_nasc is not None and app_nasc.featureCount() > 0:
                path = os.path.join(pasta_temp, '04_APP_Nascentes.shp')
                self._salvar_shapefile(app_nasc, path, 4674)
                arquivos_gerados.append((path, f'APP Nascentes — {nome}', 'app_nasc'))

            self.progresso.emit(100, 'Concluído!')
            self.finalizado.emit(arquivos_gerados)

        except Exception as e:
            import traceback
            self.erro.emit(f'Erro:\n{str(e)}\n\n{traceback.format_exc()}')


# ─────────────────────────────────────────────────────────────────────────────
# DIALOG
# ─────────────────────────────────────────────────────────────────────────────
class DelimitacaoAPPsDialog(QDialog):

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface  = iface
        self.worker = None
        self._montar_interface()
        self._popular_municipios()

    def _montar_interface(self):
        self.setWindowTitle('Delimitação de APPs — Lei 12.651/2012')
        self.setMinimumWidth(440)
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)

        layout = QVBoxLayout()
        layout.setSpacing(10)
        layout.setContentsMargins(16, 16, 16, 16)

        titulo = QLabel('<b>Delimitação de Áreas de Preservação Permanente</b>')
        titulo.setAlignment(Qt.AlignCenter)
        layout.addWidget(titulo)

        sub = QLabel('Código Florestal — Lei 12.651/2012 | Minas Gerais')
        sub.setAlignment(Qt.AlignCenter)
        layout.addWidget(sub)

        layout.addSpacing(8)
        layout.addWidget(QLabel('Selecione ou digite o município:'))

        self.combo_municipio = QComboBox()
        self.combo_municipio.setEditable(True)
        self.combo_municipio.setInsertPolicy(QComboBox.NoInsert)
        self.combo_municipio.completer().setCompletionMode(QCompleter.PopupCompletion)
        self.combo_municipio.completer().setFilterMode(Qt.MatchContains)
        self.combo_municipio.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout.addWidget(self.combo_municipio)

        layout.addSpacing(8)

        self.barra = QProgressBar()
        self.barra.setValue(0)
        self.barra.setVisible(False)
        layout.addWidget(self.barra)

        self.lbl_status = QLabel('')
        self.lbl_status.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.lbl_status)

        layout.addSpacing(4)

        hbox = QHBoxLayout()
        self.btn_executar = QPushButton('Executar')
        self.btn_executar.setDefault(True)
        self.btn_fechar   = QPushButton('Fechar')
        hbox.addWidget(self.btn_executar)
        hbox.addWidget(self.btn_fechar)
        layout.addLayout(hbox)

        self.setLayout(layout)
        self.btn_executar.clicked.connect(self.executar)
        self.btn_fechar.clicked.connect(self.close)

    def _popular_municipios(self):
        texto_atual = self.combo_municipio.currentText()
        self.combo_municipio.clear()
        self.combo_municipio.addItem('')

        caminho_gpkg = obter_caminho_gpkg()
        if not caminho_gpkg:
            self.lbl_status.setText(
                'ℹ️ A base de dados será baixada automaticamente na primeira execução.'
            )
            return

        try:
            lyr = QgsVectorLayer(f'{caminho_gpkg}|layername={CAMADA_MUNI}', 'municipios_lista', 'ogr')
            if not lyr.isValid():
                self.lbl_status.setText('⚠️ Não foi possível ler a lista de municípios.')
                return

            idx_nome = lyr.fields().indexOf('nome')
            if idx_nome == -1:
                return

            nomes = sorted({
                str(feat[idx_nome]).strip()
                for feat in lyr.getFeatures()
                if feat[idx_nome] is not None and str(feat[idx_nome]).strip()
            })

            for n in nomes:
                self.combo_municipio.addItem(n)

            if texto_atual:
                self.combo_municipio.setCurrentText(texto_atual)

        except Exception as e:
            QMessageBox.warning(
                self, 'Aviso',
                f'Não foi possível carregar os municípios:\n{str(e)}'
            )

    def executar(self):
        nome = self.combo_municipio.currentText().strip()
        if not nome:
            QMessageBox.warning(self, 'Atenção', 'Selecione ou digite o nome do município.')
            return

        self.btn_executar.setEnabled(False)
        self.barra.setVisible(True)
        self.barra.setValue(0)
        self.lbl_status.setText('Iniciando...')

        self.worker = ProcessamentoWorker(nome)
        self.worker.progresso.connect(self._atualizar_progresso)
        self.worker.dados_baixados.connect(self._popular_municipios)
        self.worker.finalizado.connect(self._carregar_camadas)
        self.worker.erro.connect(self._mostrar_erro)
        self.worker.start()

    def _atualizar_progresso(self, valor, msg):
        self.barra.setValue(valor)
        self.lbl_status.setText(msg)

    def _carregar_camadas(self, arquivos_gerados):
        camadas = []
        for caminho, nome_camada, tipo in arquivos_gerados:
            lyr = QgsVectorLayer(caminho, nome_camada, 'ogr')
            if not lyr.isValid():
                continue

            QgsProject.instance().addMapLayer(lyr)

            if tipo == 'hidro':
                estilizar_poligono(lyr, '#00f8ff', 100)
            elif tipo == 'app_rios':
                estilizar_poligono(lyr, '#00c6ff', 40, rotulo_campo='categoria_')
            elif tipo == 'nascentes':
                estilizar_ponto(lyr, '#1c00ff', 100)
            elif tipo == 'app_nasc':
                estilizar_poligono(lyr, '#00a2ff', 47, rotulo_campo='medida')

            camadas.append(lyr)

        self.btn_executar.setEnabled(True)

        if camadas:
            self.lbl_status.setText(f'✅ {len(camadas)} camadas carregadas!')
            ext = camadas[0].extent()
            for c in camadas[1:]:
                ext.combineExtentWith(c.extent())
            self.iface.mapCanvas().setExtent(ext)
            self.iface.mapCanvas().refresh()
        else:
            self.lbl_status.setText('⚠️ Nenhuma camada válida foi gerada.')

    def _mostrar_erro(self, msg):
        self.btn_executar.setEnabled(True)
        self.barra.setValue(0)
        self.lbl_status.setText('❌ Erro no processamento.')
        QMessageBox.critical(self, 'Erro', msg)
