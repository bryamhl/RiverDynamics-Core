import os
os.environ['GDAL_DATA'] = r"C:\Users\ASUS\.conda\envs\TESIS\Library\share\gdal"  # Evita warning de GDAL
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog
import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString, Point
import numpy as np
from scipy.interpolate import splprep, splev
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

# Suavizado con B-spline (reemplazo del método PAEK)
def bspline_smoothing(line, smoothing_factor=0):
    coords = np.array(line.coords)
    if len(coords) < 4:
        return line  # No se puede suavizar una línea con menos de 4 puntos
    x, y = coords[:, 0], coords[:, 1]
    tck, u = splprep([x, y], s=smoothing_factor)
    unew = np.linspace(0, 1.0, len(x) * 10)
    out = splev(unew, tck)
    smoothed_coords = list(zip(out[0], out[1]))
    return LineString(smoothed_coords)

# Crear puntos cada X metros
def generate_points_along_line(line, spacing):
    length = line.length
    distances = np.arange(0, length, spacing)
    return [line.interpolate(distance) for distance in distances]

# Guardar Excel (.xlsx) con columnas separadas correctamente
def save_coords_to_excel(points, output_excel):
    coords = [(pt.x, pt.y) for pt in points]
    df = pd.DataFrame(coords, columns=["a", "b"])
    df.to_excel(output_excel, index=False, header=False)

# Mostrar previsualización interactiva con zoom y pan
def show_preview_interactive(original_line, smooth_line):
    preview_window = tk.Toplevel()
    preview_window.title("Previsualización interactiva")

    fig, ax = plt.subplots(figsize=(10, 6))
    x1, y1 = original_line.xy
    x2, y2 = smooth_line.xy
    ax.plot(x1, y1, label='Original', color='gray', linestyle='--')
    ax.plot(x2, y2, label='Suavizada', color='blue')
    ax.set_title("Comparación de línea original y suavizada")
    ax.set_xlabel("X")
    ax.set_ylabel("Y")
    ax.legend()
    ax.grid(True)

    canvas = FigureCanvasTkAgg(fig, master=preview_window)
    canvas.draw()
    canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

    toolbar_frame = tk.Frame(preview_window)
    toolbar_frame.pack()

    from matplotlib.backends.backend_tkagg import NavigationToolbar2Tk
    toolbar = NavigationToolbar2Tk(canvas, toolbar_frame)
    toolbar.update()

# Función principal
class RiverApp:
    def __init__(self, master):
        self.master = master
        master.title("Procesador de Líneas de Río")

        tk.Label(master, text="Nombre del río:").grid(row=0, column=0, sticky="e")
        tk.Label(master, text="Año:").grid(row=1, column=0, sticky="e")
        tk.Label(master, text="Ancho promedio del río (m):").grid(row=2, column=0, sticky="e")

        self.river_name_entry = tk.Entry(master)
        self.year_entry = tk.Entry(master)
        self.width_entry = tk.Entry(master)

        self.river_name_entry.grid(row=0, column=1)
        self.year_entry.grid(row=1, column=1)
        self.width_entry.grid(row=2, column=1)

        self.select_btn = tk.Button(master, text="Seleccionar SHP de línea central", command=self.load_shapefile)
        self.select_btn.grid(row=3, column=0, columnspan=2, pady=5)

        self.preview_btn = tk.Button(master, text="Previsualizar suavizado", command=self.preview)
        self.preview_btn.grid(row=4, column=0, columnspan=2, pady=5)

        self.run_btn = tk.Button(master, text="Ejecutar", command=self.run)
        self.run_btn.grid(row=5, column=0, columnspan=2, pady=10)

    def load_shapefile(self):
        self.shapefile_path = filedialog.askopenfilename(filetypes=[("Shapefiles", "*.shp")])

    def preview(self):
        if not hasattr(self, 'shapefile_path'):
            messagebox.showerror("Error", "Primero selecciona un archivo shapefile.")
            return

        gdf = gpd.read_file(self.shapefile_path)
        # Reemplazo de unary_union por union_all
        line = gdf.geometry.union_all()
        if line.geom_type == 'MultiLineString':
            line = max(line.geoms, key=lambda l: l.length)
        elif line.geom_type != 'LineString':
            messagebox.showerror("Error", "La geometría no es una línea válida.")
            return

        try:
            smoothing = float(simpledialog.askstring("Tolerancia de suavizado", "Ingresa la tolerancia (en metros):"))
        except:
            messagebox.showerror("Error", "Tolerancia inválida.")
            return

        smooth_line = bspline_smoothing(line, smoothing_factor=smoothing)
        show_preview_interactive(line, smooth_line)

    def run(self):
        river_name = self.river_name_entry.get().strip().replace(" ", "_")
        year = self.year_entry.get().strip()
        width = float(self.width_entry.get().strip())

        if not hasattr(self, 'shapefile_path'):
            messagebox.showerror("Error", "No se ha seleccionado un archivo shapefile.")
            return

        input_folder = os.path.dirname(self.shapefile_path)
        folder_name = f"RESULTADOS_{river_name}_{year}"
        result_dir = os.path.join(input_folder, folder_name)
        os.makedirs(result_dir, exist_ok=True)

        gdf = gpd.read_file(self.shapefile_path)
        # Reemplazo de unary_union por union_all
        line = gdf.geometry.union_all()
        if line.geom_type == 'MultiLineString':
            line = max(line.geoms, key=lambda l: l.length)
        elif line.geom_type != 'LineString':
            messagebox.showerror("Error", "La geometría cargada no es una línea válida.")
            return

        smooth_line = bspline_smoothing(line, smoothing_factor=width)
        gdf_smooth = gpd.GeoDataFrame(geometry=[smooth_line], crs=gdf.crs)
        out_line_path = os.path.join(result_dir, f"CL_{river_name}_{year}_POL.shp")
        gdf_smooth.to_file(out_line_path)

        spacing = width / 2
        points = generate_points_along_line(smooth_line, spacing)
        gdf_points = gpd.GeoDataFrame(geometry=points, crs=gdf.crs)
        out_points_path = os.path.join(result_dir, f"VERT_{river_name}_{year}.shp")
        gdf_points.to_file(out_points_path)

        out_excel_path = os.path.join(result_dir, f"CL_{river_name}_{year}.xlsx")
        save_coords_to_excel(points, out_excel_path)

        messagebox.showinfo("Éxito", f"¡Proceso completado! Archivos guardados en:\n{result_dir}")

if __name__ == "__main__":
    root = tk.Tk()
    app = RiverApp(root)
    root.mainloop()
