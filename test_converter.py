"""
Testes de integração: Imagem para DXF e PDF para DXF (Etapa 1 + Etapa 2).
Valida a função master process_file e o pipeline in-memory com PyMuPDF.
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

    # -------------------------------------------------------------
    # 1. Teste de Imagem direta (PNG -> DXF)
    # -------------------------------------------------------------
    img_path = test_dir / "test_img.png"
    dxf_img_path = test_dir / "test_img.dxf"

    img = np.full((400, 400, 3), 255, dtype=np.uint8)
    cv2.circle(img, (200, 200), 100, (0, 0, 0), -1)  # Círculo preto
    cv2.imwrite(str(img_path), img)

    result_img = process_file(img_path, dxf_img_path)
    print(f"1. Imagem processada com sucesso: {result_img}")
    assert dxf_img_path.exists(), "DXF de imagem não foi gerado!"

    doc_img = ezdxf.readfile(str(dxf_img_path))
    polys_img = list(doc_img.modelspace().query("LWPOLYLINE"))
    assert len(polys_img) >= 1 and polys_img[0].closed, "Falha na validação do DXF de imagem!"

    # -------------------------------------------------------------
    # 2. Teste de PDF via PyMuPDF (PDF -> DXF in-memory)
    # -------------------------------------------------------------
    pdf_path = test_dir / "test_doc.pdf"
    dxf_pdf_path = test_dir / "test_doc.dxf"

    # Cria um documento PDF com PyMuPDF contendo um retângulo preto
    pdf_doc = fitz.open()
    page = pdf_doc.new_page(width=300, height=300)
    # Desenha retângulo preenchido
    rect = fitz.Rect(50, 50, 200, 200)
    page.draw_rect(rect, color=(0, 0, 0), fill=(0, 0, 0))
    pdf_doc.save(str(pdf_path))
    pdf_doc.close()

    result_pdf = process_file(pdf_path, dxf_pdf_path, dpi=300)
    print(f"2. PDF processado com sucesso: {result_pdf}")
    assert dxf_pdf_path.exists(), "DXF de PDF não foi gerado!"

    doc_pdf = ezdxf.readfile(str(dxf_pdf_path))
    polys_pdf = list(doc_pdf.modelspace().query("LWPOLYLINE"))
    assert len(polys_pdf) >= 1, "Nenhuma polilinha encontrada no DXF do PDF!"
    assert polys_pdf[0].closed, "A polilinha do PDF não está fechada!"

    print(f"   Polilinhas geradas do PDF: {len(polys_pdf)}, Fechada={polys_pdf[0].closed}")
    print("\n✅ Todos os testes de Imagem e PDF via PyMuPDF passaram com sucesso!")


if __name__ == "__main__":
    test_pipeline()
