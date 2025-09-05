from fpdf import FPDF
import os

# 👉 Ruta base de las fuentes
BASE_FUENTES = r"C:\Users\USUARIO\OneDrive\Apps\CM_HorasExtras\dejavu-fonts-ttf-2.37\dejavu-fonts-ttf-2.37\ttf"

class PDFSimbolos(FPDF):
    def __init__(self):
        super().__init__()
        self.add_page()

        # Registrar variantes de DejaVu
        self.add_font("DejaVu", "", os.path.join(BASE_FUENTES, "DejaVuSans.ttf"))
        self.add_font("DejaVu", "B", os.path.join(BASE_FUENTES, "DejaVuSans-Bold.ttf"))
        self.add_font("DejaVu", "I", os.path.join(BASE_FUENTES, "DejaVuSans-Oblique.ttf"))

        self.set_font("DejaVu", "", 14)

    def mostrar_bloque(self, titulo, simbolos):
        self.set_font("DejaVu", "B", 12)
        self.cell(0, 10, titulo, ln=True)
        self.set_font("DejaVu", "", 14)
        self.multi_cell(0, 10, simbolos)
        self.ln(5)

# Crear PDF
pdf = PDFSimbolos()

# ✔ Bloque 1: Símbolos check / cruces
pdf.mostrar_bloque("✔ Checks y cruces:", "✔ ✘ ✓ ✗ ✕ ✖")

# ✔ Bloque 2: Flechas
pdf.mostrar_bloque("➡ Flechas:", "→ ← ↑ ↓ ↔ ↕ ⇐ ⇒ ⇑ ⇓ ⇔")

# ✔ Bloque 3: Geometría simple
pdf.mostrar_bloque("■ Figuras geométricas:", "■ □ ▲ △ ▼ ▽ ◆ ◇ ○ ●")

# ✔ Bloque 4: Estrellas y varios
pdf.mostrar_bloque("★ Estrellas y varios:", "★ ☆ ✦ ✧ ✩ ✪ ✫ ✬ ✭ ✮ ✯")

# ✔ Bloque 5: Monedas y legales
pdf.mostrar_bloque("€ Monedas y legales:", "€ $ £ ¥ © ® ™ § ¶")

# ✔ Bloque 6: Caritas y emojis simples
pdf.mostrar_bloque("☺ Caritas clásicas:", "☺ ☻ ☹ ❀ ✿ ✌")

# Exportar
salida = "test_simbolos.pdf"
pdf.output(salida)
print(f"PDF generado: {os.path.abspath(salida)}")





