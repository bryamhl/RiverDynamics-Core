import os
import sys
import numpy as np
import pandas as pd
import geopandas as gpd
import rasterio
from shapely.geometry import LineString, Point
from rivgraph.classes import river
from scipy.ndimage import binary_closing
from osgeo import gdal
import warnings
import copy

# Configuración
gdal.UseExceptions()
warnings.filterwarnings("ignore")


# =============================================================================
#  FUNCIÓN AUXILIAR: CONVERTIR PÍXELES A GEOMETRÍA REAL
# =============================================================================
def generar_geometria_links(rio_obj):
    """
    Si los links solo tienen índices de píxeles ('idx'), genera la clave 'geom'
    convirtiéndolos a coordenadas reales (Metros/Grados) usando el GeoTransform.
    """
    links = rio_obj.links
    if 'geom' in links: return  # Ya existe, no hacer nada

    print("   > Generando geometrías desde índices de píxeles...")
    gt = rio_obj.gt  # GeoTransform [x_min, pixel_w, rot, y_max, rot, pixel_h]
    shape = rio_obj.Imask.shape

    geoms = []

    for idx_list in links['idx']:
        # 1. Convertir índice lineal a filas y columnas
        rows, cols = np.unravel_index(idx_list, shape)

        # 2. Convertir fila/col a Coordenada X, Y
        # X = origen_x + col * ancho_pixel
        # Y = origen_y + row * alto_pixel
        xs = gt[0] + cols * gt[1]
        ys = gt[3] + rows * gt[5]

        # 3. Crear LineString
        # Necesitamos al menos 2 puntos. Si es 1 punto, lo duplicamos.
        pts = list(zip(xs, ys))
        if len(pts) < 2:
            pts.append(pts[0])

        geoms.append(LineString(pts))

    # Guardar en el diccionario del río
    links['geom'] = geoms


# =============================================================================
#  FUNCIÓN CÁLCULO EBI (PROYECCIÓN VECTORIAL)
# =============================================================================
def calcular_ebi_segmento_vectorial(links_segmento, eje_segmento):
    """
    Calcula eBI proyectando los links recortados sobre el eje recortado.
    """
    if eje_segmento is None or eje_segmento.is_empty: return 1.0

    largo_eje = eje_segmento.length
    if largo_eje == 0: return 1.0

    # Muestreo fino (cada 10m para precisión)
    estaciones = np.arange(0, largo_eje, 10.0)
    anchos_por_estacion = {est: [] for est in estaciones}

    # Iterar sobre los links que cayeron dentro de este segmento
    for link_geom, ancho in links_segmento:
        if ancho <= 0 or np.isnan(ancho): ancho = 30.0

        try:
            # Proyectar sobre el eje local
            # El link puede ser MultiLineString si el recorte lo partió
            geoms = [link_geom] if link_geom.geom_type == 'LineString' else link_geom.geoms

            for g in geoms:
                p1 = eje_segmento.project(Point(g.coords[0]))
                p2 = eje_segmento.project(Point(g.coords[-1]))
                start, end = sorted((p1, p2))

                # Corrección para links verticales/bucles
                if (end - start) < 1.0:
                    mid = (start + end) / 2
                    start, end = mid - 5, mid + 5

                indices = np.where((estaciones >= start) & (estaciones <= end))[0]
                for idx in indices:
                    anchos_por_estacion[estaciones[idx]].append(ancho)
        except:
            continue

    # Shannon
    ebis = []
    for est in estaciones:
        w_list = np.array(anchos_por_estacion[est])
        if len(w_list) == 0:
            ebis.append(1.0)
        else:
            W_tot = np.sum(w_list)
            if W_tot == 0:
                ebis.append(1.0)
            else:
                p = w_list / W_tot
                H = -np.sum(p * np.log2(p + 1e-9))
                ebis.append(2 ** H)

    if len(ebis) == 0: return 1.0
    return np.mean(ebis)


# =============================================================================
#  BLOQUE PRINCIPAL
# =============================================================================
if __name__ == "__main__":
    # --- RUTAS DE ENTRADA ---
    PATH_TIF_RIO = r'D:\UNHEVAL\TESIS PROCESO\PROCESO RIOS\RIO CUPOHUE\MOR\RIOS RASTER POR AÑO\RIO_CUPOHUE_1986_30m.tif'
    PATH_SHP_SECTORES = r'D:\UNHEVAL\TESIS PROCESO\PROCESO RIOS\RIO CUPOHUE\RESULTADOS_eBI\V_RIO_CUPOHUE_S1_ET.shp'
    PATH_SALIDA = r'D:\UNHEVAL\TESIS PROCESO\PROCESO RIOS\RIO CUPOHUE\RESULTADOS_SEGMENTADOS'
    COLUMNA_ID = 'SEGMENTS'

    # Ajusta esto si tu río fluye al revés
    EXIT_SIDES = 'EW'

    if not os.path.exists(PATH_SALIDA): os.makedirs(PATH_SALIDA)

    print("--- INICIANDO ANÁLISIS HÍBRIDO V2 (FIX GEOM) ---")

    # 1. PROCESAMIENTO GLOBAL (UNA SOLA VEZ)
    print("1. Procesando Red Global del Río...")
    # Silenciar salidas verbose
    sys.stdout = open(os.devnull, 'w')
    rio_global = river('Global', PATH_TIF_RIO, PATH_SALIDA, exit_sides=EXIT_SIDES, verbose=False)
    rio_global.Imask = binary_closing(rio_global.Imask, structure=np.ones((3, 3))).astype(int)
    rio_global.skeletonize()
    rio_global.compute_network()
    sys.stdout = sys.__stdout__  # Restaurar consola

    print("   > Red base calculada.")

    # GUARDAR RED COMPLETA (CRUDO)
    raw_links = copy.deepcopy(rio_global.links)

    # CALCULAR EJE MAESTRO
    print("   > Calculando Eje Central Maestro...")
    rio_global.prune_network()
    rio_global.compute_centerline()

    # OBJETO SHAPELY DEL EJE
    cl_x, cl_y = rio_global.centerline
    global_centerline_geom = LineString(zip(cl_x, cl_y))

    # RESTAURAR RED COMPLETA Y REPARAR GEOMETRÍA
    print("   > Restaurando islas y generando geometría...")
    rio_global.links = raw_links

    # ¡AQUÍ ESTÁ LA CORRECCIÓN! Generamos 'geom' manualmente si falta
    generar_geometria_links(rio_global)

    # Calcular anchos sobre la red completa
    rio_global.compute_link_width_and_length()

    # Preparar lista de tuplas (Geometria, Ancho) para intersección rápida
    global_links_geoms = []
    for i in range(len(rio_global.links['id'])):
        try:
            # Ahora 'geom' seguro existe gracias a nuestra función
            coords = rio_global.links['geom'][i]
            ancho = rio_global.links['wid_adj'][i]
            if np.isnan(ancho): ancho = 30.0

            # coords puede ser lista de puntos o LineString directo, aseguramos LineString
            if isinstance(coords, LineString):
                l_geom = coords
            else:
                l_geom = LineString(coords)

            global_links_geoms.append((l_geom, ancho))
        except Exception as e:
            continue

    print(f"   > Red Global lista con {len(global_links_geoms)} segmentos.")

    # 2. CARGAR SECTORES
    print("2. Cruzando con Sectores...")
    gdf_sectores = gpd.read_file(PATH_SHP_SECTORES)

    with rasterio.open(PATH_TIF_RIO) as src:
        crs_raster = src.crs
    if gdf_sectores.crs != crs_raster:
        gdf_sectores = gdf_sectores.to_crs(crs_raster)

    resultados_ebi = []

    # 3. INTERSECCIÓN VECTORIAL
    for idx, row in gdf_sectores.iterrows():
        try:
            nombre = row[COLUMNA_ID]
        except:
            nombre = f"Seg_{idx}"

        print(f"   > {nombre}...", end=" ")

        poly = row.geometry

        # A. Recortar Eje Maestro
        try:
            if not global_centerline_geom.intersects(poly):
                print("Eje fuera. (eBI=1.0)")
                resultados_ebi.append(1.0)
                continue

            eje_recortado = global_centerline_geom.intersection(poly)

            # Limpieza si corta en múltiples pedazos
            if eje_recortado.is_empty:
                resultados_ebi.append(1.0);
                continue
            if eje_recortado.geom_type == 'MultiLineString':
                eje_recortado = max(eje_recortado.geoms, key=lambda x: x.length)
            if eje_recortado.geom_type != 'LineString':  # GeometryCollection, etc.
                resultados_ebi.append(1.0);
                continue

        except:
            print("Err Eje. (1.0)")
            resultados_ebi.append(1.0)
            continue

        # B. Recortar Links
        links_recortados = []
        for l_geom, l_ancho in global_links_geoms:
            if l_geom.intersects(poly):
                intersection = l_geom.intersection(poly)
                if not intersection.is_empty:
                    links_recortados.append((intersection, l_ancho))

        # C. Calcular eBI
        if not links_recortados:
            val = 1.0
        else:
            val = calcular_ebi_segmento_vectorial(links_recortados, eje_recortado)

        print(f"eBI: {val:.3f}")
        resultados_ebi.append(val)

    # 4. GUARDAR
    print("\n--- GUARDANDO RESULTADOS ---")
    gdf_sectores['eBI_Final'] = resultados_ebi
    out_shp = os.path.join(PATH_SALIDA, "Valle_eBI_GlobalLocal_V2.shp")
    gdf_sectores.to_file(out_shp)
    print(f"✅ Listo: {out_shp}")