# -*- coding: utf-8 -*-
"""Anulación segura del último cierre manual por departamento."""
import gc
import json
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

import servidor


def test_anula_solo_ultimo_y_no_toca_movimientos_nuevos():
    with tempfile.TemporaryDirectory() as tmp:
        db_file = Path(tmp) / "cierres_test.db"
        with patch.object(servidor, "DATOS_DIR", Path(tmp)), \
             patch.object(servidor, "DB_FILE", db_file), \
             patch.object(servidor, "_autenticado", lambda: True):
            servidor._init_db()
            base = {"100": {
                "nombre": "MANCIONI, Martin", "saldo": 5, "nota": "base",
                "cargado_en": "2026-05-31", "tomados_al_corte": 2,
                "gen_extra_al_corte": 3, "fecha_corte": "2026-05-31",
            }}
            with servidor._get_db() as conn:
                conn.execute(
                    "INSERT INTO francos_saldo_inicial "
                    "(legajo,nombre,saldo,nota,cargado_en,tomados_al_corte,gen_extra_al_corte,fecha_corte) "
                    "VALUES ('100','MANCIONI, Martin',99,'posterior','2026-06-30',9,8,'2026-06-30')"
                )
                conn.execute(
                    "INSERT INTO cierres_francos "
                    "(id,cerrado_en,departamento,fecha_hasta,total_dias,estado,base_anterior) "
                    "VALUES (1,'2026-05-31T10:00:00','Ingenieros','2026-05-31',0,'ACTIVO',?)",
                    (json.dumps(base),),
                )
                conn.execute(
                    "INSERT INTO cierres_francos "
                    "(id,cerrado_en,departamento,fecha_hasta,total_dias,estado,base_anterior) "
                    "VALUES (2,'2026-06-30T10:00:00','Ingenieros','2026-06-30',1,'ACTIVO',?)",
                    (json.dumps(base),),
                )
                # Un cierre posterior de otro departamento no debe interferir.
                conn.execute(
                    "INSERT INTO cierres_francos "
                    "(id,cerrado_en,departamento,fecha_hasta,total_dias,estado,base_anterior) "
                    "VALUES (3,'2026-07-01T10:00:00','Guardias','2026-06-30',0,'ACTIVO',?)",
                    (json.dumps({"113": None}),),
                )
                conn.execute(
                    "INSERT INTO francos_tomados "
                    "(id,legajo,nombre,tipo,fecha_desde,fecha_hasta,dias,estado,estado_antes_cierre,cierre_francos_id) "
                    "VALUES (1,'100','MANCIONI, Martin','UNICO','2026-06-10','2026-06-10',1,'Cerrado','Pendiente',2)"
                )
                conn.execute(
                    "INSERT INTO francos_tomados "
                    "(id,legajo,nombre,tipo,fecha_desde,fecha_hasta,dias,estado,cierre_francos_id) "
                    "VALUES (2,'100','MANCIONI, Martin','UNICO','2026-07-05','2026-07-05',1,'Aprobado',NULL)"
                )
                conn.execute(
                    "INSERT INTO francos_generados "
                    "(id,legajo,nombre,departamento,descripcion,dias,cargado_en,cierre_francos_id) "
                    "VALUES (1,'100','MANCIONI, Martin','Ingenieros','Junio',1,'2026-06-30',2),"
                    "(2,'100','MANCIONI, Martin','Ingenieros','Julio',1,'2026-07-05',NULL)"
                )
                conn.execute(
                    "INSERT INTO francos_semana_manual "
                    "(legajo,nombre,departamento,semana_num,mes,dias,guardado_en,cierre_francos_id) "
                    "VALUES ('100','MANCIONI, Martin','Ingenieros',1,'2026-06',1,'2026-06-30',2)"
                )
                conn.commit()

            servidor.app.config["TESTING"] = True
            with servidor.app.test_client() as client:
                anterior = client.post("/francos/cierre/anular/1", data={"motivo": "error"})
                assert anterior.status_code == 409
                assert "\u00faltimo cierre activo" in anterior.get_json()["error"]

                ultimo = client.post("/francos/cierre/anular/2", data={"motivo": "corregir carga"})
                assert ultimo.status_code == 200
                assert ultimo.get_json()["desbloqueados"] == {
                    "tomados": 1, "generados": 1, "semanales": 1,
                }

            conn = sqlite3.connect(str(db_file))
            assert conn.execute("SELECT estado FROM cierres_francos WHERE id=2").fetchone()[0] == "ANULADO"
            assert conn.execute(
                "SELECT saldo,tomados_al_corte,gen_extra_al_corte FROM francos_saldo_inicial WHERE legajo='100'"
            ).fetchone() == (5, 2, 3)
            assert conn.execute(
                "SELECT estado,cierre_francos_id FROM francos_tomados WHERE id=1"
            ).fetchone() == ("Pendiente", None)
            assert conn.execute(
                "SELECT estado,cierre_francos_id FROM francos_tomados WHERE id=2"
            ).fetchone() == ("Aprobado", None)
            assert conn.execute(
                "SELECT cierre_francos_id FROM francos_generados WHERE id=1"
            ).fetchone()[0] is None
            assert conn.execute(
                "SELECT cierre_francos_id FROM francos_generados WHERE id=2"
            ).fetchone()[0] is None
            conn.close()
            gc.collect()
