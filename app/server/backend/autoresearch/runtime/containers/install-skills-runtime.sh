#!/bin/sh
# Runs during image construction, never on the host or in a user session.
set -eu
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends \
  ca-certificates curl xz-utils fontconfig fonts-liberation2 fonts-noto-cjk \
  poppler-utils pandoc libreoffice-writer libreoffice-impress \
  imagemagick ghostscript tesseract-ocr tesseract-ocr-eng tesseract-ocr-chi-sim \
  texlive-xetex texlive-latex-extra texlive-lang-chinese texlive-fonts-recommended \
  dvisvgm pdf2svg \
  r-base-core r-cran-ggplot2 r-cran-patchwork r-cran-svglite r-cran-ragg \
  r-cran-circlize r-cran-jsonlite r-cran-systemfonts r-cran-rcolorbrewer \
  r-cran-pdftools r-bioc-complexheatmap

# Freeze installed packages that define the trained-model runtime. Extra skill
# packages may add dependencies but may not silently upgrade these components.
python - <<'PY'
from importlib.metadata import version, PackageNotFoundError
from pathlib import Path
names = ['torch','torchvision','torchaudio','numpy','pandas','scipy','scikit-learn',
         'Pillow','timm','transformers','huggingface-hub','safetensors','open_clip_torch']
pins = []
for name in names:
    try:
        pins.append(f'{name}=={version(name)}')
    except PackageNotFoundError:
        pass
Path('/opt/pathlab/ml-constraints.txt').write_text('\n'.join(pins) + '\n')
PY
python -m pip install --no-cache-dir -c /opt/pathlab/ml-constraints.txt \
  -r /opt/pathlab/skills-runtime-requirements.txt
# Run from the complete skill tree: the CLI resolves prompts/schemas relative to
# its source, which a standalone wheel in site-packages cannot preserve.
python - <<'PY'
import sysconfig
from pathlib import Path
target = Path(sysconfig.get_path('scripts')) / 'image2ppt'
target.write_text('#!/bin/sh\nexec python /opt/pathlab/skill-library/nature-skills/skills/nature-image2ppt/cli/image2ppt/cli.py "$@"\n')
target.chmod(0o755)
PY

# Official Node binary with checksum verification; no curl-to-shell installer.
NODE_VERSION=v22.23.4
cd /tmp
curl -fSL --retry 3 -O "https://nodejs.org/dist/$NODE_VERSION/node-$NODE_VERSION-linux-x64.tar.xz"
curl -fSL --retry 3 -O "https://nodejs.org/dist/$NODE_VERSION/SHASUMS256.txt"
grep " node-$NODE_VERSION-linux-x64.tar.xz\$" SHASUMS256.txt | sha256sum -c -
tar -xJf "node-$NODE_VERSION-linux-x64.tar.xz" -C /opt
ln -sfnT "/opt/node-$NODE_VERSION-linux-x64" /opt/node
export PATH=/opt/node/bin:$PATH
export PLAYWRIGHT_BROWSERS_PATH=/opt/playwright
python -m playwright install --with-deps chromium
export PUPPETEER_SKIP_DOWNLOAD=true
npm install --global --no-audit --no-fund --ignore-scripts \
  pptxgenjs@4.0.1 @mermaid-js/mermaid-cli@11.4.0 puppeteer@23.1.1
mkdir -p /opt/pathlab
python - <<'PY'
import json
from pathlib import Path
chromium = next(Path('/opt/playwright').glob('chromium-*/chrome-linux*/chrome'))
Path('/opt/pathlab/puppeteer.json').write_text(json.dumps({
    'executablePath': str(chromium), 'args': ['--no-sandbox', '--disable-dev-shm-usage']
}))
Path('/opt/pathlab/chromium-path').write_text(str(chromium))
PY
cat > /usr/local/bin/pathlab-mermaid <<'SH'
#!/bin/sh
exec /opt/node/bin/mmdc -p /opt/pathlab/puppeteer.json "$@"
SH
chmod +x /usr/local/bin/pathlab-mermaid
fc-cache -f
python -m pip freeze > /opt/pathlab/skills-python-freeze.txt
dpkg-query -W > /opt/pathlab/skills-system-packages.txt
rm -f "/tmp/node-$NODE_VERSION-linux-x64.tar.xz" /tmp/SHASUMS256.txt
rm -rf /var/lib/apt/lists/* /root/.cache/pip /root/.npm
