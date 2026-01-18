# fusionador_app.py
import sys
import os
os.environ['GDAL_DATA'] = r"C:\Users\ASUS\.conda\envs\TESIS\Library\share\gdal"
import re
from PyQt5.QtWidgets import (
    QApplication, QWidget, QPushButton, QVBoxLayout, QFileDialog,
    QLabel, QTextEdit, QMessageBox, QInputDialog, QLineEdit, QHBoxLayout
)
from PyQt5.QtCore import Qt

YEAR_RE = re.compile(r"(19\d{2}|20\d{2})")


class RasterVectorFusionApp(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Procesador de Ríos - Vectorización y Fusión")
        self.setGeometry(200, 200, 820, 520)

        layout = QVBoxLayout()

        title = QLabel("<b>Procesador de Rasters → Vectores → Fusión por año</b>")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        # botones
        btn_layout = QHBoxLayout()
        self.btn_vectorizar = QPushButton("1. Vectorizar y agrupar por año")
        self.btn_fusionar = QPushButton("2. Fusionar vectores por año")
        btn_layout.addWidget(self.btn_vectorizar)
        btn_layout.addWidget(self.btn_fusionar)
        layout.addLayout(btn_layout)

        # entrada nombre del río (solo se usa en fusión si quieres)
        name_layout = QHBoxLayout()
        name_layout.addWidget(QLabel("Nombre del río (para fusión):"))
        self.input_river = QLineEdit()
        name_layout.addWidget(self.input_river)
        layout.addLayout(name_layout)

        # log
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        layout.addWidget(self.log)

        self.setLayout(layout)

        # conexiones
        self.btn_vectorizar.clicked.connect(self.vectorizar_por_ano)
        self.btn_fusionar.clicked.connect(self.fusionar_por_ano)

    def log_append(self, msg):
        self.log.append(msg)
        QApplication.processEvents()

    # ---------------------------
    # PARTE 1: Vectorizar y agrupar por año
    # ---------------------------
    def vectorizar_por_ano(self):
        # imports locales (evitan cargar GDAL/Fiona en el arranque)
        try:
            import rasterio
            from rasterio.features import shapes
            import geopandas as gpd
            from shapely.geometry import shape
        except Exception as e:
            QMessageBox.critical(self, "Error importación",
                                 f"No se pudieron importar librerías necesarias:\n{e}")
            return

        files, _ = QFileDialog.getOpenFileNames(self, "Seleccione DEMs (varios)", "", "Archivos raster (*.tif *.tiff *.img)")
        if not files:
            return

        salida_base = QFileDialog.getExistingDirectory(self, "Seleccione carpeta de salida (se crearán subcarpetas por año)")
        if not salida_base:
            return

        self.log_append(f"▶ Iniciando vectorización de {len(files)} archivos...")
        for idx, file in enumerate(files, start=1):
            base = os.path.basename(file)
            m = YEAR_RE.search(base)
            if not m:
                self.log_append(f"  ⚠ {base}: no se encontró año en el nombre → omitido")
                continue
            year = m.group(0)
            carpeta_anio = os.path.join(salida_base, year)
            os.makedirs(carpeta_anio, exist_ok=True)

            try:
                with rasterio.open(file) as src:
                    arr = src.read(1)
                    mask = arr == 1
                    results = (
                        {"properties": {"value": int(v)}, "geometry": s}
                        for s, v in shapes(arr, mask=mask, transform=src.transform)
                    )

                    geoms = [shape(feat["geometry"]) for feat in results if int(feat["properties"]["value"]) == 1]

                    if not geoms:
                        self.log_append(f"  [{idx}] {base}: sin geometrías (no se detectó valor 1).")
                        continue

                    gdf = gpd.GeoDataFrame(geometry=geoms, crs=src.crs)

                    # reproyectar a UTM detectado (estimate_utm_crs)
                    try:
                        utm = gdf.estimate_utm_crs()
                        gdf = gdf.to_crs(utm)
                    except Exception as e:
                        self.log_append(f"  [{idx}] {base}: advertencia reproyección UTM: {e} (se guardará en CRS original).")

                    nombre_salida = f"VECT_{os.path.splitext(base)[0]}.shp"
                    ruta_salida = os.path.join(carpeta_anio, nombre_salida)

                    # eliminar previos si existen
                    base_noext = os.path.splitext(ruta_salida)[0]
                    for ext in [".shp", ".shx", ".dbf", ".prj", ".cpg"]:
                        p = base_noext + ext
                        if os.path.exists(p):
                            try:
                                os.remove(p)
                            except Exception:
                                pass

                    gdf.to_file(ruta_salida)
                    self.log_append(f"  [{idx}] {base} → Guardado: {ruta_salida} (geoms: {len(gdf)})")

            except Exception as e:
                self.log_append(f"  ❌ Error procesando {base}: {e}")

        self.log_append("✅ Vectorización finalizada.")

    # ---------------------------
    # PARTE 2: Fusionar vectores por año (cada carpeta -> un shapefile NOMBRE_RIO_AÑO.shp)
    # ---------------------------
    def fusionar_por_ano(self):
        # imports locales
        try:
            import geopandas as gpd
            from shapely.ops import unary_union
        except Exception as e:
            QMessageBox.critical(self, "Error importación",
                                 f"No se pudieron importar librerías necesarias:\n{e}")
            return

        # pedir nombre del río (si no lo dan, lo pedimos)
        river_name = self.input_river.text().strip()
        if not river_name:
            river_name, ok = QInputDialog.getText(self, "Nombre del río", "Ingrese el nombre del río (para los archivos resultantes):")
            if not ok or not river_name.strip():
                QMessageBox.warning(self, "Cancelado", "Operación cancelada (falta nombre del río).")
                return
            river_name = river_name.strip()

        carpeta_base = QFileDialog.getExistingDirectory(self, "Seleccione la carpeta base donde están las carpetas por año")
        if not carpeta_base:
            return

        salida_base = QFileDialog.getExistingDirectory(self, "Seleccione carpeta de salida para los shapefiles fusionados")
        if not salida_base:
            return

        self.log_append(f"▶ Iniciando fusión por año en: {carpeta_base}")
        # recorrer subcarpetas en carpeta_base
        entries = sorted(os.listdir(carpeta_base))
        for entry in entries:
            folder = os.path.join(carpeta_base, entry)
            if not os.path.isdir(folder):
                continue

            # obtener shapefiles en la carpeta
            shp_files = [os.path.join(folder, f) for f in os.listdir(folder) if f.lower().endswith(".shp")]
            if not shp_files:
                self.log_append(f"  - {entry}: sin shapefiles → omitido")
                continue

            self.log_append(f"  - {entry}: {len(shp_files)} shapefiles encontrados. → leyendo y uniendo...")

            geoms = []
            target_crs = None
            # leer uno por uno y extraer geometrías (liberando memoria)
            for shp in shp_files:
                try:
                    gdf = gpd.read_file(shp)
                    if gdf.empty:
                        self.log_append(f"    • {os.path.basename(shp)}: vacío → omitido")
                        continue

                    # establecer target_crs con el primero leído
                    if target_crs is None:
                        target_crs = gdf.crs

                    # reproyectar al CRS objetivo si difiere
                    if gdf.crs != target_crs:
                        try:
                            gdf = gdf.to_crs(target_crs)
                        except Exception as e:
                            self.log_append(f"    • {os.path.basename(shp)}: fallo reproyección a target_crs: {e} → se omitirá este shapefile")
                            continue

                    # añadir geometrías válidas
                    for geom in gdf.geometry:
                        if geom is None or geom.is_empty:
                            continue
                        geoms.append(geom)

                    # liberar
                    del gdf

                except Exception as e:
                    self.log_append(f"    ❌ Error leyendo {os.path.basename(shp)}: {e}")
                    continue

            if not geoms:
                self.log_append(f"    ⚠ No se encontraron geometrías válidas en {entry} → omitiendo.")
                continue

            # realizar la unión topológica (unary_union)
            try:
                unioned = unary_union(geoms)
                if unioned.is_empty:
                    self.log_append(f"    ⚠ Unión vacía para {entry}, se omite.")
                    continue

                # normalizar a lista de polígonos/multipolígonos
                parts = []
                if unioned.geom_type == "Polygon":
                    parts = [unioned]
                elif unioned.geom_type == "MultiPolygon":
                    parts = list(unioned.geoms)
                else:
                    # GeometryCollection u otros -> extraer polígonos
                    for g in getattr(unioned, "geoms", [unioned]):
                        if g.geom_type in ("Polygon", "MultiPolygon"):
                            if g.geom_type == "Polygon":
                                parts.append(g)
                            else:
                                parts.extend(list(g.geoms))

                if not parts:
                    self.log_append(f"    ⚠ Después de procesar, no hay polígonos en {entry}.")
                    continue

                # crear GeoDataFrame de salida
                out_gdf = gpd.GeoDataFrame({
                    "river": [river_name] * len(parts),
                    "year": [entry] * len(parts),
                    "geometry": parts
                }, crs=target_crs)

                # nombre y guardado
                out_name = f"{river_name}_{entry}.shp"
                out_path = os.path.join(salida_base, out_name)

                # eliminar previos si existen
                base_noext = os.path.splitext(out_path)[0]
                for ext in [".shp", ".shx", ".dbf", ".prj", ".cpg"]:
                    p = base_noext + ext
                    if os.path.exists(p):
                        try:
                            os.remove(p)
                        except Exception:
                            pass

                out_gdf.to_file(out_path)
                self.log_append(f"    ✅ Guardado fusionado: {out_path} (partes: {len(parts)})")

            except Exception as e:
                self.log_append(f"    ❌ Error uniendo geometrías en {entry}: {e}")
                continue

        self.log_append("✅ Fusión por año completada.")
        QMessageBox.information(self, "Proceso terminado", "Fusión por año finalizada. Revisa el log para detalles.")

# ejecutar
if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = RasterVectorFusionApp()
    win.show()
    sys.exit(app.exec_())
