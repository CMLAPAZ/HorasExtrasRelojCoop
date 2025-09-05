# test_import.py
try:
    from fpdf import FPDF
    print("✅ Import correcto:", FPDF)
except Exception as e:
    print("❌ Error en el import:", e)
