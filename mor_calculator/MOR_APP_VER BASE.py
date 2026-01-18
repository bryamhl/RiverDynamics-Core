import sys
import os
import re
import json
import tempfile
import logging
from pathlib import Path
from datetime import datetime

import geopandas as gpd
import pandas as pd

from PyQt5.QtWidgets import (
    QApplication, QWidget, QLabel, QLineEdit, QPushButton, QFileDialog,
    QVBoxLayout, QMessageBox, QTableWidget, QTableWidgetItem, QComboBox,
    QAbstractItemView, QHBoxLayout, QFrame, QProgressBar, QCheckBox
)
from PyQt5.QtGui import QIcon
from PyQt5.QtCore import Qt, QThread, pyqtSignal

# Configuración persistente
CONFIG_FILE = os.path.join(Path.home(), ".river_activity_config.json")
DEFAULT_CONFIG = {
    "last_dir_a": "",
    "last_dir_b": "",
    "last_dir_valle": "",
    "last_dir_save": "",
    "theme": "light"
}

# Datos del desarrollador / metadata
APP_TITLE = "RIVER ACTIVITY BASE - VER 1.3"
DEVELOPER = "Developed by: Bryam Juan Hinostroza León"
CONTACT = "2025"


def load_config():
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            for k, v in DEFAULT_CONFIG.items():
                if k not in data:
                    data[k] = v
            return data
    except Exception:
        pass
    return DEFAULT_CONFIG.copy()


def save_config(config):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("No se pudo guardar configuración:", e)


# Worker para procesar en hilo separado y actualizar progreso
class ProcessingThread(QThread):
    progress = pyqtSignal(int, str)  # porcentaje, mensaje
    finished = pyqtSignal(dict, str)  # resumen, carpeta_salida o mensaje de error

    def __init__(self, path_a, path_b, path_valle, year_a, year_b, nombre_rio, campo_tramos, usar_carpeta, carpeta_salida):
        super().__init__()
        self.path_a = path_a
        self.path_b = path_b
        self.path_valle = path_valle
        self.year_a = year_a
        self.year_b = year_b
        self.nombre_rio = nombre_rio
        self.campo_tramos = campo_tramos
        self.usar_carpeta = usar_carpeta
        self.carpeta_salida = carpeta_salida

    def run(self):
        try:
            self.progress.emit(5, "Leyendo shapefiles...")
            shp_a = gpd.read_file(self.path_a)
            shp_b = gpd.read_file(self.path_b)
            valle = gpd.read_file(self.path_valle)

            # Detectar y unificar CRS
            crs_a = shp_a.crs
            crs_b = shp_b.crs
            crs_valle = valle.crs

            target_crs = crs_a or crs_b or crs_valle
            if target_crs is None:
                # fallback a EPSG:32719 si no hay CRSs
                target_crs = {'init': 'epsg:32719'}

            # Reproyectar si es necesario
            if shp_a.crs != target_crs:
                self.progress.emit(10, f"Reproyectando SHP A a CRS unificado...")
                shp_a = shp_a.to_crs(target_crs)
            if shp_b.crs != target_crs:
                self.progress.emit(15, f"Reproyectando SHP B a CRS unificado...")
                shp_b = shp_b.to_crs(target_crs)
            if valle.crs != target_crs:
                self.progress.emit(18, f"Reproyectando SHP Valle a CRS unificado...")
                valle = valle.to_crs(target_crs)

            self.progress.emit(22, "Arreglando geometrías (buffer 0)...")
            for df in (shp_a, shp_b, valle):
                try:
                    df["geometry"] = df["geometry"].buffer(0)
                except Exception:
                    pass

            self.progress.emit(30, "Calculando intersecciones...")
            inter = gpd.overlay(shp_b, shp_a, how="intersection")

            # Guardar intersección
            if self.usar_carpeta:
                inter_path = os.path.join(self.carpeta_salida, f"INTERSECCION_{self.nombre_rio}_{self.year_a}_{self.year_b}.shp")
                inter.to_file(inter_path)

            self.progress.emit(45, "Segmentando por tramos (valle)...")
            inter_tramos = gpd.overlay(inter, valle, how="intersection")
            inter_tramos["AREA"] = inter_tramos.geometry.area

            if self.usar_carpeta:
                inter_tramos.to_file(os.path.join(self.carpeta_salida, f"INTERSECCION_SEGMENTADA_{self.nombre_rio}_{self.year_a}_{self.year_b}.shp"))

            self.progress.emit(60, "Calculando deposición y erosión...")
            deposicion_temp = gpd.overlay(shp_a, inter, how="difference")
            deposicion = gpd.overlay(deposicion_temp, valle, how="intersection")
            deposicion["AREA"] = deposicion.geometry.area
            if self.usar_carpeta:
                deposicion.to_file(os.path.join(self.carpeta_salida, f"DEPOSICION_{self.nombre_rio}_{self.year_a}_{self.year_b}.shp"))

            erosion_temp = gpd.overlay(shp_b, inter, how="difference")
            erosion = gpd.overlay(erosion_temp, valle, how="intersection")
            erosion["AREA"] = erosion.geometry.area
            if self.usar_carpeta:
                erosion.to_file(os.path.join(self.carpeta_salida, f"EROSION_{self.nombre_rio}_{self.year_a}_{self.year_b}.shp"))

            self.progress.emit(80, "Resumiendo por tramos...")
            resumen = {}
            tramos_unicos = valle[self.campo_tramos].unique()
            for i, tramo in enumerate(tramos_unicos):
                area_inter = float(inter_tramos[inter_tramos[self.campo_tramos] == tramo]['AREA'].sum()) if not inter_tramos.empty else 0.0
                area_depo = float(deposicion[deposicion[self.campo_tramos] == tramo]['AREA'].sum()) if not deposicion.empty else 0.0
                area_er = float(erosion[erosion[self.campo_tramos] == tramo]['AREA'].sum()) if not erosion.empty else 0.0
                resumen[tramo] = {
                    "INTERSECCION": area_inter,
                    "DEPOSICION": area_depo,
                    "EROSION": area_er
                }
                # emitir progreso parcial según tramos
                pct = 80 + int((i / max(1, len(tramos_unicos))) * 15)
                self.progress.emit(min(pct, 95), f"Procesando tramos... {i+1}/{len(tramos_unicos)}")

            # Guardar resumen a Excel
            self.progress.emit(95, "Exportando resultados a Excel...")
            df_resumen = pd.DataFrame([
                {"TRAMO": t, "INTERSECCION": v['INTERSECCION'], "EROSION": v['EROSION'], "DEPOSICION": v['DEPOSICION']}
                for t, v in resumen.items()
            ])

            if self.usar_carpeta:
                excel_path = os.path.join(self.carpeta_salida, f"RESUMEN_{self.nombre_rio}_{self.year_a}_{self.year_b}.xlsx")
                df_resumen.to_excel(excel_path, index=False)

                # Crear log
                log_path = os.path.join(self.carpeta_salida, "process_log.txt")
                # registrar con logging
                logging.basicConfig(filename=log_path, level=logging.INFO, format='%(asctime)s %(levelname)s:%(message)s')
                logging.info(f"Proceso completado para {self.nombre_rio} {self.year_a}-{self.year_b}")
                logging.info(f"Archivos guardados en: {self.carpeta_salida}")

            self.progress.emit(100, "Completado")
            self.finished.emit(resumen, self.carpeta_salida if self.usar_carpeta else "")

        except Exception as e:
            self.finished.emit({}, f"ERROR: {str(e)}")


class RiverActivityApp(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(900, 650)

        # Config
        self.config = load_config()
        self.last_dir_a = self.config.get("last_dir_a", "")
        self.last_dir_b = self.config.get("last_dir_b", "")
        self.last_dir_valle = self.config.get("last_dir_valle", "")
        self.last_dir_save = self.config.get("last_dir_save", "")
        self.theme = self.config.get("theme", "light")

        # Paths
        self.path_shp_a = ""
        self.path_shp_b = ""
        self.path_valle = ""

        # GeoDataFrames temporales
        self.gdf_valle = None

        self.init_ui()

    def init_ui(self):
        main_layout = QVBoxLayout(self)

        title_label = QLabel(f"<h1>{APP_TITLE}</h1>")
        title_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(title_label)

        # Carga archivos
        files_frame = QFrame()
        files_layout = QHBoxLayout(files_frame)

        # SHP A
        v_a = QVBoxLayout()
        self.btn_shp_a = QPushButton("Seleccionar SHP Año A")
        self.btn_shp_a.clicked.connect(self.load_shp_a)
        self.input_year_a = QLineEdit()
        self.input_year_a.setPlaceholderText("Año A (ej. 2000)")
        v_a.addWidget(self.btn_shp_a)
        v_a.addWidget(self.input_year_a)

        # SHP B
        v_b = QVBoxLayout()
        self.btn_shp_b = QPushButton("Seleccionar SHP Año B")
        self.btn_shp_b.clicked.connect(self.load_shp_b)
        self.input_year_b = QLineEdit()
        self.input_year_b.setPlaceholderText("Año B (ej. 2010)")
        v_b.addWidget(self.btn_shp_b)
        v_b.addWidget(self.input_year_b)

        # Valle
        v_valle = QVBoxLayout()
        self.btn_valle = QPushButton("Seleccionar SHP Valle Segmentado")
        self.btn_valle.clicked.connect(self.load_valle)
        self.combo_tramos = QComboBox()
        v_valle.addWidget(self.btn_valle)
        v_valle.addWidget(self.combo_tramos)

        files_layout.addLayout(v_a)
        files_layout.addLayout(v_b)
        files_layout.addLayout(v_valle)
        main_layout.addWidget(files_frame)

        # Nombre del río con botón detectar
        nombre_frame = QHBoxLayout()
        self.input_rio = QLineEdit()
        self.input_rio.setPlaceholderText("Nombre del río (puede detectar automáticamente)")
        btn_detect_rio = QPushButton("Detectar nombre río")
        btn_detect_rio.clicked.connect(self.detect_nombre_rio)
        nombre_frame.addWidget(self.input_rio)
        nombre_frame.addWidget(btn_detect_rio)
        main_layout.addLayout(nombre_frame)

        # Opciones
        opts_frame = QHBoxLayout()
        self.chk_use_folder = QCheckBox("Guardar todos los resultados en una carpeta (recomendado)")
        self.chk_use_folder.setChecked(True)
        opts_frame.addWidget(self.chk_use_folder)

        self.theme_checkbox = QCheckBox("Modo oscuro")
        self.theme_checkbox.setChecked(self.theme == "dark")
        self.theme_checkbox.stateChanged.connect(self.toggle_theme)
        opts_frame.addWidget(self.theme_checkbox)

        main_layout.addLayout(opts_frame)

        # Botones de acción
        actions_frame = QHBoxLayout()
        self.btn_procesar = QPushButton("Procesar")
        self.btn_procesar.clicked.connect(self.start_processing)
        self.btn_reset = QPushButton("Resetear")
        self.btn_reset.clicked.connect(self.resetear_formulario)
        actions_frame.addWidget(self.btn_procesar)
        actions_frame.addWidget(self.btn_reset)
        main_layout.addLayout(actions_frame)

        # Barra de progreso
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        main_layout.addWidget(self.progress_bar)

        # Tabla resultados
        self.table_resultados = QTableWidget()
        self.table_resultados.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.table_resultados.setSelectionMode(QAbstractItemView.SingleSelection)
        main_layout.addWidget(self.table_resultados)

        # Footer con metadata
        footer = QLabel(f"{DEVELOPER} — {CONTACT}")
        footer.setAlignment(Qt.AlignRight)
        main_layout.addWidget(footer)

        self.apply_styles()

    def apply_styles(self):
        if self.theme_checkbox.isChecked():
            # modo oscuro
            style = """
            QWidget { background: #2b2b2b; color: #e6e6e6; font-family: Arial; }
            QPushButton { background: #3c6e71; color: white; border-radius:6px; padding:6px; }
            QLineEdit, QComboBox { background: #1f1f1f; color: #e6e6e6; padding:6px; border-radius:4px; }
            QTableWidget { background: #1f1f1f; color: #e6e6e6; }
            QProgressBar { background: #444; color: #e6e6e6; }
            """
        else:
            # modo claro
            style = """
            QWidget { background: #f7f9fb; color: #222; font-family: Arial; }
            QPushButton { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #4c78a8, stop:1 #35608a); color: white; border-radius:6px; padding:6px; }
            QLineEdit, QComboBox { background: white; color: #222; padding:6px; border-radius:4px; }
            QTableWidget { background: white; color: #222; }
            QProgressBar { background: #eee; color: #222; }
            """
        self.setStyleSheet(style)

    # ----------------------------------
    # Funciones de carga
    # ----------------------------------
    def load_shp_a(self):
        path, _ = QFileDialog.getOpenFileName(self, "Seleccionar SHP Año A", self.last_dir_a or "", "Shapefiles (*.shp)")
        if path:
            self.path_shp_a = path
            self.last_dir_a = os.path.dirname(path)
            save_config(self.config)
            self.btn_shp_a.setText(f"✔ {os.path.basename(path)}")
            # intentar detectar año
            m = re.search(r"(19\d{2}|20\d{2})", os.path.basename(path))
            if m:
                self.input_year_a.setText(m.group(0))

    def load_shp_b(self):
        path, _ = QFileDialog.getOpenFileName(self, "Seleccionar SHP Año B", self.last_dir_b or "", "Shapefiles (*.shp)")
        if path:
            self.path_shp_b = path
            self.last_dir_b = os.path.dirname(path)
            save_config(self.config)
            self.btn_shp_b.setText(f"✔ {os.path.basename(path)}")
            m = re.search(r"(19\d{2}|20\d{2})", os.path.basename(path))
            if m:
                self.input_year_b.setText(m.group(0))

    def load_valle(self):
        path, _ = QFileDialog.getOpenFileName(self, "Seleccionar SHP Valle Segmentado", self.last_dir_valle or "", "Shapefiles (*.shp)")
        if path:
            self.path_valle = path
            self.last_dir_valle = os.path.dirname(path)
            save_config(self.config)
            self.btn_valle.setText(f"✔ {os.path.basename(path)}")
            try:
                self.gdf_valle = gpd.read_file(path)
                # popular combo con campos categoricos/strings
                self.combo_tramos.clear()
                self.combo_tramos.addItems([col for col in self.gdf_valle.columns if self.gdf_valle[col].dtype == object or self.gdf_valle[col].dtype.name == 'category'])
            except Exception as e:
                QMessageBox.warning(self, "Advertencia", f"No se pudo leer SHP Valle: {e}")

    # ----------------------------------
    # Detectar nombre del rio desde nombres de archivos
    # ----------------------------------
    def detect_nombre_rio(self):
        candidates = []
        for p in (self.path_shp_a, self.path_shp_b):
            if p:
                name = os.path.splitext(os.path.basename(p))[0]
                # eliminar años y caracteres especiales
                name_clean = re.sub(r"(19\d{2}|20\d{2})", "", name)
                name_clean = re.sub(r"[^A-Za-z0-9_ ]", " ", name_clean)
                tokens = [t for t in re.split(r"[_\- ]+", name_clean) if t]
                # elegir token distinto de 'rio' o 'rio'
                token = " ".join([t for t in tokens if t.lower() not in ('rio', 'river')])
                if token:
                    candidates.append(token)
        if candidates:
            # preferir el candidato más largo
            candidate = sorted(candidates, key=lambda s: len(s), reverse=True)[0]
            # limpiar espacios repetidos
            candidate = re.sub(r"\s+", " ", candidate).strip()
            self.input_rio.setText(candidate)
            QMessageBox.information(self, "Nombre detectado", f"Nombre detectado: {candidate}")
        else:
            QMessageBox.information(self, "Nombre no detectado", "No se pudo detectar un nombre de río desde los nombres de archivo. Ingrésalo manualmente.")

    # ----------------------------------
    # Iniciar procesamiento (preparar carpeta y hilo)
    # ----------------------------------
    def start_processing(self):
        try:
            year_a = int(self.input_year_a.text())
            year_b = int(self.input_year_b.text())
            nombre_rio = self.input_rio.text().strip()
            campo_tramos = self.combo_tramos.currentText()

            if not (self.path_shp_a and self.path_shp_b and self.path_valle and nombre_rio and campo_tramos):
                QMessageBox.warning(self, "Error", "Complete todos los campos y seleccione todos los archivos antes de procesar.")
                return
            if year_a >= year_b:
                QMessageBox.warning(self, "Error", "El año A debe ser menor que el año B.")
                return

            usar_carpeta = self.chk_use_folder.isChecked()
            carpeta_salida = ""
            if usar_carpeta:
                base_dir = QFileDialog.getExistingDirectory(self, "Selecciona carpeta donde crear la nueva carpeta", self.last_dir_save or "")
                if not base_dir:
                    return
                carpeta_salida = os.path.join(base_dir, f"RIVER_ACTIVITY_{year_a}_{year_b}")
                os.makedirs(carpeta_salida, exist_ok=True)
                self.last_dir_save = carpeta_salida
                self.config['last_dir_save'] = carpeta_salida
                save_config(self.config)

            # deshabilitar botones mientras procesa
            self.btn_procesar.setEnabled(False)
            self.btn_reset.setEnabled(False)

            # iniciar hilo de procesamiento
            self.thread = ProcessingThread(self.path_shp_a, self.path_shp_b, self.path_valle,
                                           year_a, year_b, nombre_rio, campo_tramos, usar_carpeta, carpeta_salida)
            self.thread.progress.connect(self.on_progress)
            self.thread.finished.connect(self.on_finished)
            self.progress_bar.setValue(0)
            self.thread.start()

        except ValueError:
            QMessageBox.warning(self, "Error", "Por favor ingresa años válidos (enteros).")
        except Exception as e:
            QMessageBox.critical(self, "Error inesperado", str(e))

    def on_progress(self, pct, msg):
        self.progress_bar.setValue(pct)
        self.progress_bar.setFormat(msg + " (%p%)")

    def on_finished(self, resumen, carpeta_salida):
        self.btn_procesar.setEnabled(True)
        self.btn_reset.setEnabled(True)
        if isinstance(carpeta_salida, str) and carpeta_salida.startswith("ERROR:"):
            QMessageBox.critical(self, "Error", carpeta_salida)
            return

        # poblar la tabla
        self.table_resultados.setRowCount(len(resumen))
        self.table_resultados.setColumnCount(4)
        self.table_resultados.setHorizontalHeaderLabels(["TRAMO", "INTERSECCION", "EROSION", "DEPOSICION"])
        for i, (tramo, datos) in enumerate(resumen.items()):
            self.table_resultados.setItem(i, 0, QTableWidgetItem(str(tramo)))
            self.table_resultados.setItem(i, 1, QTableWidgetItem(str(round(datos['INTERSECCION'], 3))))
            self.table_resultados.setItem(i, 2, QTableWidgetItem(str(round(datos['EROSION'], 3))))
            self.table_resultados.setItem(i, 3, QTableWidgetItem(str(round(datos['DEPOSICION'], 3))))

        # guardar excel si se ha usado carpeta
        if carpeta_salida:
            try:
                df = pd.DataFrame([
                    {"TRAMO": t, "INTERSECCION": v['INTERSECCION'], "EROSION": v['EROSION'], "DEPOSICION": v['DEPOSICION']}
                    for t, v in resumen.items()
                ])
                excel_path = os.path.join(carpeta_salida, f"RESUMEN_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx")
                df.to_excel(excel_path, index=False)
                QMessageBox.information(self, "Completado", f"Procesamiento completado. Archivos guardados en:\n{carpeta_salida}")
            except Exception as e:
                QMessageBox.warning(self, "Advertencia", f"No se pudo guardar Excel: {e}")
        else:
            QMessageBox.information(self, "Completado", "Procesamiento completado.")

    def resetear_formulario(self):
        self.path_shp_a = ""
        self.path_shp_b = ""
        self.path_valle = ""
        self.gdf_valle = None
        self.btn_shp_a.setText("Seleccionar SHP Año A")
        self.btn_shp_b.setText("Seleccionar SHP Año B")
        self.btn_valle.setText("Seleccionar SHP Valle Segmentado")
        self.input_year_a.clear()
        self.input_year_b.clear()
        self.input_rio.clear()
        self.combo_tramos.clear()
        self.table_resultados.setRowCount(0)
        self.progress_bar.setValue(0)

    def toggle_theme(self, state=None):
        self.apply_styles()
        self.config['theme'] = 'dark' if self.theme_checkbox.isChecked() else 'light'
        save_config(self.config)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    ventana = RiverActivityApp()
    ventana.show()
    sys.exit(app.exec_())
