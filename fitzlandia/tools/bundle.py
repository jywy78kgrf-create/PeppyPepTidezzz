#!/usr/bin/env python3
"""Bundle FitzLandia into a single self-contained HTML file (three.js loaded from CDN).
Usage: python3 tools/bundle.py [out.html]   -> default dist/fitzlandia.html"""
import os, re, sys
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(root, 'dist', 'fitzlandia.html')
html = open(os.path.join(root, 'index.html'), encoding='utf-8').read()
css = open(os.path.join(root, 'style.css'), encoding='utf-8').read()
html = html.replace('<link rel="stylesheet" href="style.css">', '<style>\n' + css + '\n</style>')
html = re.sub(r'<link rel="apple-touch-icon"[^>]*>\n?', '', html)
html = re.sub(r'<link rel="icon".*\n', '', html)
html = html.replace('<script src="vendor/three.min.js"></script>\n<script>if(!window.THREE){document.write(\'<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/0.158.0/three.min.js"><\\/script>\')}</script>',
                    '<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/0.158.0/three.min.js"></script>')
def inline(m):
    src = m.group(1)
    js = open(os.path.join(root, src), encoding='utf-8').read().replace('</script', '<\\/script')
    return '<script>\n' + js + '\n</script>'
html = re.sub(r'<script src="(js/[^"]+)"></script>', inline, html)
os.makedirs(os.path.dirname(out), exist_ok=True)
open(out, 'w', encoding='utf-8').write(html)
print('wrote', out, len(html), 'bytes')
