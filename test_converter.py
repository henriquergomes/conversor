"""
Testes de integração: Imagem para DXF e PDF para DXF (Etapa 1 + Etapa 2).
Valida a função master process_file e o pipeline in-memory com PyMuPDF,
incluindo proteção contra o erro 'Overly large image' em arquivos gigantes.
"""

from pathlib import Path
import cv2
import ezdxf
import fitz  # PyMuPDF
import numpy as np

from converter import process_file


def test_pipeline():
    test_dir = Path("./test_output")
    test_dir.mkdir(exist_ok=True)

    # 1. Teste de Imagem direta (PNG -> DXF)
    img_path = test_dir / "test_img.png"
    dxf_img_path = test_dir / "test_img.dxf"

    img = np.full((400, 400, 3), 255, dtype=np.uint8)
    cv2.circle(img, (200, 200), 100, (0, 0, 0), -1)
    cv2.imwrite(str(img_path), img)

    result_img = process_file(img_path, dxf_img_path)
    print(f"1. Imagem processada com sucesso: {result_img}")
    assert dxf_img_path.exists(), "DXF de imagem não foi gerado!"

    # 2. Teste de PDF padrão via PyMuPDF (PDF -> DXF in-memory)
    pdf_path = test_dir / "test_doc.pdf"
    dxf_pdf_path = test_dir / "test_doc.dxf"

    pdf_doc = fitz.open()
    page = pdf_doc.new_page(width=300, height=300)
    rect = fitz.Rect(50, 50, 200, 200)
    page.draw_rect(rect, color=(0, 0, 0), fill=(0, 0, 0))
    pdf_doc.save(str(pdf_path))
    pdf_doc.close()

    result_pdf = process_file(pdf_path, dxf_pdf_path, dpi=300)
    print(f"2. PDF padrão processado com sucesso: {result_pdf}")
    assert dxf_pdf_path.exists(), "DXF de PDF não foi gerado!"

    # 3. Teste com PDF gigante (8000x8000 pontos) - Evita 'Overly large image'
    huge_pdf = test_dir / "huge_test.pdf"
    huge_dxf = test_dir / "huge_test.dxf"

    doc_huge = fitz.open()
    p_huge = doc_huge.new_page(width=8000, height=8000)
    p_huge.draw_rect(fitz.Rect(1000, 1000, 7000, 7000), color=(0, 0, 0), fill=(0, 0, 0))
    doc_huge.save(str(huge_pdf))
    doc_huge.close()

    result_huge = process_file(huge_pdf, huge_dxf, dpi=300)
    print(f"3. PDF gigante (8000pt) processado adaptativamente: {result_huge}")
    assert huge_dxf.exists(), "DXF do PDF gigante não foi gerado!"

    print("\n✅ Todos os testes de validação passaram com sucesso!")


if __name__ == "__main__":
    test_pipeline()
