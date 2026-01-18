# RiverDynamics Core 🌊

**RiverDynamics** es una suite de herramientas *open-source* desarrollada en Python para la ingeniería fluvial. Este repositorio contiene las versiones estables y fundamentales de algoritmos diseñados para el procesamiento de geometrías de ríos, cálculo de índices geomorfológicos y análisis de dinámicas fluviales temporales.

El objetivo es proporcionar a la comunidad científica herramientas reproducibles y eficientes para el estudio de la morfodinámica de ríos meándricos y entrelazados.

## 🛠️ Módulos Principales

### 1. MOR Calculator (Migration/Occupation Rate)
Algoritmo en Python diseñado para calcular la **actividad fluvial** de un río a lo largo de una serie temporal. El script analiza la dinámica de migración en secciones transversales definidas dentro del valle de inundación.
* **Base Teórica:** Implementación basada en la metodología propuesta por *Chichon & Abad (2025)* para la cuantificación de tasas de migración y ocupación en entornos fluviales dinámicos.

### 2. eBI Adapter (Entropic Braiding Index)
Una adaptación optimizada del índice de entrelazamiento entrópico. Permite cuantificar la complejidad de la red de canales de un río, ofreciendo métricas precisas sobre la intensidad del entrelazamiento (braiding intensity) en diferentes tramos.

### 3. River Suites (Pre-procesamiento)
Conjunto de utilidades esenciales para preparar la data geoespacial antes del análisis:
* Etiquetado automático de ríos.
* Cálculo y suavizado de *centerlines* (ejes de río).
* Seccionamiento automatizado de valles de inundación.
* Limpieza de geometrías y conversión de coordenadas.

## 📦 Requisitos
Las dependencias principales para ejecutar estos scripts se encuentran en el archivo `requirements.txt`.

## 📄 Licencia
Este proyecto está bajo la Licencia **MIT**. Consulte el archivo `LICENSE` para más detalles.