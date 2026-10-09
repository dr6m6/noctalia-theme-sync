{ lib, python3Packages }:
python3Packages.buildPythonApplication {
  pname = "noctalia-theme-sync";
  version = "0.2.1";
  pyproject = true;
  src = lib.cleanSourceWith {
    src = ../.;
    filter = path: type:
      lib.cleanSourceFilter path type &&
      !(builtins.elem (builtins.baseNameOf path) [
        "dist" "build" ".venv" ".ruff_cache" ".pytest_cache" "__pycache__"
      ]);
  };
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
