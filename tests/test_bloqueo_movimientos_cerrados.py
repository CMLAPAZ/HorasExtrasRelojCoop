# -*- coding: utf-8 -*-
"""Los movimientos asociados a un cierre manual son inmutables."""
import sqlite3
import tempfile
import gc
from pathlib import Path
from unittest.mock import patch

import servidor


def test_rutas_no_modifican_movimientos_cerrados():
    with tempfile.TemporaryDirectory() as tmp:
        db_file = Path(tmp) / "cierres_test.db"
        with patch.object(servidor, "DATOS_DIR", Path(tmp)), \
             patch.object(servidor, "DB_FILE", db_file), \
             patch.object(servidor, "_autenticado", lambda: True):
            servidor._init_db()
            with servidor._get_db() as conn:
                conn.execute(
                    "INSERT INTO cierres_francos "
                    "(id,cerrado_en,departamento,fecha_hasta,total_dias,estado) "
                    "VALUES (9,'2026-06-30','Ingenieros','2026-06-30',1,'ACTIVO')"
                )
                conn.execute(
                    "INSERT INTO francos_generados "
                    "(id,legajo,nombre,departamento,descripcion,dias,cargado_en,cierre_francos_id) "
                    "VALUES (1,'100','MANCIONI, Martin','Ingenieros','Junio',1,'2026-06-30',9)"
                )
                conn.execute(
                    "INSERT INTO francos_tomados "
                    "(id,legajo,nombre,tipo,fecha_desde,fecha_hasta,dias,estado,cierre_francos_id) "
                    "VALUES (1,'100','MANCIONI, Martin','UNICO','2026-06-10','2026-06-10',1,'Cerrado',9)"
                )
                conn.execute(
                    "INSERT INTO francos_semana_manual "
                    "(legajo,nombre,departamento,semana_num,mes,dias,guardado_en,cierre_francos_id) "
                    "VALUES ('100','MANCIONI, Martin','Ingenieros',1,'2026-06',2,'2026-06-30',9)"
                )
                conn.commit()

            servidor.app.config["TESTING"] = True
            with servidor.app.test_client() as client:
                resp_gen = client.post("/francos/generados/eliminar/1")
                assert "error=movimiento_cerrado" in resp_gen.headers["Location"]

                resp_tom = client.post("/francos/eliminar/1", data={"motivo": "error"})
                assert "error=movimiento_cerrado" in resp_tom.headers["Location"]

                resp_sem = client.post("/francos/guardar-manual-semana", data={
                    "semana_num": "1", "mes": "2026-06",
                    "dias_100": "7", "dias_101": "3",
                })
                assert resp_sem.status_code == 200
                bloqueados = resp_sem.get_json()["bloqueados"]
                assert bloqueados == [{"cierre_id": 9, "legajo": "100"}]

            conn = sqlite3.connect(str(db_file))
            assert conn.execute("SELECT COUNT(*) FROM francos_generados WHERE id=1").fetchone()[0] == 1
            assert conn.execute("SELECT estado FROM francos_tomados WHERE id=1").fetchone()[0] == "Cerrado"
            assert conn.execute(
                "SELECT dias FROM francos_semana_manual "
                "WHERE legajo='100' AND semana_num=1 AND mes='2026-06'"
            ).fetchone()[0] == 2
            assert conn.execute(
                "SELECT dias FROM francos_semana_manual "
                "WHERE legajo='101' AND semana_num=1 AND mes='2026-06'"
            ).fetchone()[0] == 3
            conn.close()
            gc.collect()
