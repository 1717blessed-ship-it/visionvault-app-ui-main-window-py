Icons in this folder:

- chip_success.svg — green rounded chip example
- chip_error.svg — red rounded chip example
- icon_money.svg — circular money icon
- icon_paid.svg — circular paid/check icon

Generate PNGs from SVG using Inkscape or ImageMagick. Examples:

Inkscape:

```bash
inkscape "chip_success.svg" --export-type="png" --export-width=320 --export-height=64 -o chip_success.png
```

ImageMagick (rsvg or librsvg required for SVG rendering):

```bash
magick convert -density 300 chip_success.svg -resize 320x64 chip_success.png
```

Or use cairosvg (Python):

```bash
python -m pip install cairosvg
python -c "import cairosvg; cairosvg.svg2png(url='chip_success.svg', write_to='chip_success.png', output_width=320, output_height=64)"
```

If you want, I can generate PNGs and add them to the repo — tell me which sizes you prefer (e.g. card chip 160x32, icons 28x28).