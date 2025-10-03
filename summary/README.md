# GROBID PDF Processing Test

Este script prueba el procesamiento de PDFs científicos usando GROBID.

## Requisitos

1. **Java JDK 17+** instalado y en PATH
2. **GROBID instalado y corriendo** en `localhost:8070`
3. **Python dependencies**: `grobid-client-python` (ya instalado)
4. **PDF de prueba**: `aiayn.pdf` en la raíz del proyecto

## Instalación de Java

```bash
# Instalar OpenJDK 17 con Homebrew
brew install openjdk@17

# Agregar al PATH (agregar a ~/.zshrc)
echo 'export PATH="/opt/homebrew/opt/openjdk@17/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc

# Verificar instalación
java -version
```

## Instalación de GROBID

```bash
# 1. Clona el repositorio
git clone https://github.com/kermitt2/grobid.git
cd grobid

# 2. Ejecuta GROBID (toma varios minutos la primera vez)
./gradlew run
```

Espera a que aparezca: `GROBID server is running on port 8070`

## Ejecución

```bash
# Desde la raíz del proyecto
.venv/bin/python backend/summary/test_grobid.py

# Opcional: especificar otro PDF
.venv/bin/python backend/summary/test_grobid.py /ruta/a/otro/paper.pdf
```

## Qué hace

- ✅ Verifica que GROBID esté corriendo
- 📄 Extrae título del paper
- 📝 Extrae abstract
- 📚 Identifica secciones del documento
- 🖼️ Encuentra figuras con sus descripciones
- ➗ Localiza ecuaciones en LaTeX
- 📊 Proporciona metadata básica

## Salida esperada

Si todo funciona correctamente, verás algo como:

```
=== GROBID PDF Processing Test ===
PDF file: /Users/.../aiayn.pdf
Checking GROBID connection...
✅ GROBID está corriendo correctamente
Procesando PDF...

📄 Title: [Título del paper]
📝 Abstract: [Resumen del paper]...
📚 Sections found: 6
  1. Introduction
     Text: [Contenido de la introducción]...
🖼️ Figures found: 3
  Figure 1: [Descripción de la figura]...
➗ Equations found: 5
  Eq 1: [Ecuación en LaTeX]...
📊 Metadata:
  Total pages: 12

✅ Test completed successfully!
```

## Troubleshooting

- **"GROBID no está disponible"**: Asegúrate de que GROBID esté corriendo
- **"PDF not found"**: Verifica que `aiayn.pdf` esté en la raíz del proyecto
- **Errores de conexión**: Revisa que el puerto 8070 no esté ocupado

## Próximos pasos

Una vez que funcione, este código se puede integrar en el pipeline de resumen de DeepRead.