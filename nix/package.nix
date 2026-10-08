{ lib, python3Packages }:
python3Packages.buildPythonApplication {
  pname = "noctalia-theme-sync";
  version = "0.1.0";
  pyproject = true;
  src = lib.cleanSource ../.;
  build-system = [ python3Packages.setuptools ];
  nativeCheckInputs = [ python3Packages.jsonschema ];
  checkPhase = ''
    PYTHONPATH=src:$PYTHONPATH python -m unittest discover -s tests -q
  '';
  pythonImportsCheck = [ "noctalia_theme_sync" ];
  meta = {
    description = "Noctalia v5 per-user palette adapters and optional local theme bridge";
    homepage = "https://github.com/dr6m6/noctalia-theme-sync";
    license = lib.licenses.mit;
    platforms = lib.platforms.linux;
    mainProgram = "noctalia-theme-sync";
  };
}
