import json
from io import BytesIO

from openpyxl import Workbook, load_workbook

import servidor


def _planilla():
    wb = Workbook()
    ws = wb.active
    ws.title = "Julio 2026"
    for fila, legajo in enumerate((100, 101, 113, 118), start=8):
        ws.cell(fila, 1).value = legajo
        ws.cell(fila, 3).value = 99
        ws.cell(fila, 6).value = 5
        ws.cell(fila, 9).value = f"=F{fila}+G{fila}-H{fila}"
        ws.cell(fila, 12).value = 30
    salida = BytesIO()
    wb.save(salida)
    return salida.getvalue()


def test_actualiza_solo_francos_orig_y_tomados():
    cierres = {
        "ingenieros": {"saldo_anterior": json.dumps({
            "100": {"generados": 1, "tomados": 2},
            "101": {"generados": 0, "tomados": 1},
        })},
        "guardias": {"saldo_anterior": json.dumps({
            "113": {"generados": 3, "tomados": 0},
            "118": {"generados": 1, "tomados": 1},
        })},
    }
    resultado = servidor._actualizar_planilla_francos(_planilla(), "2026-07", cierres)
    ws = load_workbook(resultado, data_only=False)["Julio 2026"]

    assert (ws["G8"].value, ws["H8"].value) == (1, 2)
    assert (ws["G9"].value, ws["H9"].value) == (None, 1)
    assert (ws["G10"].value, ws["H10"].value) == (3, None)
    assert (ws["G11"].value, ws["H11"].value) == (1, 1)
    assert ws["C8"].value == 99
    assert ws["F8"].value == 5
    assert ws["I8"].value == "=F8+G8-H8"
    assert ws["L8"].value == 30


def test_rechaza_planilla_si_falta_un_legajo():
    cierres = {
        "ingenieros": {"saldo_anterior": json.dumps({"999": {"generados": 1, "tomados": 0}})},
        "guardias": {"saldo_anterior": json.dumps({"113": {"generados": 0, "tomados": 0}})},
    }
    try:
        servidor._actualizar_planilla_francos(_planilla(), "2026-07", cierres)
        assert False, "Debía rechazar el legajo ausente"
    except ValueError as exc:
        assert "999" in str(exc)
