"""
Conversor Universal de Imagem Raster (PNG, JPG) e PDF para Vetor CAD (DXF)
==========================================================================

Desenvolvido para pipeline de pré-processamento e vetorização 2D para
máquinas de gravação e corte a laser (LightBurn, EzCad, RDWorks, LaserGRBL, etc.).

Principais recursos:
- Renderização de PDFs em alta resolução (300 DPI) diretamente na memória RAM (via PyMuPDF).
- Zero overhead de disco e sem necessidade de limpeza de arquivos temporários.
- Binarização inteligente (Otsu) e aproximação poligonal (Douglas-Peucker).
- Polilinhas estritamente fechadas (LWPolyline com bit de fechamento ativo) para suporte nativo a Hatching.
- Hierarquia topológica de contornos externos (LASER_OUTER) e furos internos (LASER_HOLES).
- Suporte a callback de progresso para interfaces gráficas (PySide6 / QThread).
"""

from pathlib import Path
from typing import Callable, List, Optional, Tuple, Union
import argparse
import sys

import cv2
import ezdxf
import fitz  # PyMuPDF
import numpy as np


# Extensões suportadas
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tiff", ".tif"}
PDF_EXTENSIONS = {".pdf"}

ProgressCallback = Optional[Callable[[int, str], None]]


def clean_polygon_points(
    points: List[Tuple[float, float]],
    min_dist_threshold: float = 1e-4,
) -> List[Tuple[float, float]]:
    """
    Higieniza a lista de vértices de um contorno para aplicação segura em CAM/Laser:
    1. Remove vértices consecutivos coincidentes ou com distância desprezível.
    2. Remove o último ponto caso seja idêntico ao primeiro (já que o fechamento
       é garantido pela flag `close=True` no DXF, evitando micro-segmentos nulos).
    """
    if len(points) < 3:
        return []

    cleaned: List[Tuple[float, float]] = [points[0]]
    for pt in points[1:]:
        prev = cleaned[-1]
        dist = np.hypot(pt[0] - prev[0], pt[1] - prev[1])
        if dist > min_dist_threshold:
            cleaned.append(pt)

    if len(cleaned) > 1:
        first = cleaned[0]
        last = cleaned[-1]
        if np.hypot(last[0] - first[0], last[1] - first[1]) <= min_dist_threshold:
            cleaned.pop()

    return cleaned


def image_array_to_dxf(
    img_array: np.ndarray,
    output_path: Union[str, Path],
    threshold_value: Optional[int] = None,
    invert_colors: bool = True,
    blur_kernel_size: int = 5,
    approx_epsilon_ratio: float = 0.002,
    min_contour_area: float = 10.0,
    dxf_version: str = "R2010",
    progress_callback: ProgressCallback = None,
) -> Path:
    """
    Vetoriza um array NumPy (imagem em memória) e salva como DXF com polígonos fechados.
    Essa função permite pipeline 100% in-memory, eliminando I/O de arquivos temporários.
    """
    def _notify(pct: int, msg: str):
        if progress_callback:
            progress_callback(pct, msg)

    output_path = Path(output_path).resolve()

    if img_array is None or not isinstance(img_array, np.ndarray):
        raise ValueError("O array de imagem fornecido é inválido ou nulo.")

    img_height, img_width = img_array.shape[:2]
    _notify(35, "Processando canais de cor e escala de cinza...")

    # 1. Normalização para escala de cinza (1 canal)
    if len(img_array.shape) == 3:
        gray = cv2.cvtColor(img_array, cv2.COLOR_BGR2GRAY)
    elif len(img_array.shape) == 2:
        gray = img_array.copy()
    else:
        raise ValueError(f"Dimensões de imagem não suportadas: shape={img_array.shape}")

    # 2. Suavização Gaussiana
    if blur_kernel_size > 0:
        if blur_kernel_size % 2 == 0:
            blur_kernel_size += 1
        gray = cv2.GaussianBlur(gray, (blur_kernel_size, blur_kernel_size), 0)

    # 3. Binarização (Threshold)
    _notify(50, "Binarizando imagem (Thresholding)...")
    thresh_type = cv2.THRESH_BINARY_INV if invert_colors else cv2.THRESH_BINARY
    if threshold_value is None:
        _, binary = cv2.threshold(gray, 0, 255, thresh_type + cv2.THRESH_OTSU)
    else:
        threshold_value = max(0, min(255, threshold_value))
        _, binary = cv2.threshold(gray, threshold_value, 255, thresh_type)

    # 4. Extração de Contornos com Hierarquia (RETR_CCOMP)
    _notify(65, "Extraindo contornos e analisando topologia...")
    contours, hierarchy = cv2.findContours(
        binary, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE
    )

    if not contours:
        raise RuntimeError(
            "Nenhum contorno detectado na imagem. "
            "Ajuste os parâmetros de binarização (threshold) ou contraste."
        )

    # 5. Criação do documento DXF
    _notify(75, "Gerando polilinhas vetoriais fechadas (LWPolyline)...")
    doc = ezdxf.new(dxfversion=dxf_version)
    msp = doc.modelspace()

    # Camadas separadas para controle de corte e gravação no software Laser
    doc.layers.add(name="LASER_OUTER", color=1)  # Vermelho: contornos externos
    doc.layers.add(name="LASER_HOLES", color=3)  # Verde: ilhas e furos internos

    polygons_added = 0
    hier_data = hierarchy[0] if hierarchy is not None else None

    for idx, cnt in enumerate(contours):
        area = cv2.contourArea(cnt)
        if area < min_contour_area:
            continue

        # Douglas-Peucker para aproximação de curvas
        if approx_epsilon_ratio > 0:
            perimeter = cv2.arcLength(cnt, closed=True)
            epsilon = approx_epsilon_ratio * perimeter
            approx_cnt = cv2.approxPolyDP(cnt, epsilon, closed=True)
        else:
            approx_cnt = cnt

        raw_pts = approx_cnt.reshape(-1, 2)

        # Inversão do eixo Y para coordenadas de CAD (Y_cad = height - Y_img)
        cad_points = [
            (float(x), float(img_height - y)) for x, y in raw_pts
        ]

        # Sanitização geométrica
        clean_pts = clean_polygon_points(cad_points)
        if len(clean_pts) < 3:
            continue

        # Identificação de furo interno vs contorno externo
        is_hole = False
        if hier_data is not None and hier_data[idx][3] != -1:
            is_hole = True

        target_layer = "LASER_HOLES" if is_hole else "LASER_OUTER"

        # Polilinha com flag de fechamento estrita para o Hatch
        msp.add_lwpolyline(
            points=clean_pts,
            close=True,
            dxfattribs={"layer": target_layer},
        )
        polygons_added += 1

    if polygons_added == 0:
        raise RuntimeError(
            f"Foram encontrados {len(contours)} contornos, mas nenhum atendeu aos critérios "
            f"de polígono fechado válido (área >= {min_contour_area} px e >= 3 vértices)."
        )

    _notify(90, f"Gravando arquivo DXF com {polygons_added} polígonos fechados...")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(str(output_path))

    _notify(100, "Vetorização concluída com sucesso!")
    return output_path


def image_to_dxf(
    input_path: Union[str, Path],
    output_path: Optional[Union[str, Path]] = None,
    progress_callback: ProgressCallback = None,
    **kwargs,
) -> Path:
    """Lê uma imagem do disco (JPG, PNG) e a converte para DXF."""
    def _notify(pct: int, msg: str):
        if progress_callback:
            progress_callback(pct, msg)

    input_path = Path(input_path).resolve()
    if not input_path.is_file():
        raise FileNotFoundError(f"Arquivo de imagem não encontrado: '{input_path}'")

    if input_path.suffix.lower() not in IMAGE_EXTENSIONS:
        raise ValueError(
            f"Extensão de imagem não suportada: '{input_path.suffix}'. "
            f"Extensões válidas: {', '.join(sorted(IMAGE_EXTENSIONS))}"
        )

    if output_path is None:
        output_path = input_path.with_suffix(".dxf")
    else:
        output_path = Path(output_path).resolve()

    _notify(15, f"Carregando imagem '{input_path.name}'...")
    img = cv2.imread(str(input_path))
    if img is None:
        raise ValueError(
            f"Não foi possível decodificar a imagem '{input_path}'. "
            "O arquivo pode estar corrompido ou em formato incompatível."
        )

    return image_array_to_dxf(
        img_array=img,
        output_path=output_path,
        progress_callback=progress_callback,
        **kwargs,
    )


def pdf_to_images(
    pdf_path: Union[str, Path],
    dpi: int = 300,
    all_pages: bool = False,
    progress_callback: ProgressCallback = None,
    max_dimension_pixels: int = 4000,
) -> List[np.ndarray]:
    """
    Renderiza as páginas de um PDF diretamente para arrays NumPy em memória RAM via PyMuPDF.

    Possui cálculo adaptativo de resolução: para páginas gigantescas (ex: pranchas ou PDFs
    com milhares de pontos), ajusta a escala dinamicamente para respeitar o teto de segurança
    (max_dimension_pixels), prevenindo o erro 'code=5: Overly large image' do MuPDF e mantendo
    a máxima nitidez possível para gravação a laser.
    """
    def _notify(pct: int, msg: str):
        if progress_callback:
            progress_callback(pct, msg)

    pdf_path = Path(pdf_path).resolve()
    if not pdf_path.is_file():
        raise FileNotFoundError(f"Arquivo PDF não encontrado: '{pdf_path}'")

    if pdf_path.suffix.lower() not in PDF_EXTENSIONS:
        raise ValueError(f"O arquivo fornecido não é um PDF: '{pdf_path.suffix}'")

    _notify(10, f"Abrindo documento PDF '{pdf_path.name}'...")
    try:
        doc = fitz.open(str(pdf_path))
    except Exception as exc:
        raise ValueError(f"Falha ao abrir o documento PDF '{pdf_path}': {exc}") from exc

    if doc.page_count == 0:
        doc.close()
        raise ValueError(f"O documento PDF '{pdf_path}' está vazio (0 páginas).")

    pages_to_process = range(doc.page_count) if all_pages else [0]
    rendered_images: List[np.ndarray] = []

    try:
        total_p = len(pages_to_process)
        for i, page_num in enumerate(pages_to_process):
            pct = 15 + int((i / total_p) * 20)
            page = doc.load_page(page_num)
            rect = page.rect
            page_max_pt = max(rect.width, rect.height)

            # Cálculo de escala adaptativa:
            # 72 pontos = 1 polegada no padrão PDF.
            ideal_scale = dpi / 72.0
            expected_pixels = page_max_pt * ideal_scale

            if expected_pixels > max_dimension_pixels:
                # Ajusta para não estourar o limite de memória do MuPDF
                effective_scale = max_dimension_pixels / max(page_max_pt, 1.0)
                _notify(pct, f"Página gigante detectada ({int(page_max_pt)}pt). Otimizando resolução adaptativa...")
            else:
                effective_scale = ideal_scale
                _notify(pct, f"Renderizando página {page_num + 1}/{total_p} a {dpi} DPI na memória...")

            # Renderização com fallback defensivo contra estouro de memória
            current_scale = effective_scale
            pix = None
            for attempt in range(4):
                try:
                    mat = fitz.Matrix(current_scale, current_scale)
                    pix = page.get_pixmap(matrix=mat, colorspace=fitz.csGRAY)
                    break
                except Exception as render_err:
                    err_str = str(render_err).lower()
                    if ("large image" in err_str or "code=5" in err_str) and attempt < 3:
                        current_scale *= 0.6  # Reduz a escala em 40% e tenta novamente
                        continue
                    raise ValueError(
                        f"A imagem do PDF é excessivamente grande para a memória disponível: {render_err}"
                    ) from render_err

            img_gray = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)
            rendered_images.append(img_gray.copy())
    finally:
        doc.close()

    return rendered_images


def process_file(
    filepath: Union[str, Path],
    output_path: Optional[Union[str, Path]] = None,
    dpi: int = 300,
    all_pages: bool = False,
    progress_callback: ProgressCallback = None,
    **conversion_kwargs,
) -> Union[Path, List[Path]]:
    """
    Função Master: Detecta o tipo de arquivo por extensão e coordena a conversão para DXF.
    """
    def _notify(pct: int, msg: str):
        if progress_callback:
            progress_callback(pct, msg)

    input_path = Path(filepath).resolve()
    if not input_path.is_file():
        raise FileNotFoundError(f"Arquivo não encontrado: '{input_path}'")

    ext = input_path.suffix.lower()

    # 1. Roteamento: Arquivo de Imagem
    if ext in IMAGE_EXTENSIONS:
        return image_to_dxf(
            input_path=input_path,
            output_path=output_path,
            progress_callback=progress_callback,
            **conversion_kwargs,
        )

    # 2. Roteamento: Arquivo PDF
    elif ext in PDF_EXTENSIONS:
        images = pdf_to_images(
            pdf_path=input_path,
            dpi=dpi,
            all_pages=all_pages,
            progress_callback=progress_callback,
        )

        if len(images) == 1:
            target_out = (
                Path(output_path).resolve()
                if output_path is not None
                else input_path.with_suffix(".dxf")
            )
            return image_array_to_dxf(
                img_array=images[0],
                output_path=target_out,
                progress_callback=progress_callback,
                **conversion_kwargs,
            )

        output_files: List[Path] = []
        base_stem = (
            Path(output_path).stem
            if output_path is not None
            else input_path.stem
        )
        parent_dir = (
            Path(output_path).parent
            if output_path is not None
            else input_path.parent
        )

        for page_idx, img_arr in enumerate(images, start=1):
            page_dxf_path = parent_dir / f"{base_stem}_page_{page_idx}.dxf"
            res = image_array_to_dxf(
                img_array=img_arr,
                output_path=page_dxf_path,
                progress_callback=progress_callback,
                **conversion_kwargs,
            )
            output_files.append(res)

        return output_files

    else:
        all_supported = sorted(IMAGE_EXTENSIONS.union(PDF_EXTENSIONS))
        raise ValueError(
            f"Formato de arquivo não suportado: '{ext}'. "
            f"Formatos suportados: {', '.join(all_supported)}"
        )


def main():
    """CLI universal."""
    parser = argparse.ArgumentParser(
        description="Converte imagens (JPG, PNG) e PDFs para arquivos DXF com contornos fechados para Laser/CAM."
    )
    parser.add_argument("input", type=str, help="Caminho do arquivo de entrada (Imagem JPG/PNG ou PDF).")
    parser.add_argument(
        "-o", "--output", type=str, default=None,
        help="Caminho do arquivo .dxf de saída (padrão: mesmo nome com extensão .dxf)."
    )
    parser.add_argument(
        "--dpi", type=int, default=300,
        help="Resolução de renderização para PDFs em DPI (padrão: 300)."
    )
    parser.add_argument(
        "--all-pages", action="store_true",
        help="Para PDFs: converte todas as páginas (gera um DXF por página)."
    )
    parser.add_argument(
        "-t", "--threshold", type=int, default=None,
        help="Valor fixo de threshold (0 a 255). Se omitido, usa Otsu automático."
    )
    parser.add_argument(
        "--keep-colors", action="store_true",
        help="Não inverte as cores (usar caso o desenho seja traço branco em fundo preto)."
    )
    parser.add_argument(
        "-e", "--epsilon", type=float, default=0.002,
        help="Fator de aproximação Douglas-Peucker (padrão: 0.002)."
    )
    parser.add_argument(
        "--min-area", type=float, default=10.0,
        help="Área mínima em pixels para descarte de ruído (padrão: 10.0)."
    )

    args = parser.parse_args()

    try:
        result = process_file(
            filepath=args.input,
            output_path=args.output,
            dpi=args.dpi,
            all_pages=args.all_pages,
            threshold_value=args.threshold,
            invert_colors=not args.keep_colors,
            approx_epsilon_ratio=args.epsilon,
            min_contour_area=args.min_area,
            progress_callback=lambda p, m: print(f"[{p}%] {m}"),
        )
        if isinstance(result, list):
            print(f"✅ {len(result)} arquivos DXF gerados com sucesso:")
            for p in result:
                print(f"   - {p}")
        else:
            print(f"✅ Arquivo DXF gerado com sucesso em: {result}")
    except Exception as exc:
        print(f"❌ Erro no processamento: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
