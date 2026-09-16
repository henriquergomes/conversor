"""
Interface Gráfica do Usuário (GUI) - Conversor Laser DXF com Pré-Visualizador
=============================================================================

Aplicação desktop assíncrona desenvolvida em PySide6 (Qt 6) com QThread.
Possui um visualizador gráfico interativo (QGraphicsView) integrado para inspeção
dos polígonos fechados e camadas de corte/gravação (Hatch Preview) antes do envio para a máquina.
"""

from pathlib import Path
from typing import Optional, Tuple
import sys

import ezdxf
from PySide6.QtCore import QPointF, QRectF, QThread, QUrl, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QDesktopServices,
    QDragEnterEvent,
    QDropEvent,
    QFont,
    QPainter,
    QPainterPath,
    QPen,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
    QGraphicsScene,
    QGraphicsView,
)

from converter import process_file


# -------------------------------------------------------------
# Folha de Estilos Moderna (QSS)
# -------------------------------------------------------------
MODERN_STYLE_SHEET = """
QMainWindow {
    background-color: #0f1117;
}

QWidget#CentralWidget {
    background-color: #0f1117;
}

/* Cards e Painéis */
QFrame#LeftCard {
    background-color: #171923;
    border: 1px solid #262a38;
    border-radius: 12px;
}

QFrame#RightCard {
    background-color: #171923;
    border: 1px solid #262a38;
    border-radius: 12px;
}

/* Título e Subtítulo */
QLabel#TitleLabel {
    color: #f8fafc;
    font-size: 18px;
    font-weight: 700;
}

QLabel#SubtitleLabel {
    color: #94a3b8;
    font-size: 11px;
}

/* Botão Selecionar Arquivo */
QPushButton#BtnSelect {
    background-color: #2563eb;
    color: #ffffff;
    font-size: 13px;
    font-weight: 600;
    border: none;
    border-radius: 8px;
    padding: 11px 18px;
}

QPushButton#BtnSelect:hover {
    background-color: #1d4ed8;
}

QPushButton#BtnSelect:pressed {
    background-color: #1e40af;
}

QPushButton#BtnSelect:disabled {
    background-color: #1e293b;
    color: #64748b;
}

/* Campo de Exibição do Caminho */
QLineEdit#PathDisplay {
    background-color: #0f1117;
    color: #e2e8f0;
    border: 1px solid #334155;
    border-radius: 6px;
    padding: 8px 10px;
    font-size: 11px;
}

QLineEdit#PathDisplay:focus {
    border: 1px solid #3b82f6;
}

/* Botão Converter para DXF */
QPushButton#BtnConvert {
    background-color: #059669;
    color: #ffffff;
    font-size: 14px;
    font-weight: 600;
    border: none;
    border-radius: 8px;
    padding: 12px 18px;
}

QPushButton#BtnConvert:hover {
    background-color: #047857;
}

QPushButton#BtnConvert:pressed {
    background-color: #065f46;
}

QPushButton#BtnConvert:disabled {
    background-color: #1e293b;
    color: #64748b;
}

/* Botões de Ação do Visor */
QPushButton#ViewerActionBtn {
    background-color: #1e293b;
    color: #cbd5e1;
    font-size: 11px;
    font-weight: 600;
    border: 1px solid #334155;
    border-radius: 6px;
    padding: 5px 10px;
}

QPushButton#ViewerActionBtn:hover {
    background-color: #334155;
    color: #f8fafc;
}

/* Barra de Progresso */
QProgressBar#ProgressBar {
    border: 1px solid #334155;
    border-radius: 6px;
    background-color: #0f1117;
    text-align: center;
    color: #f8fafc;
    font-size: 10px;
    font-weight: 600;
    height: 14px;
}

QProgressBar#ProgressBar::chunk {
    background-color: #3b82f6;
    border-radius: 5px;
}

/* Label de Status */
QLabel#StatusLabel {
    color: #94a3b8;
    font-size: 12px;
    font-weight: 500;
}
"""


class DXFPreviewWidget(QGraphicsView):
    """
    Componente Gráfico interativo com suporte a Zoom, Pan e renderização vetorial
    fiel dos contornos gerados para máquina a laser.
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)

        # Configurações de Renderização
        self.setRenderHints(
            QPainter.Antialiasing
            | QPainter.SmoothPixmapTransform
        )
        self.setDragMode(QGraphicsView.ScrollHandDrag)  # Pan com arrasto do mouse
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setBackgroundBrush(QBrush(QColor("#0d1017")))  # Cor de fundo estilo CAD
        self.setStyleSheet("border: 1px solid #262a38; border-radius: 8px;")

        self._show_placeholder_message()

    def _show_placeholder_message(self):
        """Exibe uma mensagem inicial amigável enquanto nenhum vetor foi carregado."""
        self.scene.clear()
        text = self.scene.addText(
            "📐 Pré-Visualização Vetorial DXF\n\n"
            "Selecione um arquivo (PNG, JPG ou PDF)\n"
            "e clique em 'Converter para DXF' para inspecionar os contornos.",
            QFont("Segoe UI", 11)
        )
        text.setDefaultTextColor(QColor("#64748b"))
        rect = text.boundingRect()
        text.setPos(-rect.width() / 2, -rect.height() / 2)
        self.setSceneRect(self.scene.itemsBoundingRect().adjusted(-50, -50, 50, 50))
        self.fitInView(self.sceneRect(), Qt.KeepAspectRatio)

    def load_dxf(self, dxf_path: str) -> Tuple[int, int]:
        """
        Carrega as entidades do arquivo DXF gerado e renderiza como traços vetoriais.

        Retorna:
            (qtd_contornos_externos, qtd_furos_internos)
        """
        self.scene.clear()
        self.resetTransform()

        path = Path(dxf_path)
        if not path.is_file():
            return 0, 0

        doc = ezdxf.readfile(str(path))
        msp = doc.modelspace()

        # Cores para o operador de laser identificar claramente cada camada:
        pen_outer = QPen(QColor("#ef4444"), 1.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)  # Vermelho
        pen_outer.setCosmetic(True)  # Mantém espessura visual constante no zoom

        pen_hole = QPen(QColor("#10b981"), 1.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)   # Verde
        pen_hole.setCosmetic(True)

        pen_default = QPen(QColor("#94a3b8"), 1.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        pen_default.setCosmetic(True)

        outer_count = 0
        hole_count = 0

        # Itera sobre as polilinhas leves do DXF
        for poly in msp.query("LWPOLYLINE"):
            points = list(poly.get_points())
            if len(points) < 2:
                continue

            qpath = QPainterPath()
            # No DXF WCS, Y cresce para cima. No Qt, Y cresce para baixo.
            # Invertemos o sinal de Y (-y) para o desenho ficar perfeitamente orientado na tela:
            qpath.moveTo(QPointF(points[0][0], -points[0][1]))
            for pt in points[1:]:
                qpath.lineTo(QPointF(pt[0], -pt[1]))

            if poly.closed:
                qpath.closeSubpath()

            layer_name = poly.dxf.layer.upper()
            if "OUTER" in layer_name:
                pen = pen_outer
                outer_count += 1
            elif "HOLE" in layer_name:
                pen = pen_hole
                hole_count += 1
            else:
                pen = pen_default

            self.scene.addPath(qpath, pen)

        # Ajusta os limites da cena e enquadra o desenho automaticamente
        bounds = self.scene.itemsBoundingRect()
        if not bounds.isEmpty():
            self.setSceneRect(bounds.adjusted(-20, -20, 20, 20))
            self.fit_to_view()

        return outer_count, hole_count

    def fit_to_view(self):
        """Ajusta o desenho para caber perfeitamente na janela."""
        bounds = self.sceneRect()
        if not bounds.isEmpty():
            self.fitInView(bounds, Qt.KeepAspectRatio)

    def zoom_in(self):
        """Aumenta o zoom em 25%."""
        self.scale(1.25, 1.25)

    def zoom_out(self):
        """Diminui o zoom em 25%."""
        self.scale(0.8, 0.8)

    def wheelEvent(self, event: QWheelEvent):
        """Controle suave de Zoom centrado na posição do mouse."""
        factor = 1.15 if event.angleDelta().y() > 0 else 1.0 / 1.15
        self.scale(factor, factor)


class ConversionWorker(QThread):
    """Worker assíncrono para conversão sem congelamento da GUI."""
    progress = Signal(int)
    status = Signal(str)
    finished = Signal(str)
    error = Signal(str)

    def __init__(self, input_path: str, output_path: str = "", dpi: int = 300):
        super().__init__()
        self.input_path = input_path
        self.output_path = output_path if output_path else None
        self.dpi = dpi

    def run(self):
        try:
            self.progress.emit(5)
            self.status.emit("Iniciando processo de conversão...")

            def _callback(percent: int, message: str):
                self.progress.emit(percent)
                self.status.emit(message)

            result = process_file(
                filepath=self.input_path,
                output_path=self.output_path,
                dpi=self.dpi,
                all_pages=False,
                progress_callback=_callback,
            )

            last_path = str(result[0]) if isinstance(result, list) else str(result)

            self.progress.emit(100)
            self.status.emit("Sucesso!")
            self.finished.emit(last_path)

        except Exception as exc:
            self.error.emit(str(exc))


class MainWindow(QMainWindow):
    """Janela Principal com layout dividido em Controles (esquerda) e Preview (direita)."""

    SUPPORTED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".pdf"}

    def __init__(self):
        super().__init__()

        self.selected_filepath: str = ""
        self.last_generated_dxf: str = ""
        self.worker: Optional[ConversionWorker] = None

        self.setWindowTitle("Conversor Laser DXF | Pré-Visualizador CAD")
        self.resize(1050, 620)
        self.setMinimumSize(920, 540)
        self.setAcceptDrops(True)

        self._setup_ui()

    def _setup_ui(self):
        central_widget = QWidget(self)
        central_widget.setObjectName("CentralWidget")
        self.setCentralWidget(central_widget)

        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(16)

        # =========================================================
        # 1. PAINEL ESQUERDO: CONTROLES E AÇÕES (360px fixo)
        # =========================================================
        left_card = QFrame(self)
        left_card.setObjectName("LeftCard")
        left_card.setFixedWidth(360)
        left_layout = QVBoxLayout(left_card)
        left_layout.setContentsMargins(22, 22, 22, 22)
        left_layout.setSpacing(14)

        # Header
        self.lbl_title = QLabel("Conversor para Laser", self)
        self.lbl_title.setObjectName("TitleLabel")
        self.lbl_subtitle = QLabel(
            "Vetorização com polígonos fechados e hierarquia para Hatch",
            self,
        )
        self.lbl_subtitle.setObjectName("SubtitleLabel")
        self.lbl_subtitle.setWordWrap(True)

        left_layout.addWidget(self.lbl_title)
        left_layout.addWidget(self.lbl_subtitle)

        # Divisor
        divider = QFrame(self)
        divider.setFrameShape(QFrame.HLine)
        divider.setStyleSheet("color: #262a38;")
        left_layout.addWidget(divider)

        # Botão Selecionar
        self.btn_select = QPushButton("📂  Selecionar Arquivo (PDF, Imagem)", self)
        self.btn_select.setObjectName("BtnSelect")
        self.btn_select.setCursor(Qt.PointingHandCursor)
        self.btn_select.clicked.connect(self.select_file)
        left_layout.addWidget(self.btn_select)

        # Campo Caminho
        lbl_path_title = QLabel("Arquivo Selecionado:", self)
        lbl_path_title.setStyleSheet("color: #94a3b8; font-size: 11px; font-weight: 600;")
        left_layout.addWidget(lbl_path_title)

        self.txt_path = QLineEdit(self)
        self.txt_path.setObjectName("PathDisplay")
        self.txt_path.setReadOnly(True)
        self.txt_path.setPlaceholderText("Nenhum arquivo ou arraste aqui...")
        left_layout.addWidget(self.txt_path)

        # Barra de Progresso
        self.progress_bar = QProgressBar(self)
        self.progress_bar.setObjectName("ProgressBar")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        left_layout.addWidget(self.progress_bar)

        # Botão Converter
        self.btn_convert = QPushButton("⚡  Converter para DXF", self)
        self.btn_convert.setObjectName("BtnConvert")
        self.btn_convert.setCursor(Qt.PointingHandCursor)
        self.btn_convert.setEnabled(False)
        self.btn_convert.clicked.connect(self.start_conversion)
        left_layout.addWidget(self.btn_convert)

        # Status
        self.lbl_status = QLabel("Aguardando seleção de arquivo...", self)
        self.lbl_status.setObjectName("StatusLabel")
        self.lbl_status.setAlignment(Qt.AlignCenter)
        self.lbl_status.setWordWrap(True)
        left_layout.addWidget(self.lbl_status)

        # Botão Abrir Pasta
        self.btn_open_folder = QPushButton("📁 Abrir Pasta de Destino", self)
        self.btn_open_folder.setObjectName("ViewerActionBtn")
        self.btn_open_folder.setCursor(Qt.PointingHandCursor)
        self.btn_open_folder.setVisible(False)
        self.btn_open_folder.clicked.connect(self.open_output_folder)
        left_layout.addWidget(self.btn_open_folder)

        # Card de Resumo da Vetorização (Estatísticas do DXF)
        self.stats_frame = QFrame(self)
        self.stats_frame.setStyleSheet("background-color: #0f1117; border-radius: 8px; padding: 10px;")
        self.stats_frame.setVisible(False)
        stats_layout = QVBoxLayout(self.stats_frame)
        stats_layout.setContentsMargins(6, 6, 6, 6)
        stats_layout.setSpacing(4)

        self.lbl_stats_title = QLabel("📊 Resumo da Vetorização:", self)
        self.lbl_stats_title.setStyleSheet("color: #38bdf8; font-size: 11px; font-weight: 700;")
        self.lbl_stats_outer = QLabel("• Contornos Externos: 0", self)
        self.lbl_stats_outer.setStyleSheet("color: #f87171; font-size: 11px;")
        self.lbl_stats_holes = QLabel("• Ilhas / Furos Internos: 0", self)
        self.lbl_stats_holes.setStyleSheet("color: #34d399; font-size: 11px;")

        stats_layout.addWidget(self.lbl_stats_title)
        stats_layout.addWidget(self.lbl_stats_outer)
        stats_layout.addWidget(self.lbl_stats_holes)
        left_layout.addWidget(self.stats_frame)

        left_layout.addStretch()
        main_layout.addWidget(left_card)

        # =========================================================
        # 2. PAINEL DIREITO: VISOR GRÁFICO INTERATIVO (EXPANSÍVEL)
        # =========================================================
        right_card = QFrame(self)
        right_card.setObjectName("RightCard")
        right_layout = QVBoxLayout(right_card)
        right_layout.setContentsMargins(16, 16, 16, 16)
        right_layout.setSpacing(10)

        # Barra de ferramentas do Preview
        toolbar_layout = QHBoxLayout()
        toolbar_layout.setSpacing(8)

        lbl_viewer_title = QLabel("Visor Interativo de Contornos do Laser", self)
        lbl_viewer_title.setStyleSheet("color: #f8fafc; font-size: 13px; font-weight: 700;")
        toolbar_layout.addWidget(lbl_viewer_title)

        # Legenda das camadas
        lbl_leg_outer = QLabel("■ Contornos Externos", self)
        lbl_leg_outer.setStyleSheet("color: #ef4444; font-size: 11px; font-weight: 600;")
        lbl_leg_holes = QLabel("■ Furos / Ilhas", self)
        lbl_leg_holes.setStyleSheet("color: #10b981; font-size: 11px; font-weight: 600;")
        toolbar_layout.addWidget(lbl_leg_outer)
        toolbar_layout.addWidget(lbl_leg_holes)

        toolbar_layout.addStretch()

        # Botões de Zoom e Ajuste
        btn_zoom_in = QPushButton("🔍 +", self)
        btn_zoom_in.setObjectName("ViewerActionBtn")
        btn_zoom_in.setToolTip("Aumentar Zoom (ou use o scroll do mouse)")
        btn_zoom_in.clicked.connect(lambda: self.preview_widget.zoom_in())

        btn_zoom_out = QPushButton("🔍 −", self)
        btn_zoom_out.setObjectName("ViewerActionBtn")
        btn_zoom_out.setToolTip("Diminuir Zoom (ou use o scroll do mouse)")
        btn_zoom_out.clicked.connect(lambda: self.preview_widget.zoom_out())

        btn_fit = QPushButton("⛶ Ajustar", self)
        btn_fit.setObjectName("ViewerActionBtn")
        btn_fit.setToolTip("Enquadrar vetor na tela")
        btn_fit.clicked.connect(lambda: self.preview_widget.fit_to_view())

        toolbar_layout.addWidget(btn_zoom_in)
        toolbar_layout.addWidget(btn_zoom_out)
        toolbar_layout.addWidget(btn_fit)

        right_layout.addLayout(toolbar_layout)

        # Componente de Visualização
        self.preview_widget = DXFPreviewWidget(self)
        self.preview_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        right_layout.addWidget(self.preview_widget)

        main_layout.addWidget(right_card, stretch=1)

    # -------------------------------------------------------------
    # Manipulação de Arquivos
    # -------------------------------------------------------------
    def select_file(self):
        filters = (
            "Arquivos Suportados (*.png *.jpg *.jpeg *.pdf);;"
            "Documentos PDF (*.pdf);;"
            "Imagens (*.png *.jpg *.jpeg);;"
            "Todos os Arquivos (*.*)"
        )
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Selecionar Imagem ou PDF", "", filters
        )
        if file_path:
            self.set_selected_file(file_path)

    def set_selected_file(self, file_path: str):
        path = Path(file_path)
        if path.suffix.lower() in self.SUPPORTED_EXTENSIONS and path.is_file():
            self.selected_filepath = str(path)
            self.txt_path.setText(str(path))
            self.btn_convert.setEnabled(True)
            self.btn_open_folder.setVisible(False)
            self.stats_frame.setVisible(False)
            self.progress_bar.setVisible(False)
            self.lbl_status.setText("Arquivo pronto. Clique em 'Converter para DXF'.")
            self.lbl_status.setStyleSheet("color: #60a5fa;")
        else:
            self.selected_filepath = ""
            self.txt_path.clear()
            self.btn_convert.setEnabled(False)
            self.lbl_status.setText("Formato inválido! Selecione PDF, PNG ou JPG.")
            self.lbl_status.setStyleSheet("color: #f87171;")

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        urls = event.mimeData().urls()
        if urls:
            local_path = urls[0].toLocalFile()
            self.set_selected_file(local_path)

    # -------------------------------------------------------------
    # Conversão e Integração com o Preview
    # -------------------------------------------------------------
    def start_conversion(self):
        if not self.selected_filepath:
            return

        self.btn_convert.setEnabled(False)
        self.btn_select.setEnabled(False)
        self.btn_open_folder.setVisible(False)
        self.stats_frame.setVisible(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.lbl_status.setText("Iniciando conversão...")
        self.lbl_status.setStyleSheet("color: #94a3b8;")

        self.worker = ConversionWorker(input_path=self.selected_filepath, dpi=300)
        self.worker.progress.connect(self.progress_bar.setValue)
        self.worker.status.connect(self._on_status_update)
        self.worker.finished.connect(self._on_conversion_finished)
        self.worker.error.connect(self._on_conversion_error)
        self.worker.start()

    def _on_status_update(self, msg: str):
        self.lbl_status.setText(msg)
        self.lbl_status.setStyleSheet("color: #93c5fd;")

    def _on_conversion_finished(self, output_path: str):
        self.last_generated_dxf = output_path
        self.lbl_status.setText("✅ Sucesso! Vetor DXF gerado.")
        self.lbl_status.setStyleSheet("color: #34d399; font-weight: 600;")

        self.btn_select.setEnabled(True)
        self.btn_convert.setEnabled(True)
        self.btn_open_folder.setVisible(True)

        # Carrega o vetor DXF gerado diretamente no Visualizador Gráfico!
        outer_cnt, hole_cnt = self.preview_widget.load_dxf(output_path)

        # Atualiza o quadro de estatísticas
        self.lbl_stats_outer.setText(f"• Contornos Externos: {outer_cnt}")
        self.lbl_stats_holes.setText(f"• Ilhas / Furos Internos: {hole_cnt}")
        self.stats_frame.setVisible(True)

    def _on_conversion_error(self, err_msg: str):
        self.lbl_status.setText(f"❌ Erro: {err_msg}")
        self.lbl_status.setStyleSheet("color: #f87171; font-weight: 600;")
        self.btn_select.setEnabled(True)
        self.btn_convert.setEnabled(True)
        self.progress_bar.setVisible(False)

    def open_output_folder(self):
        if self.last_generated_dxf:
            folder_path = Path(self.last_generated_dxf).parent
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder_path)))


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(MODERN_STYLE_SHEET)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
