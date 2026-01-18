import sys
import os
import glob
import re
import shutil
import numpy as np
import pandas as pd
import geopandas as gpd
import rasterio
from rasterio import features
from rasterio.transform import from_origin
import matplotlib.pyplot as plt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
from matplotlib.figure import Figure

from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QLabel, QLineEdit, QPushButton, QComboBox, QFileDialog,
                             QProgressBar, QTextEdit, QTabWidget, QGroupBox, QRadioButton,
                             QSpinBox, QMessageBox, QSplitter, QFrame, QCheckBox)
from PyQt5.QtCore import Qt, QThread, pyqtSignal


# =============================================================================
# LÓGICA AUXILIAR Y CIENTÍFICA
# =============================================================================

def natural_sort_key(text):
    """Permite ordenar MD_1, MD_2, MD_10 correctamente."""
    return [int(c) if c.isdigit() else c.lower() for c in re.split(r'(\d+)', str(text))]


def calcular_ebi_matriz(mascara):
    """Calcula eBI de una matriz binaria (Segmento rasterizado)."""
    # Barrido en ambos ejes para robustez
    ebis = []
    for eje in [0, 1]:
        mat = mascara if eje == 0 else mascara.T
        for i in range(mat.shape[1]):
            col = mat[:, i]
            if np.sum(col) == 0: continue

            # Detectar tramos continuos de agua
            padded = np.pad(col, (1, 1), 'constant')
            diff = np.diff(padded)
            starts = np.where(diff == 1)[0]
            ends = np.where(diff == -1)[0]
            anchos = ends - starts

            # Fórmula eBI
            W_tot = np.sum(anchos)
            if W_tot == 0: continue
            probs = anchos / W_tot
            H = -np.sum(probs * np.log2(probs))
            ebis.append(2 ** H)

    if len(ebis) == 0: return 0.0
    return np.mean(ebis)


# =============================================================================
# HILO DE PROCESAMIENTO (WORKER)
# =============================================================================
class ProcessingThread(QThread):
    progress_signal = pyqtSignal(int)
    log_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(str, pd.DataFrame)  # Ruta carpeta, DataFrame Resultados
    error_signal = pyqtSignal(str)

    def __init__(self, ruta_segmentos, col_id, carpeta_rios, dir_salida, nombre_rio):
        super().__init__()
        self.ruta_seg = ruta_segmentos
        self.col_id = col_id
        self.carpeta_rios = carpeta_rios
        self.dir_salida = dir_salida
        self.nombre_rio = nombre_rio

    def run(self):
        try:
            self.log_signal.emit(">>> INICIANDO PROCESO CIENTÍFICO")

            # 1. Crear Estructura de Carpetas
            nombre_carpeta_madre = f"EBI_{self.nombre_rio}"
            path_madre = os.path.join(self.dir_salida, nombre_carpeta_madre)
            if not os.path.exists(path_madre): os.makedirs(path_madre)

            path_plots = os.path.join(path_madre, "PLOTS")
            if not os.path.exists(path_plots): os.makedirs(path_plots)

            # 2. Cargar Segmentos (Valle)
            self.log_signal.emit(f"Cargando segmentos: {os.path.basename(self.ruta_seg)}")
            gdf_seg = gpd.read_file(self.ruta_seg)

            # Asegurar ordenamiento natural de los segmentos
            gdf_seg['sort_key'] = gdf_seg[self.col_id].apply(natural_sort_key)
            gdf_seg = gdf_seg.sort_values('sort_key').drop(columns=['sort_key']).reset_index(drop=True)

            # DataFrame Maestro para resultados (Filas=Segmentos)
            df_master = pd.DataFrame({self.col_id: gdf_seg[self.col_id]})

            # 3. Buscar Ríos y Ordenar por Año
            archivos_rios = glob.glob(os.path.join(self.carpeta_rios, "*.shp"))
            rios_info = []
            for r in archivos_rios:
                match = re.search(r"(\d{4})", os.path.basename(r))
                if match:
                    rios_info.append((int(match.group(1)), r))

            rios_info.sort()  # Ordenar cronológicamente (1986, 1990...)

            total_pasos = len(rios_info) * len(gdf_seg)
            paso_actual = 0

            # 4. Bucle Principal
            for year, ruta_rio in rios_info:
                self.log_signal.emit(f"--> Analizando Año {year}...")
                gdf_rio = gpd.read_file(ruta_rio)

                # Asegurar proyecciones iguales
                if gdf_rio.crs != gdf_seg.crs:
                    gdf_rio = gdf_rio.to_crs(gdf_seg.crs)

                col_name = f"eBI_{year}"
                ebis_anio = []

                for idx, row in gdf_seg.iterrows():
                    geom_seg = row.geometry

                    # Clip (Intersección)
                    try:
                        clip_rio = gpd.clip(gdf_rio, geom_seg)
                    except:
                        clip_rio = gpd.GeoDataFrame(geometry=[])

                    if clip_rio.is_empty.all():
                        ebis_anio.append(0.0)
                    else:
                        # Rasterización Local
                        bounds = geom_seg.bounds
                        pixel_size = 30  # Metros
                        w = int((bounds[2] - bounds[0]) / pixel_size)
                        h = int((bounds[3] - bounds[1]) / pixel_size)

                        if w <= 0 or h <= 0:
                            ebis_anio.append(0.0)
                        else:
                            transform = from_origin(bounds[0], bounds[3], pixel_size, pixel_size)
                            shapes = ((g, 1) for g in clip_rio.geometry)
                            try:
                                img = features.rasterize(shapes=shapes, out_shape=(h, w), transform=transform)
                                val_ebi = calcular_ebi_matriz(img)
                                ebis_anio.append(val_ebi)
                            except Exception as e:
                                ebis_anio.append(0.0)

                    paso_actual += 1
                    progreso = int((paso_actual / total_pasos) * 100)
                    self.progress_signal.emit(progreso)

                # Agregar columna al maestro
                df_master[col_name] = ebis_anio

            # 5. Exportar CSV Maestro
            path_csv = os.path.join(path_madre, f"{self.nombre_rio}_Matriz_eBI.csv")
            # Usar punto y coma para Excel español
            df_master.to_csv(path_csv, sep=';', decimal=',', index=False)
            self.log_signal.emit(f"CSV guardado: {path_csv}")

            # 6. Exportar SHP Limpio (Solo ID + eBI)
            # Copia limpia solo con geometría e ID
            gdf_clean = gdf_seg[[self.col_id, 'geometry']].copy()
            # Unir con los datos calculados
            gdf_final = gdf_clean.merge(df_master, on=self.col_id)

            path_shp = os.path.join(path_madre, f"{self.nombre_rio}_Spatial_eBI.shp")
            gdf_final.to_file(path_shp)
            self.log_signal.emit(f"Shapefile limpio guardado: {path_shp}")

            self.finished_signal.emit(path_madre, df_master)

        except Exception as e:
            self.error_signal.emit(str(e))


# =============================================================================
# INTERFAZ GRÁFICA (GUI)
# =============================================================================
class EBICalculatorApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("eBI MorphoDynamics Pro - Scientific Analysis")
        self.setGeometry(100, 100, 1200, 800)
        self.df_resultados = None  # Aquí guardaremos la data en memoria
        self.ruta_resultados = ""
        self.initUI()

    def initUI(self):
        # Widget Central y Tabs
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout_main = QVBoxLayout(central_widget)

        self.tabs = QTabWidget()
        self.tab_process = QWidget()
        self.tab_analysis = QWidget()

        self.tabs.addTab(self.tab_process, "1. Procesamiento")
        self.tabs.addTab(self.tab_analysis, "2. Análisis y Gráficos")
        self.tabs.setTabEnabled(1, False)  # Bloquear tab 2 hasta procesar

        layout_main.addWidget(self.tabs)

        self.setup_tab_process()
        self.setup_tab_analysis()

    # --- PESTAÑA 1: PROCESAMIENTO ---
    def setup_tab_process(self):
        layout = QVBoxLayout()

        # Grupo 1: Inputs
        grp_in = QGroupBox("Datos de Entrada")
        ly_in = QVBoxLayout()

        # Segmentos
        h1 = QHBoxLayout()
        self.txt_seg = QLineEdit()
        self.txt_seg.setPlaceholderText("Seleccionar Shapefile del Valle Sectorizado (.shp)")
        btn_seg = QPushButton("Cargar SHP Valle")
        btn_seg.clicked.connect(self.load_segment_shp)
        h1.addWidget(self.txt_seg)
        h1.addWidget(btn_seg)

        # Selector de Columna ID
        h1_b = QHBoxLayout()
        h1_b.addWidget(QLabel("Columna ID Segmentos:"))
        self.cb_col_id = QComboBox()
        h1_b.addWidget(self.cb_col_id)

        # Carpeta Ríos
        h2 = QHBoxLayout()
        self.txt_rios = QLineEdit()
        self.txt_rios.setPlaceholderText("Carpeta con Shapefiles de Ríos (Año_XXXX.shp)")
        btn_rios = QPushButton("Cargar Carpeta Ríos")
        btn_rios.clicked.connect(self.load_river_folder)
        h2.addWidget(self.txt_rios)
        h2.addWidget(btn_rios)

        ly_in.addLayout(h1)
        ly_in.addLayout(h1_b)
        ly_in.addLayout(h2)
        grp_in.setLayout(ly_in)

        # Grupo 2: Configuración
        grp_conf = QGroupBox("Configuración de Salida")
        ly_conf = QVBoxLayout()

        h3 = QHBoxLayout()
        h3.addWidget(QLabel("Nombre del Río (Proyecto):"))
        self.txt_nombre = QLineEdit()
        h3.addWidget(self.txt_nombre)

        h4 = QHBoxLayout()
        self.txt_out = QLineEdit()
        self.txt_out.setPlaceholderText("Carpeta donde guardar resultados")
        btn_out = QPushButton("Seleccionar Salida")
        btn_out.clicked.connect(self.select_output_dir)
        h4.addWidget(self.txt_out)
        h4.addWidget(btn_out)

        ly_conf.addLayout(h3)
        ly_conf.addLayout(h4)
        grp_conf.setLayout(ly_conf)

        # Ejecución
        self.progress = QProgressBar()
        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)

        btn_run = QPushButton("INICIAR CÁLCULO CIENTÍFICO")
        btn_run.setStyleSheet(
            "font-weight: bold; font-size: 14px; padding: 10px; background-color: #2ecc71; color: white;")
        btn_run.clicked.connect(self.run_process)

        btn_reset = QPushButton("LIMPIAR / NUEVO PROYECTO")
        btn_reset.setStyleSheet("background-color: #e74c3c; color: white;")
        btn_reset.clicked.connect(self.reset_app)

        layout.addWidget(grp_in)
        layout.addWidget(grp_conf)
        layout.addWidget(btn_run)
        layout.addWidget(self.progress)
        layout.addWidget(self.log_box)
        layout.addWidget(btn_reset)

        self.tab_process.setLayout(layout)

    # --- PESTAÑA 2: ANÁLISIS ---
    def setup_tab_analysis(self):
        layout = QHBoxLayout()

        # PANEL IZQUIERDO (Controles)
        panel_left = QFrame()
        panel_left.setFrameShape(QFrame.StyledPanel)
        panel_left.setFixedWidth(350)
        ly_left = QVBoxLayout(panel_left)

        ly_left.addWidget(QLabel("<b>CONTROLES DE VISUALIZACIÓN</b>"))

        # Modos
        self.rb_seg = QRadioButton("Ver por Segmento (Evolución Temporal)")
        self.rb_spatial = QRadioButton("Ver Espacial (Todo el Valle)")
        self.rb_seg.setChecked(True)
        self.rb_seg.toggled.connect(self.update_plot_controls)
        self.rb_spatial.toggled.connect(self.update_plot_controls)

        ly_left.addWidget(self.rb_seg)
        ly_left.addWidget(self.rb_spatial)

        # Stack 1: Controles Segmento
        self.grp_seg_ctrl = QGroupBox("Opciones de Segmento")
        ly_seg = QVBoxLayout()
        self.cb_segments = QComboBox()
        self.cb_segments.currentIndexChanged.connect(self.update_plot)
        btn_exp_seg = QPushButton("Exportar Gráfico Actual")
        btn_exp_seg.clicked.connect(lambda: self.export_plot(batch=False))
        btn_exp_batch_seg = QPushButton("Exportar TODOS los Segmentos (Lote)")
        btn_exp_batch_seg.clicked.connect(lambda: self.export_plot(batch=True))

        ly_seg.addWidget(QLabel("Seleccionar Segmento:"))
        ly_seg.addWidget(self.cb_segments)
        ly_seg.addWidget(btn_exp_seg)
        ly_seg.addWidget(btn_exp_batch_seg)
        self.grp_seg_ctrl.setLayout(ly_seg)

        # Stack 2: Controles Espaciales
        self.grp_spa_ctrl = QGroupBox("Opciones Espaciales")
        ly_spa = QVBoxLayout()

        # Sub-opciones
        self.rb_year_single = QRadioButton("Ver Un Año")
        self.rb_year_all = QRadioButton("Ver Todos los Años")
        self.rb_year_single.setChecked(True)
        self.rb_year_single.toggled.connect(self.update_plot)
        self.rb_year_all.toggled.connect(self.update_plot)

        self.cb_years = QComboBox()
        self.cb_years.currentIndexChanged.connect(self.update_plot)

        # Step X Axis
        h_step = QHBoxLayout()
        h_step.addWidget(QLabel("Etiquetas Eje X cada:"))
        self.spin_step = QSpinBox()
        self.spin_step.setRange(1, 100)
        self.spin_step.setValue(1)  # Default 1 en 1
        self.spin_step.valueChanged.connect(self.update_plot)
        h_step.addWidget(self.spin_step)

        btn_exp_spa = QPushButton("Exportar Gráfico Actual")
        btn_exp_spa.clicked.connect(lambda: self.export_plot(batch=False))
        btn_exp_batch_spa = QPushButton("Exportar TODOS los Años (Lote)")
        btn_exp_batch_spa.clicked.connect(lambda: self.export_plot(batch=True))

        ly_spa.addWidget(self.rb_year_single)
        ly_spa.addWidget(self.cb_years)
        ly_spa.addWidget(self.rb_year_all)
        ly_spa.addLayout(h_step)
        ly_spa.addWidget(btn_exp_spa)
        ly_spa.addWidget(btn_exp_batch_spa)
        self.grp_spa_ctrl.setLayout(ly_spa)
        self.grp_spa_ctrl.setVisible(False)

        ly_left.addWidget(self.grp_seg_ctrl)
        ly_left.addWidget(self.grp_spa_ctrl)
        ly_left.addStretch()

        # PANEL DERECHO (Matplotlib)
        self.figure = Figure()
        self.canvas = FigureCanvas(self.figure)
        self.toolbar = NavigationToolbar(self.canvas, self)

        layout_right = QVBoxLayout()
        layout_right.addWidget(self.toolbar)
        layout_right.addWidget(self.canvas)

        layout.addWidget(panel_left)
        layout.addLayout(layout_right)
        self.tab_analysis.setLayout(layout)

    # --- FUNCIONES DE CARGA ---
    def load_segment_shp(self):
        f, _ = QFileDialog.getOpenFileName(self, "Seleccionar SHP Valle", "", "Shapefile (*.shp)")
        if f:
            self.txt_seg.setText(f)
            # Leer columnas para el combo
            try:
                gdf = gpd.read_file(f, rows=1)
                self.cb_col_id.clear()
                self.cb_col_id.addItems(gdf.columns.tolist())
                # Intentar seleccionar 'segments' por defecto
                idx = self.cb_col_id.findText("segments", Qt.MatchContains)
                if idx >= 0: self.cb_col_id.setCurrentIndex(idx)
            except Exception as e:
                self.log_box.append(f"Error leyendo SHP: {e}")

    def load_river_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Seleccionar Carpeta Ríos")
        if d:
            self.txt_rios.setText(d)
            # Intentar adivinar nombre
            files = glob.glob(os.path.join(d, "*.shp"))
            if files:
                base = os.path.basename(files[0])
                # Regex para quitar el año y _
                guess = re.sub(r'[_]?\d{4}.shp', '', base)
                self.txt_nombre.setText(guess)

    def select_output_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Seleccionar Carpeta Salida")
        if d: self.txt_out.setText(d)

    # --- LÓGICA DE PROCESAMIENTO ---
    def run_process(self):
        # Validaciones
        seg = self.txt_seg.text()
        rios = self.txt_rios.text()
        out = self.txt_out.text()
        col = self.cb_col_id.currentText()
        name = self.txt_nombre.text()

        if not all([seg, rios, out, col, name]):
            QMessageBox.warning(self, "Faltan Datos", "Por favor completa todos los campos.")
            return

        self.thread = ProcessingThread(seg, col, rios, out, name)
        self.thread.progress_signal.connect(self.progress.setValue)
        self.thread.log_signal.connect(self.log_box.append)
        self.thread.error_signal.connect(lambda e: QMessageBox.critical(self, "Error", e))
        self.thread.finished_signal.connect(self.on_process_finished)

        self.log_box.clear()
        self.tabs.setCurrentIndex(0)
        self.thread.start()

    def on_process_finished(self, path_res, df):
        self.log_box.append(">>> PROCESO FINALIZADO CON ÉXITO")
        self.ruta_resultados = path_res
        self.df_resultados = df

        # Habilitar Tab 2
        self.tabs.setTabEnabled(1, True)
        self.populate_analysis_controls()
        self.tabs.setCurrentIndex(1)
        QMessageBox.information(self, "Éxito", f"Resultados guardados en:\n{path_res}")

    def reset_app(self):
        self.txt_seg.clear()
        self.txt_rios.clear()
        self.txt_out.clear()
        self.txt_nombre.clear()
        self.cb_col_id.clear()
        self.log_box.clear()
        self.progress.setValue(0)
        self.tabs.setTabEnabled(1, False)
        self.tabs.setCurrentIndex(0)
        self.figure.clear()
        self.canvas.draw()

    # --- LÓGICA DE ANÁLISIS ---
    def populate_analysis_controls(self):
        if self.df_resultados is None: return

        # Llenar segmentos (Col 0)
        col_seg = self.df_resultados.columns[0]
        segments = self.df_resultados[col_seg].astype(str).tolist()
        self.cb_segments.blockSignals(True)
        self.cb_segments.clear()
        self.cb_segments.addItems(segments)
        self.cb_segments.blockSignals(False)

        # Llenar años (Columnas eBI_XXXX)
        cols = self.df_resultados.columns
        years = [c.replace("eBI_", "") for c in cols if "eBI_" in c]
        self.cb_years.blockSignals(True)
        self.cb_years.clear()
        self.cb_years.addItems(years)
        self.cb_years.blockSignals(False)

        self.update_plot()

    def update_plot_controls(self):
        if self.rb_seg.isChecked():
            self.grp_seg_ctrl.setVisible(True)
            self.grp_spa_ctrl.setVisible(False)
        else:
            self.grp_seg_ctrl.setVisible(False)
            self.grp_spa_ctrl.setVisible(True)
        self.update_plot()

    def update_plot(self):
        if self.df_resultados is None: return

        self.figure.clear()
        ax = self.figure.add_subplot(111)

        col_id_name = self.df_resultados.columns[0]

        # MODO 1: Por Segmento (Evolución Temporal)
        if self.rb_seg.isChecked():
            seg_actual = self.cb_segments.currentText()
            # Filtrar fila
            row = self.df_resultados[self.df_resultados[col_id_name].astype(str) == seg_actual]
            if row.empty: return

            # Extraer datos
            cols_ebi = [c for c in self.df_resultados.columns if "eBI_" in c]
            years = [int(c.replace("eBI_", "")) for c in cols_ebi]
            vals = row[cols_ebi].values.flatten()

            # Graficar
            ax.plot(years, vals, marker='o', linestyle='-', color='royalblue', linewidth=2)
            ax.set_title(f"Evolución Temporal del eBI - Segmento: {seg_actual}")
            ax.set_xlabel("Año")
            ax.set_ylabel("eBI (Índice de Trenzamiento)")
            ax.set_xticks(years)
            ax.grid(True, linestyle='--', alpha=0.6)

        # MODO 2: Espacial (Todo el valle)
        else:
            segments = self.df_resultados[col_id_name].astype(str).tolist()
            x_indices = np.arange(len(segments))
            step = self.spin_step.value()

            # Sub-Modo: Un solo año
            if self.rb_year_single.isChecked():
                year_sel = self.cb_years.currentText()
                col_sel = f"eBI_{year_sel}"
                vals = self.df_resultados[col_sel].values

                ax.plot(x_indices, vals, color='darkgreen', linewidth=1.5)
                ax.set_title(f"Variación Espacial del eBI - Año {year_sel}")

            # Sub-Modo: Todos los años
            else:
                cols_ebi = [c for c in self.df_resultados.columns if "eBI_" in c]
                # Colores (colormap)
                cmap = plt.get_cmap('viridis')
                colors = [cmap(i) for i in np.linspace(0, 1, len(cols_ebi))]

                for idx, col in enumerate(cols_ebi):
                    year = col.replace("eBI_", "")
                    vals = self.df_resultados[col].values
                    ax.plot(x_indices, vals, label=year, color=colors[idx], linewidth=1)

                ax.set_title(f"Variación Espacial Multitemporal ({len(cols_ebi)} Años)")
                ax.legend(bbox_to_anchor=(1.01, 1), loc='upper left', fontsize='small')
                # Ajustar layout para la leyenda
                self.figure.subplots_adjust(right=0.85)

            # Eje X Configurable
            ax.set_xlabel("Segmentos del Valle")
            ax.set_ylabel("eBI")
            ax.set_xticks(x_indices[::step])
            ax.set_xticklabels(segments[::step], rotation=45, ha='right', fontsize=8)
            ax.grid(True, alpha=0.3)

        self.canvas.draw()

    # --- EXPORTACIÓN ---
    def export_plot(self, batch=False):
        path_plots = os.path.join(self.ruta_resultados, "PLOTS")

        # MODO 1: Segmentos
        if self.rb_seg.isChecked():
            if not batch:
                # Exportar uno solo
                seg = self.cb_segments.currentText()
                default_name = f"eBI_Temporal_{seg}.png"
                path, _ = QFileDialog.getSaveFileName(self, "Guardar Gráfico",
                                                      os.path.join(path_plots, default_name),
                                                      "PNG Image (*.png)")
                if path:
                    self.figure.savefig(path, dpi=150)
            else:
                # Batch Segmentos
                folder = QFileDialog.getExistingDirectory(self, "Seleccionar Carpeta Destino", path_plots)
                if folder:
                    count = self.cb_segments.count()
                    for i in range(count):
                        self.cb_segments.setCurrentIndex(i)  # Esto actualiza el plot
                        seg = self.cb_segments.currentText()
                        fname = f"eBI_Temporal_{seg}.png"
                        self.figure.savefig(os.path.join(folder, fname), dpi=100)
                    QMessageBox.information(self, "Batch", f"Se exportaron {count} gráficos.")

        # MODO 2: Espacial
        else:
            if not batch:
                # Uno solo (El que se ve)
                year = self.cb_years.currentText() if self.rb_year_single.isChecked() else "VARIACION_TOTAL"
                default_name = f"eBI_Espacial_{year}.png"
                path, _ = QFileDialog.getSaveFileName(self, "Guardar Gráfico",
                                                      os.path.join(path_plots, default_name),
                                                      "PNG Image (*.png)")
                if path:
                    self.figure.savefig(path, dpi=150)
            else:
                # Batch Años (Solo tiene sentido si estamos en modo Un Año)
                if self.rb_year_all.isChecked():
                    QMessageBox.information(self, "Info",
                                            "En modo 'Todos los Años' solo hay 1 gráfico. Usa exportar individual.")
                    return

                folder = os.path.join(path_plots, "PLOTS_BY_YEAR")
                if not os.path.exists(folder): os.makedirs(folder)

                # Preguntar si guardar ahí
                reply = QMessageBox.question(self, "Batch", f"Se guardarán en:\n{folder}\n¿Continuar?",
                                             QMessageBox.Yes | QMessageBox.No)
                if reply == QMessageBox.Yes:
                    count = self.cb_years.count()
                    for i in range(count):
                        self.cb_years.setCurrentIndex(i)
                        y = self.cb_years.currentText()
                        fname = f"eBI_Espacial_{y}.png"
                        self.figure.savefig(os.path.join(folder, fname), dpi=100)
                    QMessageBox.information(self, "Batch", "Exportación completa.")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = EBICalculatorApp()
    window.show()
    sys.exit(app.exec_())