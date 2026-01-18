import os
import glob
import geopandas as gpd
import rasterio
from rasterio import features
from rasterio.transform import from_origin
import numpy as np

# =============================================================================
# CONFIGURACIÓN (RESPETANDO RESOLUCIÓN NATIVA)
# =============================================================================
INPUT_FOLDER = r"D:\UNHEVAL\TESIS PROCESO\PROCESO RIOS\RIO MADRE DE DIOS\MOR\RIO VECTOR POR AÑO\UNIDO"  # <--- TU CARPETA DE SHAPEFILES
OUTPUT_FOLDER = r"D:\UNHEVAL\TESIS PROCESO\PROCESO RIOS\RIO MADRE DE DIOS\MOR\RIO RASTER POR AÑO"  # <--- CARPETA DE SALIDA
PIXEL_SIZE = 30.0  # <--- 30 METROS (NO MODIFICAR)
PADDING = 100.0  # Margen de seguridad (metros) para que el río no toque el borde


# =============================================================================
# SCRIPT DE CONVERSIÓN
# =============================================================================
def convertir_shp_a_binario_30m():
    if not os.path.exists(OUTPUT_FOLDER):
        os.makedirs(OUTPUT_FOLDER)

    archivos_shp = glob.glob(os.path.join(INPUT_FOLDER, "*.shp"))

    print(f"--- INICIANDO CONVERSIÓN ESTRICTA (30m) ---")
    print(f"Archivos encontrados: {len(archivos_shp)}")

    for i, ruta_shp in enumerate(archivos_shp):
        nombre_archivo = os.path.basename(ruta_shp).replace(".shp", "")
        print(f"[{i + 1}/{len(archivos_shp)}] Procesando: {nombre_archivo}...")

        try:
            # 1. Cargar Vector
            gdf = gpd.read_file(ruta_shp)
            if gdf.empty: continue

            # 2. Calcular Dimensiones (Bounds + Padding)
            minx, miny, maxx, maxy = gdf.total_bounds

            # Ajustar al borde del píxel más cercano para evitar desplazamientos (sub-pixel shifts)
            minx = np.floor(minx / PIXEL_SIZE) * PIXEL_SIZE - PADDING
            maxy = np.ceil(maxy / PIXEL_SIZE) * PIXEL_SIZE + PADDING
            maxx = np.ceil(maxx / PIXEL_SIZE) * PIXEL_SIZE + PADDING
            miny = np.floor(miny / PIXEL_SIZE) * PIXEL_SIZE - PADDING

            width = int((maxx - minx) / PIXEL_SIZE)
            height = int((maxy - miny) / PIXEL_SIZE)

            # 3. Transformación
            transform = from_origin(minx, maxy, PIXEL_SIZE, PIXEL_SIZE)

            # 4. Rasterizar (Quemar geometría)
            # all_touched=True es CRÍTICO en 30m para no romper la continuidad del río
            shapes = ((geom, 1) for geom in gdf.geometry)
            imagen = features.rasterize(
                shapes=shapes,
                out_shape=(height, width),
                transform=transform,
                fill=0,  # 0 = Fondo
                default_value=1,  # 1 = Río
                dtype=rasterio.uint8,
                all_touched=True
            )

            # 5. Guardar TIFF Binario
            ruta_salida = os.path.join(OUTPUT_FOLDER, f"{nombre_archivo}_30m.tif")

            with rasterio.open(
                    ruta_salida, 'w', driver='GTiff',
                    height=height, width=width, count=1,
                    dtype=rasterio.uint8, crs=gdf.crs, transform=transform,
                    compress='lzw'
            ) as dst:
                dst.write(imagen, 1)

        except Exception as e:
            print(f"Error en {nombre_archivo}: {e}")

    print("\n--- PROCESO TERMINADO ---")
    print("Nota: Al ser 30m, los bordes se verán 'pixelados' en ArcScan.")
    print("Asegúrate de usar tu código de suavizado posterior.")


if __name__ == "__main__":
    convertir_shp_a_binario_30m()