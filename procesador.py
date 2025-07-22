from datetime import datetime, timedelta, time
import pandas as pd
import json
import os

CONFIG_PATH = "config.json"

def cargar_feriados():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return set(json.load(f).get("feriados", []))
    return set()

def es_feriado(fecha_str, feriados):
    return fecha_str in feriados

def es_fin_de_semana(fecha):
    return fecha.weekday() >= 5

def redondear_timedelta(td):
    segundos = td.total_seconds()
    if segundos % 3600 >= 1800:
        return timedelta(hours=int(segundos // 3600) + 1)
    else:
        return timedelta(hours=int(segundos // 3600))

def procesar_fichadas(df):
    df["FechaHora"] = pd.to_datetime(df["FechaHora"], errors='coerce')
    df.dropna(subset=["FechaHora"], inplace=True)
    df = df.sort_values(by=["Legajo", "FechaHora"])
    feriados = cargar_feriados()
    resultados = []

    for (legajo), fichadas_legajo in df.groupby("Legajo"):
        fichadas_legajo = fichadas_legajo.reset_index(drop=True)
        registros_por_dia = {}

        # Mapear nombre y departamento
        cols = [c.lower().strip() for c in fichadas_legajo.columns]
        if "nombre" in cols:
            nombre_empleado = fichadas_legajo[fichadas_legajo.columns[cols.index("nombre")]].iloc[0]
        else:
            nombre_empleado = ""
        if "departamento" in cols:
            departamento = fichadas_legajo[fichadas_legajo.columns[cols.index("departamento")]].iloc[0]
        else:
            departamento = ""

        for _, fila in fichadas_legajo.iterrows():
            fecha = fila["FechaHora"].date()
            tipo = fila["Tipo"].upper()
            if fecha not in registros_por_dia:
                registros_por_dia[fecha] = []
            registros_por_dia[fecha].append((fila["FechaHora"], tipo))

        registros_empleado = []

        for fecha, registros in sorted(registros_por_dia.items()):
            registros.sort()
            observaciones_dia = []
            es_fer = es_feriado(str(fecha), feriados)
            es_findesemana = es_fin_de_semana(fecha)

            # Limpiar fichadas duplicadas
            limpiados = []
            i = 0
            while i < len(registros):
                actual = registros[i]
                if i + 1 < len(registros):
                    siguiente = registros[i + 1]
                    if actual[1] == siguiente[1] and actual[1] == "ENTRADA":
                        if (siguiente[0] - actual[0]).total_seconds() < 120:
                            i += 1
                            continue
                limpiados.append(actual)
                i += 1
            registros = limpiados

            tramos = []
            i = 0
            while i < len(registros) - 1:
                tipo_i = registros[i][1]
                tipo_j = registros[i + 1][1]

                if tipo_i == "ENTRADA" and tipo_j == "SALIDA":
                    ent = registros[i][0]
                    sal = registros[i + 1][0]
                    if sal < ent:
                        sal += timedelta(days=1)
                    tramos.append((ent, sal))
                    i += 2

                elif tipo_i == "SALIDA" and tipo_j == "ENTRADA":
                    try:
                        diferencia = registros[i + 1][0] - registros[i][0]
                        if diferencia < timedelta(minutes=2) or diferencia > timedelta(hours=4):
                            i += 1
                            continue
                        else:
                            ent = registros[i + 1][0]
                            sal = registros[i][0]
                            if sal < ent:
                                sal += timedelta(days=1)
                            tramos.append((ent, sal))
                            observaciones_dia.append("Corrección automática: SALIDA => ENTRADA")
                            i += 2
                    except Exception as e:
                        observaciones_dia.append(f"Error al corregir tramo SALIDA=>ENTRADA: {e}")
                        i += 1
                else:
                    i += 1

            normales_totales = timedelta()
            extra_50_totales = timedelta()
            extra_100_totales = timedelta()
            jornada_total = timedelta()
            comida = 0
            tarde = 0
            normales_asignadas = False

            for idx, (ent, sal) in enumerate(tramos):
                if idx == 0 and not es_fer and not es_findesemana and ent.time() < time(6, 0):
                    ent = datetime.combine(ent.date(), time(6, 0))
                    observaciones_dia.append("Entrada antes de las 06:00 ajustada")

                jornada = sal - ent
                jornada_total += jornada
                normales = timedelta()
                extra_50 = timedelta()
                extra_100 = timedelta()

                if idx == 0 and ent.time() >= time(6, 6) and not es_fer and not es_findesemana:
                    tarde = 1

                if es_fer or es_findesemana:
                    normales = timedelta()
                    extra_50 = timedelta()
                    extra_100 = sal - ent
                else:
                    ini_normal = datetime.combine(ent.date(), time(6, 0))
                    fin_normal = datetime.combine(ent.date(), time(13, 0))
                    fin_50 = datetime.combine(ent.date(), time(21, 0))

                    inicio = ent
                    final = sal

                    if idx == 0 and inicio < fin_normal:
                        normales = min(final, fin_normal) - inicio
                        normales = max(normales, timedelta())
                        normales = min(normales, timedelta(hours=7))
                        normales_asignadas = True
                    else:
                        normales = timedelta()

                    ini_50 = max(inicio, fin_normal)
                    fin_50_real = min(final, fin_50)
                    extra_50 = fin_50_real - ini_50
                    if extra_50 < timedelta():
                        extra_50 = timedelta()

                    ini_100 = max(inicio, fin_50)
                    extra_100 = final - ini_100
                    if extra_100 < timedelta():
                        extra_100 = timedelta()

                normales_totales += normales
                extra_50_totales += extra_50
                extra_100_totales += extra_100

                # Reglas comida/franco iguales
                if idx == 0:
                    if es_fer or es_findesemana:
                        corridos = []
                        if tramos:
                            actual_ini, actual_fin = tramos[0]
                            for ent2, sal2 in tramos[1:]:
                                if ent2 - actual_fin <= timedelta(minutes=30):
                                    actual_fin = sal2
                                else:
                                    corridos.append((actual_ini, actual_fin))
                                    actual_ini, actual_fin = ent2, sal2
                            corridos.append((actual_ini, actual_fin))

                        for ini, fin in corridos:
                            duracion = fin - ini
                            if duracion >= timedelta(hours=14):
                                comida = 2
                                break
                            elif duracion >= timedelta(hours=7, minutes=30):
                                comida = 1
                    else:
                        salida_normal = datetime.combine(fecha, time(13, 0))
                        tiempo_post_13 = max(timedelta(), sal - salida_normal)
                        if tiempo_post_13 > timedelta(minutes=30):
                            comida = 1
                            if tiempo_post_13 >= timedelta(hours=7, minutes=30):
                                comida = 2

                    observacion_dia_tipo = "Feriado" if es_fer else (
                        "Domingo" if fecha.weekday() == 6 else (
                            "Sábado" if fecha.weekday() == 5 else ""))
                    if observacion_dia_tipo:
                        observaciones_dia.insert(0, f"Día {observacion_dia_tipo}")

            franco = 1 if (es_fer or es_findesemana) and jornada_total > timedelta(hours=3, minutes=30) else 0
            # Adjuntar los tramos para aplanar luego:
            registros_empleado.append({
                "Fecha": str(fecha),
                "Entrada": tramos[0][0] if tramos else "",
                "Salida": tramos[-1][1] if tramos else "",
                "Normales": redondear_timedelta(normales_totales),
                "50%": redondear_timedelta(extra_50_totales),
                "100%": redondear_timedelta(extra_100_totales),
                "Tarde": tarde,
                "FRANCO": franco,
                "COMIDA": comida,
                "Observaciones": "; ".join(observaciones_dia),
                "Tramos": tramos  # Agregamos los tramos acá
            })

        resultados.append({
            "nombre": nombre_empleado,
            "departamento": departamento,
            "legajo": legajo,
            "registros": registros_empleado
        })

    return resultados

# ---- FUNCIÓN DE APLANADO FINAL ----
def aplanar_registros_por_tramo(lista_empleados):
    empleados_aplanados = []
    for empleado in lista_empleados:
        nuevos_registros = []
        for reg in empleado["registros"]:
            fecha = reg["Fecha"]
            tramos = reg.get("Tramos", [])
            if not tramos and reg.get("Entrada") and reg.get("Salida"):
                tramos = [(reg["Entrada"], reg["Salida"])]
            n_tramos = len(tramos)
            for idx, (entrada, salida) in enumerate(tramos):
                is_last = (idx == n_tramos - 1)
                nuevos_registros.append({
                    "Fecha": fecha,
                    "Entrada": entrada.strftime("%H:%M:%S") if hasattr(entrada, "strftime") else str(entrada),
                    "Salida": salida.strftime("%H:%M:%S") if hasattr(salida, "strftime") else str(salida),
                    "Normales": reg["Normales"] if is_last else timedelta(0),
                    "50%": reg["50%"] if is_last else timedelta(0),
                    "100%": reg["100%"] if is_last else timedelta(0),
                    "Tarde": reg["Tarde"] if is_last else 0,
                    "FRANCO": reg["FRANCO"] if is_last else 0,
                    "COMIDA": reg["COMIDA"] if is_last else 0,
                    "Observaciones": reg["Observaciones"] if is_last else ""
                })
        nuevo_empleado = empleado.copy()
        nuevo_empleado["registros"] = nuevos_registros
        empleados_aplanados.append(nuevo_empleado)
    return empleados_aplanados

