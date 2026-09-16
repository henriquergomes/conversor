"""
Interface Gráfica do Usuário (GUI) - Conversor Laser DXF
========================================================

Aplicação desktop assíncrona desenvolvida em PySide6 (Qt 6) com QThread.
Evita travamentos e mantém a interface 100% responsiva durante o processamento
de imagens e PDFs em alta resolução.
"""

from pathlib import Path
import sys

from PySide6.QtCore import QThread, QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices, QDragEnterEvent, QDropEvent
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
    QVBoxLayout,
    QWidget,
)

from converter import process_file


# -------------------------------------------------------------
# Folha de Estilos Moderna (QSS)
# -------------------------------------------------------------
MODERN_STYLE_SHEET = """
QMainWindow {
    background-color: #121318;
}

QWidget#CentralWidget {
    background-color: #121318;
}

/* Card Principal */
QFrame#MainCard {
    background-color: #1c1e26;
    border: 1px solid #2d313f;
    border-radius: 12px;
}

/* Título e Subtítulo */
QLabel#TitleLabel {
    color: #f3f4f6;
    font-size: 20px;
    font-weight: 700;
}

QLabel#SubtitleLabel {
    color: #9ca3af;
    font-size: 12px;
}

/* Botão Selecionar Arquivo */
QPushButton#BtnSelect {
    background-color: #2563eb;
    color: #ffffff;
    font-size: 14px;
    font-weight: 600;
    border: none;
    border-radius: 8px;
    padding: 12px 24px;
}

QPushButton#BtnSelect:hover {
    background-color: #1d4ed8;
}

QPushButton#BtnSelect:pressed {
    background-color: #1e40af;
}

QPushButton#BtnSelect:disabled {
    background-color: #2a313d;
    color: #6b7280;
}

/* Campo de Exibição do Caminho */
QLineEdit#PathDisplay {
    background-color: #13141b;
    color: #e5e7eb;
    border: 1px solid #374151;
    border-radius: 6px;
    padding: 8px 12px;
    font-size: 12px;
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
    padding: 12px 24px;
}

QPushButton#BtnConvert:hover {
    background-color: #047857;
}

QPushButton#BtnConvert:pressed {
    background-color: #065f46;
}

QPushButton#BtnConvert:disabled {
    background-color: #2a313d;
    color: #6b7280;
}

/* Botão Abrir Pasta */
QPushButton#BtnOpenFolder {
    background-color: #374151;
    color: #f3f4f6;
    font-size: 12px;
    font-weight: 500;
    border: none;
    border-radius: 6px;
    padding: 6px 14px;
}

QPushButton#BtnOpenFolder:hover {
    background-color: #4b5563;
}

/* Barra de Progresso */
QProgressBar#ProgressBar {
    border: 1px solid #374151;
    border-radius: 6px;
    background-color: #13141b;
    text-align: center;
    color: #f3f4f6;
    font-size: 11px;
    font-weight: 600;
    height: 16px;
}

QProgressBar#ProgressBar::chunk {
    background-color: #3b82f6;
    border-radius: 5px;
}

/* Label de Status */
QLabel#StatusLabel {
    color: #9ca3af;
    font-size: 12px;
    font-weight: 500;
}
"""


class ConversionWorker(QThread):
    """
    Worker que executa o processamento pesado de imagem/PDF em uma thread dedicada.
    Garante que a interface permaneça com 60 FPS e sem congelamentos.
    """
    progress = Signal(int)       # Emite valor percentual (0 a 100)
    status = Signal(str)         # Emite mensagem descritiva da etapa atual
    finished = Signal(str)       # Emite caminho final do arquivo gerado
    error = Signal(str)          # Emite mensagem de erro caso ocorra falha

    def __init__(
        self,
        input_path: str,
        output_path: str = "",
        dpi: int = 300,
        all_pages: bool = False,
    ):
        super().__init__()
        self.input_path = input_path
        self.output_path = output_path if output_path else None
        self.dpi = dpi
        self.all_pages = all_pages

    def run(self):
        """Execução concorrente desacoplada da GUI."""
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
                all_pages=self.all_pages,
                progress_callback=_callback,
            )

            # Prepara a mensagem final
            if isinstance(result, list):
                result_str = f"{len(result)} arquivos DXF gerados com sucesso."
                last_path = str(result[0])
            else:
                result_str = str(result)
                last_path = str(result)

            self.progress.emit(100)
            self.status.emit("Sucesso!")
            self.finished.emit(last_path)

        except Exception as exc:
            self.error.emit(str(exc))


class MainWindow(QMainWindow):
    """Janela Principal com gerenciamento de estado e threads."""

    SUPPORTED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".pdf"}

    def __init__(self):
        super().__init__()

        self.selected_filepath: str = ""
        self.last_generated_dxf: str = ""
        self.worker: Optional[ConversionWorker] = None

        # Configurações da Janela
        self.setWindowTitle("Conversor Laser DXF | Imagem & PDF")
        self.setFixedSize(620, 480)
        self.setAcceptDrops(True)

        self._setup_ui()

    def _setup_ui(self):
        """Montagem dos componentes visuais e layouts."""
        central_widget = QWidget(self)
        central_widget.setObjectName("CentralWidget")
        self.setCentralWidget(central_widget)

        root_layout = QVBoxLayout(central_widget)
        root_layout.setContentsMargins(20, 20, 20, 20)

        # Card Central
        card_frame = QFrame(self)
        card_frame.setObjectName("MainCard")
        card_layout = QVBoxLayout(card_frame)
        card_layout.setContentsMargins(26, 26, 26, 26)
        card_layout.setSpacing(16)

        # 1. Header (Título e Subtítulo)
        header_layout = QVBoxLayout()
        header_layout.setSpacing(4)

        self.lbl_title = QLabel("Conversor para Gravação a Laser", self)
        self.lbl_title.setObjectName("TitleLabel")

        self.lbl_subtitle = QLabel(
            "Vetorização de imagens e PDFs para DXF com contornos fechados (Hatch Ready)",
            self,
        )
        self.lbl_subtitle.setObjectName("SubtitleLabel")

        header_layout.addWidget(self.lbl_title)
        header_layout.addWidget(self.lbl_subtitle)
        card_layout.addLayout(header_layout)

        # Divisor visual
        divider = QFrame(self)
        divider.setFrameShape(QFrame.HLine)
        divider.setFrameShadow(QFrame.Sunken)
        divider.setStyleSheet("color: #2d313f;")
        card_layout.addWidget(divider)

        # 2. Botão "Selecionar Arquivo"
        self.btn_select = QPushButton("📂  Selecionar Arquivo (PDF, PNG, JPG)", self)
        self.btn_select.setObjectName("BtnSelect")
        self.btn_select.setCursor(Qt.PointingHandCursor)
        self.btn_select.clicked.connect(self.select_file)
        card_layout.addWidget(self.btn_select)

        # 3. Campo de texto com o caminho selecionado
        path_layout = QVBoxLayout()
        path_layout.setSpacing(6)

        lbl_path_title = QLabel("Arquivo Selecionado:", self)
        lbl_path_title.setStyleSheet("color: #9ca3af; font-size: 11px; font-weight: 600;")

        self.txt_path = QLineEdit(self)
        self.txt_path.setObjectName("PathDisplay")
        self.txt_path.setReadOnly(True)
        self.txt_path.setPlaceholderText("Nenhum arquivo selecionado ou arraste um arquivo aqui...")

        path_layout.addWidget(lbl_path_title)
        path_layout.addWidget(self.txt_path)
        card_layout.addLayout(path_layout)

        # 4. Barra de Progresso
        self.progress_bar = QProgressBar(self)
        self.progress_bar.setObjectName("ProgressBar")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        card_layout.addWidget(self.progress_bar)

        # 5. Botão "Converter para DXF"
        self.btn_convert = QPushButton("⚡  Converter para DXF", self)
        self.btn_convert.setObjectName("BtnConvert")
        self.btn_convert.setCursor(Qt.PointingHandCursor)
        self.btn_convert.setEnabled(False)
        self.btn_convert.clicked.connect(self.start_conversion)
        card_layout.addWidget(self.btn_convert)

        # 6. Status e Ações Auxiliares
        status_container = QVBoxLayout()
        status_container.setSpacing(6)

        self.lbl_status = QLabel("Aguardando arquivo...", self)
        self.lbl_status.setObjectName("StatusLabel")
        self.lbl_status.setAlignment(Qt.AlignCenter)
        status_container.addWidget(self.lbl_status)

        # Botão para abrir pasta após sucesso (inicia oculto)
        self.btn_open_folder = QPushButton("📁 Abrir Pasta de Destino", self)
        self.btn_open_folder.setObjectName("BtnOpenFolder")
        self.btn_open_folder.setCursor(Qt.PointingHandCursor)
        self.btn_open_folder.setVisible(False)
        self.btn_open_folder.clicked.connect(self.open_output_folder)
        status_container.addWidget(self.btn_open_folder, alignment=Qt.AlignCenter)

        card_layout.addLayout(status_container)
        root_layout.addWidget(card_frame)

    # -------------------------------------------------------------
    # Seleção de Arquivo e Drag & Drop
    # -------------------------------------------------------------
    def select_file(self):
        """Abre diálogo para seleção de arquivos."""
        filters = (
            "Arquivos Suportados (*.png *.jpg *.jpeg *.pdf);;"
            "Documentos PDF (*.pdf);;"
            "Imagens (*.png *.jpg *.jpeg);;"
            "Todos os Arquivos (*.*)"
        )
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Selecionar Imagem ou Documento PDF",
            "",
            filters,
        )
        if file_path:
            self.set_selected_file(file_path)

    def set_selected_file(self, file_path: str):
        """Valida e define o arquivo na interface."""
        path = Path(file_path)
        if path.suffix.lower() in self.SUPPORTED_EXTENSIONS and path.is_file():
            self.selected_filepath = str(path)
            self.txt_path.setText(str(path))
            self.btn_convert.setEnabled(True)
            self.btn_open_folder.setVisible(False)
            self.progress_bar.setVisible(False)
            self.progress_bar.setValue(0)
            self.lbl_status.setText("Arquivo pronto para conversão.")
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
    # Orquestração da Thread de Conversão
    # -------------------------------------------------------------
    def start_conversion(self):
        """Dispara o Worker em segundo plano sem congelar a UI."""
        if not self.selected_filepath:
            return

        # 1. Atualiza estados visuais para modo de carregamento
        self.btn_convert.setEnabled(False)
        self.btn_select.setEnabled(False)
        self.btn_open_folder.setVisible(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.lbl_status.setText("Iniciando...")
        self.lbl_status.setStyleSheet("color: #9ca3af;")

        # 2. Instancia o Worker
        self.worker = ConversionWorker(
            input_path=self.selected_filepath,
            dpi=300,
            all_pages=False,
        )

        # 3. Conecta os sinais da Thread aos slots da interface
        self.worker.progress.connect(self.progress_bar.setValue)
        self.worker.status.connect(self._on_status_update)
        self.worker.finished.connect(self._on_conversion_finished)
        self.worker.error.connect(self._on_conversion_error)

        # 4. Inicia a thread
        self.worker.start()

    def _on_status_update(self, message: str):
        """Atualiza a mensagem descritiva de status."""
        self.lbl_status.setText(message)
        self.lbl_status.setStyleSheet("color: #93c5fd;")

    def _on_conversion_finished(self, output_path: str):
        """Trata o término com sucesso da conversão."""
        self.last_generated_dxf = output_path
        self.lbl_status.setText("✅ Sucesso! Arquivo DXF gerado com contornos fechados.")
        self.lbl_status.setStyleSheet("color: #34d399; font-weight: 600;")

        self.btn_select.setEnabled(True)
        self.btn_convert.setEnabled(True)
        self.btn_open_folder.setVisible(True)

    def _on_conversion_error(self, err_msg: str):
        """Trata erros disparados durante a conversão."""
        self.lbl_status.setText(f"❌ Erro: {err_msg}")
        self.lbl_status.setStyleSheet("color: #f87171; font-weight: 600;")

        self.btn_select.setEnabled(True)
        self.btn_convert.setEnabled(True)
        self.progress_bar.setVisible(False)

    def open_output_folder(self):
        """Abre o explorador de arquivos do sistema na pasta do DXF gerado."""
        if self.last_generated_dxf:
            folder_path = Path(self.last_generated_dxf).parent
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder_path)))


def main():
    """Ponto de entrada da aplicação desktop."""
    app = QApplication(sys.argv)
    app.setStyleSheet(MODERN_STYLE_SHEET)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
