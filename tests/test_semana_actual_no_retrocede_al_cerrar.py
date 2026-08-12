# -*- coding: utf-8 -*-
"""
periodo_cerrar() quitaba las semanas cerradas de metadata["semanas"] y
DESPUÉS recalculaba meta["semana_actual"] = max(numero de las que quedan)
-- el mismo patrón que usa eliminar_semana(). La diferencia crítica:
eliminar_semana() SÍ borra el semana_N.csv físico (así que ese número queda
libre de verdad), pero periodo_cerrar() NUNCA borra los CSV -- solo los saca
de la lista visible. Si el departamento recién cerrado tenía el número
global más alto del sistema, el contador retrocedía y la PRÓXIMA semana
cargada (de cualquier departamento) recibía el mismo número global que una
semana ya cerrada, pisando su semana_N.csv en disco.

Reportado por la usuaria (12/08/2026): el "Ver acumulado" del cierre #7 de
Redes (MELGAREJO MANUEL) mostraba 36h de OT100 en vez de las 38h reales
guardadas en periodo_empleados/confirmaciones -- consistente con que el
CSV de una de sus semanas fue sobreescrito por una semana posterior antes
de generar ese informe.

Fix: periodo_cerrar() ya no toca meta["semana_actual"] -- solo saca las
semanas cerradas de la lista visible, dejando el contador global intacto
(monotónico, nunca reutilizable), igual que ya hace correctamente para los
demás datos permanentes del cierre.
"""
import pytest

import servidor


@pytest.fixture
def db_temporal(tmp_path, monkeypatch):
    db_file = tmp_path / "cierres_test.db"
    monkeypatch.setattr(servidor, "DATOS_DIR", tmp_path)
    monkeypatch.setattr(servidor, "DB_FILE", db_file)
    monkeypatch.setattr(servidor, "SEMANAS_DIR", tmp_path / "semanas")
    monkeypatch.setattr(servidor, "PERIODOS_DIR", tmp_path / "periodos")
    monkeypatch.setattr(servidor, "CONFIRM_DIR", tmp_path / "confirmaciones")
    servidor._init_db()
    servidor._sesion.clear()
    return db_file


@pytest.fixture(autouse=True)
def _patch_io(monkeypatch):
    monkeypatch.setattr(servidor, "_autenticado", lambda: True)


@pytest.fixture
def client():
    servidor.app.config["TESTING"] = True
    with servidor.app.test_client() as c:
        yield c


def test_semana_actual_no_retrocede_al_cerrar_periodo(db_temporal, client, monkeypatch):
    # Redes tiene las semanas globales 1-5, el número más alto del sistema.
    servidor._guardar_metadata({
        "semana_actual": 5,
        "semanas": [
            {"numero": n, "num_depto": n, "departamento": "Redes",
             "fecha_desde": "2026-06-29", "fecha_hasta": "2026-08-02"}
            for n in range(1, 6)
        ],
    })

    resumen_fijo = [{
        "legajo": "150", "nombre": "MELGAREJO MANUEL", "departamento": "Redes",
        "ot50": "24h", "ot100": "38h", "comidas": 7, "francos": 3, "tardanzas": 0,
        "semanas": [1, 2, 3, 4, 5], "confirmado": True, "pendientes": [], "dias": [],
        "excluido_ot": False, "liquida_ot": True, "observacion_liquidacion": "",
    }]
    monkeypatch.setattr(servidor, "_calcular_periodo",
                         lambda desde, hasta, departamento=None: resumen_fijo)

    form = {"desde": "1", "hasta": "5", "departamento": "redes",
            "fecha_desde": "2026-06-29", "fecha_hasta": "2026-08-02"}
    resp = client.post("/periodo/cerrar", data=form)
    assert resp.status_code == 200, resp.get_data(as_text=True)

    meta = servidor._cargar_metadata()
    assert meta["semanas"] == [], "las semanas cerradas sí deben salir de la lista visible"
    assert meta["semana_actual"] == 5, (
        "el contador global NO debe retroceder al cerrar -- si retrocede, la "
        "próxima semana cargada reutiliza un número ya usado por semana_1.csv..semana_5.csv "
        "(que siguen en disco, sin borrar) y pisa esos archivos"
    )


def test_semana_nueva_despues_de_cerrar_no_reutiliza_numero_de_semana_cerrada(db_temporal, client, monkeypatch):
    """Reproduce el escenario completo: cerrar Redes (semanas 1-5), y verificar
    que la semana que se carga después recibe el número 6, no el 1 -- que ya
    tiene un semana_1.csv real en disco perteneciente al cierre anterior."""
    servidor._guardar_metadata({
        "semana_actual": 5,
        "semanas": [
            {"numero": n, "num_depto": n, "departamento": "Redes",
             "fecha_desde": "2026-06-29", "fecha_hasta": "2026-08-02"}
            for n in range(1, 6)
        ],
    })
    resumen_fijo = [{
        "legajo": "150", "nombre": "MELGAREJO MANUEL", "departamento": "Redes",
        "ot50": "24h", "ot100": "38h", "comidas": 7, "francos": 3, "tardanzas": 0,
        "semanas": [1, 2, 3, 4, 5], "confirmado": True, "pendientes": [], "dias": [],
        "excluido_ot": False, "liquida_ot": True, "observacion_liquidacion": "",
    }]
    monkeypatch.setattr(servidor, "_calcular_periodo",
                         lambda desde, hasta, departamento=None: resumen_fijo)
    form = {"desde": "1", "hasta": "5", "departamento": "redes",
            "fecha_desde": "2026-06-29", "fecha_hasta": "2026-08-02"}
    client.post("/periodo/cerrar", data=form)

    # Simula que semana_1.csv del cierre anterior sigue en disco (real:
    # periodo_cerrar nunca lo borra).
    servidor.SEMANAS_DIR.mkdir(exist_ok=True)
    (servidor.SEMANAS_DIR / "semana_1.csv").write_text("legajo,fecha\n150,2026-06-29\n", encoding="utf-8")

    meta = servidor._cargar_metadata()
    nuevo_numero = meta["semana_actual"] + 1
    assert nuevo_numero == 6, "la próxima semana debe numerarse 6, no reutilizar 1"
