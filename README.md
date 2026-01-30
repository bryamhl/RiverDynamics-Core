# 🌊 RiverDynamics Core

![Python](https://img.shields.io/badge/Python-3.8%2B-blue)
![License](https://img.shields.io/badge/License-MIT-green)
![Status](https://img.shields.io/badge/Status-Scientific%20Research-orange)

**RiverDynamics Core** es una colección de scripts *open-source* desarrollada en Python para la ingeniería fluvial. Este repositorio contiene los algoritmos fundamentales para el procesamiento de geometrías de ríos, cálculo de índices geomorfológicos y análisis de dinámicas fluviales básicas.

El objetivo es proporcionar a la comunidad científica herramientas reproducibles para el estudio de la morfodinámica de ríos meándricos y entrelazados, basadas en literatura académica validada.

> ⚠️ **Nota:** Este repositorio contiene la implementación **manual y por scripts** de los algoritmos. Para la versión comercial automatizada con GUI, procesamiento por lotes y gestión de sesiones, consulte la arquitectura **RiverDynamics PRO**.

## 🛠️ Módulos Principales

### 1. MOR Calculator (Migration/Occupation Rate)
Algoritmo para calcular la actividad fluvial básica comparando pares de años.
* **Metodología:** Basado en *Chichon & Abad (2025)*. Calcula áreas de erosión, deposición e intersección sobre un *Shapefile* de valle proyectado.
* **Funcionalidad:**
  * Procesa **un par de imágenes** a la vez (T1 vs T2).
  * **Input:** Requiere imágenes satelitales binarias (Rasters .tif).
  * **Nomenclatura:** Se recomienda el formato `NombreRio+Año.tif` para reconocimiento automático. De lo contrario, la entrada de parámetros es manual.
  * **Output:** Genera archivos *Shapefile* (SHP) de los cambios geomorfológicos y muestra una tabla resumen de áreas en la consola/terminal.

### 2. eBI Adapter (Entropic Braiding Index)
Adaptación del Índice de Entrelazamiento Entrópico (basado en *Tejedor et al.*).
* **Capacidad:** Cuantifica la complejidad de la red de canales (Braiding Intensity).
* **Limitación Core:** Diseñado para calcular el índice de **un año a la vez**.
* **Interfaz:** Ejecución mediante consola de comandos.

### 3. River Suites (Scripts de Pre-procesamiento)
Colección de scripts independientes (dispersos) para la preparación de data geoespacial.
* **Herramientas:** Etiquetado, limpieza de geometría y conversiones básicas.
* **Uso:** El usuario debe configurar manualmente las rutas (*paths*) de los archivos en el código antes de ejecutar cada script.

## 📦 Requisitos y Uso
Las dependencias se encuentran en `requirements.txt`.
Para el correcto funcionamiento del cálculo de áreas, es indispensable que el *Shapefile* del valle cuente con una columna de etiquetas (IDs) y esté correctamente proyectado (UTM).

## 📄 Licencia
Este proyecto está bajo la Licencia **MIT**. Consulte el archivo `LICENSE` para más detalles.
