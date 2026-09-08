# -*- coding: utf-8 -*-
"""
_leer_ods_personal() no debe mostrar el error crudo de Python cuando el
archivo simplemente no existe en este entorno (caso normal en la web: la
ruta I:\\Desde Facturacion\\... es una unidad de red de la oficina, nunca
alcanzable desde PythonAnywhere) -- eso no es un error real, solo "no hay
candidatos para mostrar". Un error real (archivo presente pero corrupto,
por ejemplo) sí debe seguir mostrándose.
"""
import servidor


def test_archivo_inexistente_no_da_error(monkeypatch, tmp_path):
    monkeypatch.setattr(servidor, "_ODS_PERSONAL", tmp_path / "no_existe.ods")
    candidatos, error = servidor._leer_ods_personal()
    assert candidatos == []
    assert error is None


def test_archivo_existente_pero_corrupto_si_muestra_error(monkeypatch, tmp_path):
    archivo = tmp_path / "corrupto.ods"
    archivo.write_text("esto no es un ods valido", encoding="utf-8")
    monkeypatch.setattr(servidor, "_ODS_PERSONAL", archivo)
    candidatos, error = servidor._leer_ods_personal()
    assert candidatos == []
    assert error is not None
